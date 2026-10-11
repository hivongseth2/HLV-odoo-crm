# -*- coding: utf-8 -*-
"""Chế độ API key: chính Odoo gọi Claude API, không cần máy văn phòng nào bật.

Cron cầm tin từ CÙNG hàng chờ với agent poll (claim_jobs, SKIP LOCKED), mỗi cuộc chạy
trong một luồng riêng với cursor riêng để vài sale chat cùng lúc không phải xếp hàng
nhau. Tool MISA chạy y như khi đi qua /product_agent/agent/tool: cùng handler, cùng chốt
"chỉ tạo đúng thứ đã đề xuất", cùng khoá tạo mã, cùng nhật ký.

Không gọi Claude ngay trong request /chat/send: một lượt có thể mất cả phút (tra MISA,
đọc web), giữ worker HTTP lâu như vậy là treo trang cho người khác.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from odoo import SUPERUSER_ID, api, models
from odoo.modules.registry import Registry

from ..services.claude_api_payload import (
    DEFAULT_EFFORT, DEFAULT_MODEL, EFFORT_CHOICES, MAX_TOKENS, MODEL_CHOICES,
    build_system, build_tools, context_key, history_content, history_too_long,
    load_history, reply_text, request_extras, tool_result, tool_uses, user_content,
)

_logger = logging.getLogger(__name__)

PARAM_MODE = 'hlv_product_agent.mode'
PARAM_API_KEY = 'hlv_product_agent.anthropic_api_key'
PARAM_MODEL = 'hlv_product_agent.api_model'
PARAM_EFFORT = 'hlv_product_agent.api_effort'
PARAM_PARALLEL = 'hlv_product_agent.api_parallel'
MODE_LOCAL = 'local'
MODE_API = 'api'
CRON_XMLID = 'hlv_product_agent.ir_cron_product_agent_api'

DEFAULT_PARALLEL = 2
MAX_PARALLEL = 4
# Cron chỉ nhận việc mới trong khoảng này rồi thôi (vẫn chờ các lượt đang chạy xong):
# không biết giới hạn thời gian cron của máy chủ, nên giữ mỗi lần chạy ngắn và tự hẹn
# lần sau nếu còn tin chờ.
CLAIM_WINDOW_SECONDS = 90
IDLE_POLL_SECONDS = 2
# Một lượt: tối đa ngần ấy lần gọi API và ngần ấy giây — dưới CLAIM_TIMEOUT_MINUTES
# của hội thoại để lượt không bị thả oan khi đang chạy.
MAX_STEPS = 15
TURN_DEADLINE_SECONDS = 360
REQUEST_TIMEOUT_SECONDS = 180


# Thông điệp lỗi viết thẳng tiếng Việt, không qua _(): phần lớn được dựng trong luồng
# riêng / hàm không có self.env, nơi _() không tìm ra ngôn ngữ và ghi cảnh báo kèm stack.
class TurnFailed(Exception):
    """Lượt không xong được; thông điệp hiện cho sale đọc."""


class _StaleHistory(Exception):
    """API từ chối lịch sử đã lưu (đổi model / prompt mà vân tay không bắt được)."""


def _anthropic():
    # Import muộn: chế độ máy văn phòng không cần thư viện này, thiếu nó không được làm
    # hỏng cả module.
    try:
        import anthropic
    except ImportError:
        raise TurnFailed("Odoo chưa cài thư viện anthropic (thêm vào requirements.txt).")
    return anthropic


class HlvProductAgentApiRunner(models.AbstractModel):
    _name = 'hlv.product.agent.api.runner'
    _description = "Chạy trợ lý tạo mã hàng bằng Claude API"

    # =========================================================================
    # Cấu hình
    # =========================================================================
    @api.model
    def config(self):
        """Cấu hình chế độ API từ ir.config_parameter, đã chuẩn hoá về giá trị hợp lệ."""
        get = self.env['ir.config_parameter'].sudo().get_param
        try:
            parallel = int(get(PARAM_PARALLEL) or DEFAULT_PARALLEL)
        except ValueError:
            parallel = DEFAULT_PARALLEL
        model = get(PARAM_MODEL) or DEFAULT_MODEL
        effort = get(PARAM_EFFORT) or DEFAULT_EFFORT
        return {
            'mode': get(PARAM_MODE) or MODE_LOCAL,
            'api_key': (get(PARAM_API_KEY) or '').strip(),
            'model': model if model in dict(MODEL_CHOICES) else DEFAULT_MODEL,
            'effort': effort if effort in dict(EFFORT_CHOICES) else DEFAULT_EFFORT,
            'parallel': min(max(parallel, 1), MAX_PARALLEL),
        }

    @api.model
    def is_api_mode(self):
        return self.config()['mode'] == MODE_API

    @api.model
    def is_ready(self):
        """Đang ở chế độ API và đã có key — khung chat coi như "máy trợ lý đang bật"."""
        config = self.config()
        return config['mode'] == MODE_API and bool(config['api_key'])

    @api.model
    def wake(self):
        """Gọi cron chạy ngay (sale vừa gửi tin). Không ở chế độ API thì thôi."""
        if not self.is_ready():
            return
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def check_connection(self, api_key, model):
        """Thử key + model bằng Models API (không tốn token). Trả chuỗi báo kết quả."""
        anthropic = _anthropic()
        client = anthropic.Anthropic(api_key=api_key, timeout=30, max_retries=1)
        try:
            info = client.models.retrieve(model)
        except anthropic.AuthenticationError:
            raise TurnFailed("API key sai.")
        except anthropic.PermissionDeniedError:
            raise TurnFailed("API key không có quyền dùng model %s." % model)
        except anthropic.NotFoundError:
            raise TurnFailed("Tài khoản chưa dùng được model %s." % model)
        except anthropic.APIConnectionError:
            raise TurnFailed("Odoo không kết nối được tới Claude API.")
        except anthropic.APIStatusError as error:
            raise TurnFailed("Claude API lỗi %s." % error.status_code)
        return "Kết nối được, model %s." % (info.display_name or model)

    # =========================================================================
    # Cron
    # =========================================================================
    @api.model
    def _cron_run_queue(self):
        """Cầm tin chờ và chạy, song song tối đa `parallel` cuộc. Commit sau mỗi lần cầm."""
        config = self.config()
        Session = self.env['hlv.product.chat.session'].sudo()
        if config['mode'] != MODE_API:
            return
        Session.release_stale()
        self.env.cr.commit()
        if not config['api_key']:
            _logger.warning("PRODUCT_AGENT chế độ API nhưng chưa khai API key")
            return

        dbname = self.env.cr.dbname
        deadline = time.monotonic() + CLAIM_WINDOW_SECONDS
        running = []
        with ThreadPoolExecutor(max_workers=config['parallel'],
                                thread_name_prefix='hlv_product_agent_api') as pool:
            while True:
                running = [future for future in running if not future.done()]
                free = config['parallel'] - len(running)
                if free > 0 and time.monotonic() < deadline:
                    jobs = Session.claim_jobs(free)
                    # Commit ngay: luồng xử lý mở cursor riêng, phải thấy được lượt đã cầm.
                    self.env.cr.commit()
                    running += [
                        pool.submit(_run_job_in_thread, dbname, job['session_id'], job['claim_token'], config)
                        for job in jobs
                    ]
                if not running:
                    break
                time.sleep(IDLE_POLL_SECONDS)

        if self._has_waiting():
            self.env.ref(CRON_XMLID)._trigger()

    @api.model
    def _has_waiting(self):
        return bool(self.env['hlv.product.chat.message'].sudo().search_count([
            ('to_send', '=', True), ('session_id.state', '=', 'idle'),
        ], limit=1))

    # =========================================================================
    # Một lượt
    # =========================================================================
    @api.model
    def _run_turn(self, session_id, claim_token, config):
        """Chạy trọn một lượt rồi chốt bằng deliver_reply. Chạy trong luồng riêng."""
        Session = self.env['hlv.product.chat.session'].sudo()
        session = Session.from_claim(claim_token)
        if not session:
            return
        reply, error, history_vals = '', None, {}
        try:
            reply, history, key = self._converse(session, claim_token, config)
            history_vals = {'api_messages': json.dumps(history, ensure_ascii=False), 'api_context_key': key}
        except TurnFailed as failure:
            error = str(failure)
        except Exception as failure:  # noqa: BLE001 — sale phải nhận được câu báo lỗi
            _logger.exception("PRODUCT_AGENT API lượt %s lỗi", claim_token)
            self.env.cr.rollback()
            error = "lỗi hệ thống: %s" % failure

        self.env.invalidate_all()
        session = Session.from_claim(claim_token)
        if not session:
            _logger.info("PRODUCT_AGENT bỏ câu trả lời muộn của lượt %s", claim_token)
            return
        # Lượt lỗi: bỏ lịch sử API, lượt sau mở lại từ tóm tắt chữ (kèm lời dặn không chạy
        # lại lệnh cũ) — giữ lịch sử dở dang là Claude tưởng lệnh ghi chưa từng chạy.
        # claude_session_id: phiên Claude Code trên máy văn phòng không biết lượt này.
        session.write(dict(history_vals or {'api_messages': False, 'api_context_key': False},
                           claude_session_id=False))
        session.deliver_reply(reply, error=error)
        self.env.cr.commit()

    def _converse(self, session, claim_token, config):
        """Trả ``(reply, history, context_key)``. Raise TurnFailed khi không xong."""
        prompt_text, prompt_ver = self.env['hlv.product.agent.prompt'].sudo().build_prompt()
        key = context_key(config['model'], prompt_ver)
        history = load_history(session.api_messages) if session.api_context_key == key else []
        if history and history_too_long(history, session.api_last_prompt_tokens):
            history = []
        turn = session.api_turn_input()
        try:
            return self._run_steps(session, claim_token, config, prompt_text, history, turn) + (key,)
        except _StaleHistory:
            _logger.info("PRODUCT_AGENT API từ chối lịch sử cuộc %s, mở lại", session.id)
            return self._run_steps(session, claim_token, config, prompt_text, [], turn) + (key,)

    def _run_steps(self, session, claim_token, config, prompt_text, history, turn):
        """Vòng gọi API + chạy tool cho tới khi Claude trả lời xong. Trả ``(reply, messages)``."""
        anthropic = _anthropic()
        client = anthropic.Anthropic(api_key=config['api_key'], timeout=REQUEST_TIMEOUT_SECONDS)
        model = config['model']
        text = turn['prompt'] if history else turn['prompt_cold']
        messages = history + [{'role': 'user', 'content': user_content(text, turn['images'])}]
        params = dict(
            model=model, max_tokens=MAX_TOKENS,
            system=build_system(prompt_text), tools=build_tools(model),
            thinking={'type': 'adaptive'}, output_config={'effort': config['effort']},
            # Điểm cache tự động ở cuối hội thoại: lượt sau đọc lại lịch sử với giá cache.
            cache_control={'type': 'ephemeral'},
            **request_extras(model),
        )
        started = time.monotonic()
        for step in range(MAX_STEPS):
            if time.monotonic() - started > TURN_DEADLINE_SECONDS:
                raise TurnFailed("Claude chạy quá %s giây" % TURN_DEADLINE_SECONDS)
            response = self._request(anthropic, client, params, messages, stale_ok=bool(history) and step == 0)
            self._record_usage(session, response)
            if response.stop_reason == 'refusal':
                raise TurnFailed("Claude từ chối xử lý yêu cầu này")
            content = history_content(response.to_dict(mode='json').get('content'))
            messages.append({'role': 'assistant', 'content': content})
            if response.stop_reason == 'pause_turn':
                # Tool web chạy dài, máy chủ tạm dừng: gửi lại nguyên văn là chạy tiếp.
                continue
            calls = tool_uses(content)
            if response.stop_reason == 'tool_use' and calls:
                messages.append({'role': 'user', 'content': [
                    tool_result(call['id'], self._call_tool(claim_token, call)) for call in calls
                ]})
                continue
            if response.stop_reason == 'max_tokens':
                raise TurnFailed("câu trả lời quá dài, bị cắt")
            return reply_text(content), messages
        raise TurnFailed("Claude gọi tool quá %s lần trong một lượt" % MAX_STEPS)

    @staticmethod
    def _request(anthropic, client, params, messages, stale_ok):
        """Một lần gọi Messages API, đổi lỗi SDK thành câu sale đọc được."""
        try:
            return client.beta.messages.create(messages=messages, **params)
        except anthropic.BadRequestError as error:
            if stale_ok:
                raise _StaleHistory() from error
            _logger.warning("PRODUCT_AGENT API 400: %s", error)
            raise TurnFailed("Claude API không nhận yêu cầu (%s)" % str(error)[:200])
        except anthropic.AuthenticationError:
            raise TurnFailed("API key Claude sai hoặc đã bị thu hồi")
        except anthropic.PermissionDeniedError:
            raise TurnFailed("API key Claude không có quyền dùng model này")
        except anthropic.RateLimitError:
            raise TurnFailed("Claude API đang hết hạn mức, thử lại sau ít phút")
        except anthropic.APIConnectionError:
            raise TurnFailed("không kết nối được Claude API")
        except anthropic.APIStatusError as error:
            raise TurnFailed("Claude API lỗi %s, thử lại sau" % error.status_code)

    def _call_tool(self, claim_token, call):
        """Chạy một tool MISA và commit ngay, như mỗi lần agent gọi /product_agent/agent/tool.

        Commit từng tool: hàng đã tạo trên MISA phải nằm trong nhật ký dù bước sau lỗi, và
        khoá tạo mã (advisory lock theo transaction) được nhả cho lượt khác.
        """
        self.env.invalidate_all()
        session = self.env['hlv.product.chat.session'].sudo().from_claim(claim_token)
        if not session:
            return {'status': 'error', 'message': 'Lượt xử lý đã đóng, không chạy tool nữa.'}
        try:
            result = self.env['hlv.product.agent.tools'].sudo().run(
                session, call.get('name') or '', call.get('input') or {})
            self.env.cr.commit()
        except Exception as error:  # noqa: BLE001 — Claude phải nhận được kết quả lỗi
            self.env.cr.rollback()
            _logger.exception("PRODUCT_AGENT API tool %s lỗi", call.get('name'))
            result = {'status': 'error', 'message': str(error)[:300]}
        return result

    def _record_usage(self, session, response):
        usage = response.usage
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        _logger.info("PRODUCT_AGENT API cuộc %s %s: in=%s cache_read=%s cache_write=%s out=%s stop=%s",
                     session.id, response.model, usage.input_tokens, cache_read, cache_write,
                     usage.output_tokens, response.stop_reason)
        session.write({
            'api_input_tokens': session.api_input_tokens + (usage.input_tokens or 0) + cache_write,
            'api_cache_read_tokens': session.api_cache_read_tokens + cache_read,
            'api_output_tokens': session.api_output_tokens + (usage.output_tokens or 0),
            'api_last_prompt_tokens': (usage.input_tokens or 0) + cache_read + cache_write,
        })

def _run_job_in_thread(dbname, session_id, claim_token, config):
    """Một lượt trong luồng riêng, cursor riêng (cursor của cron không dùng chung luồng)."""
    threading.current_thread().dbname = dbname
    try:
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['hlv.product.agent.api.runner']._run_turn(session_id, claim_token, config)
    except Exception:  # noqa: BLE001 — lỗi một lượt không được giết cả cron
        _logger.exception("PRODUCT_AGENT API luồng lượt %s chết", claim_token)
