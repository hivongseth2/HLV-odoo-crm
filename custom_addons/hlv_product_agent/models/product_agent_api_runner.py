# -*- coding: utf-8 -*-
"""Chế độ API key: chính Odoo gọi Claude API, không cần máy văn phòng nào bật.

Sale gửi tin là Odoo mở NGAY một luồng nền (sau khi request /chat/send commit) để cầm tin
và chạy — không đợi cron: cron của Odoo chạy lần lượt từng job trong một luồng, đứng sau
cron đồng bộ MISA / mail là chờ cả mấy phút. Cron 1 phút chỉ để vớt tin sót (worker khởi
động lại, luồng chết) và dọn lượt treo.

Cầm tin từ CÙNG hàng chờ với agent poll (claim_jobs, SKIP LOCKED), có khoá chung giới hạn
số cuộc chạy cùng lúc trên mọi worker. Mỗi luồng một cursor riêng. Tool MISA chạy y như khi
đi qua /product_agent/agent/tool: cùng handler, cùng chốt "chỉ tạo đúng thứ đã đề xuất",
cùng khoá tạo mã, cùng nhật ký.

Không chạy Claude trong chính request /chat/send: một lượt có thể mất cả phút, trang của
sale phải trả về ngay.
"""
import json
import logging
import threading
import time

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
# không biết giới hạn thời gian cron của máy chủ, nên giữ mỗi lần chạy ngắn.
CLAIM_WINDOW_SECONDS = 90
# Khoá chung khi đếm + cầm việc: nhiều worker HTTP / cron cùng cầm thì vẫn không vượt quá
# số cuộc song song đã cấu hình.
CLAIM_LOCK_KEY = 'hlv_product_agent.api_claim'
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


def _client(anthropic, api_key, **options):
    """Client Claude API chỉ nhận câu trả lời nén gzip.

    httpx2 thấy có module brotli là xin nén brotli, rồi gọi API của brotli >= 1.2. Máy
    chủ Odoo có sẵn brotli cũ: giải nén lỗi TypeError, SDK báo thành "không kết nối được"
    và thử lại mãi vẫn hỏng. Xin gzip thì không phụ thuộc bản brotli nào.
    """
    return anthropic.Anthropic(
        api_key=api_key, default_headers={'Accept-Encoding': 'gzip, deflate'}, **options)


def _connection_cause(error):
    """Lỗi gốc bên dưới APIConnectionError, để biết là mạng hay lỗi khác bị gói lại."""
    cause = error.__cause__ or error.__context__
    return ("%s: %s" % (type(cause).__name__, cause))[:150] if cause else str(error)


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
        """Sale vừa gửi tin: chạy luôn trong luồng nền, sau khi request commit.

        Phải đợi commit: luồng mở cursor riêng, trước commit nó chưa thấy tin mới. Không ở
        chế độ API thì thôi.
        """
        if not self.is_ready():
            return
        config, dbname = self.config(), self.env.cr.dbname
        self.env.cr.postcommit.add(lambda: _start_drain_thread(dbname, config))

    @api.model
    def check_connection(self, api_key, model):
        """Thử key + model bằng Models API (không tốn token). Trả chuỗi báo kết quả."""
        anthropic = _anthropic()
        client = _client(anthropic, api_key, timeout=30, max_retries=1)
        try:
            info = client.models.retrieve(model)
        except anthropic.AuthenticationError:
            raise TurnFailed("API key sai.")
        except anthropic.PermissionDeniedError:
            raise TurnFailed("API key không có quyền dùng model %s." % model)
        except anthropic.NotFoundError:
            raise TurnFailed("Tài khoản chưa dùng được model %s." % model)
        except anthropic.APIConnectionError as error:
            _logger.warning("PRODUCT_AGENT kiểm tra Claude API lỗi kết nối", exc_info=True)
            raise TurnFailed("Odoo không kết nối được tới Claude API (%s)." % _connection_cause(error))
        except anthropic.APIStatusError as error:
            raise TurnFailed("Claude API lỗi %s." % error.status_code)
        return "Kết nối được, model %s." % (info.display_name or model)

    # =========================================================================
    # Cron
    # =========================================================================
    @api.model
    def _cron_run_queue(self):
        """Vớt tin sót: mở đủ luồng cho số tin đang chờ (trong giới hạn song song) và đợi xong."""
        config = self.config()
        if config['mode'] != MODE_API:
            return
        self.env['hlv.product.chat.session'].sudo().release_stale()
        self.env.cr.commit()
        if not config['api_key']:
            _logger.warning("PRODUCT_AGENT chế độ API nhưng chưa khai API key")
            return
        deadline = time.monotonic() + CLAIM_WINDOW_SECONDS
        threads = [
            _start_drain_thread(self.env.cr.dbname, config, deadline)
            for _i in range(min(self._waiting_count(), config['parallel']))
        ]
        for thread in threads:
            thread.join()

    @api.model
    def _waiting_count(self):
        """Số cuộc đang có tin chờ (không tính cuộc đang xử lý)."""
        self.env.cr.execute("""
            SELECT COUNT(DISTINCT m.session_id)
              FROM hlv_product_chat_message m
              JOIN hlv_product_chat_session s ON s.id = m.session_id
             WHERE m.to_send AND s.state = 'idle'
        """)
        return self.env.cr.fetchone()[0] or 0

    @api.model
    def _claim_one(self, config):
        """Cầm MỘT cuộc nếu còn chỗ trong giới hạn song song. Commit. Trả job hoặc None.

        Đếm và cầm dưới cùng một khoá advisory: hai worker cùng thấy "còn 1 chỗ" thì một
        bên phải đợi bên kia cầm xong, đếm lại mới cầm.
        """
        cr = self.env.cr
        cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [CLAIM_LOCK_KEY])
        cr.execute("SELECT COUNT(*) FROM hlv_product_chat_session WHERE state = 'processing'")
        busy = cr.fetchone()[0] or 0
        jobs = self.env['hlv.product.chat.session'].sudo().claim_jobs(1) if busy < config['parallel'] else []
        cr.commit()
        return jobs[0] if jobs else None

    @api.model
    def _drain(self, config, deadline=None):
        """Cầm và chạy lần lượt tới khi hết tin chờ, hết chỗ song song, hoặc quá deadline.

        Hết chỗ thì thôi cũng không sót: các luồng đang chạy xong lượt của mình sẽ quay lại
        cầm tiếp.
        """
        while deadline is None or time.monotonic() < deadline:
            self.env.invalidate_all()
            job = self._claim_one(config)
            if not job:
                return
            self._run_turn(job['session_id'], job['claim_token'], config)

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
        client = _client(anthropic, config['api_key'], timeout=REQUEST_TIMEOUT_SECONDS)
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
        except anthropic.APIConnectionError as error:
            _logger.warning("PRODUCT_AGENT Claude API lỗi kết nối", exc_info=True)
            raise TurnFailed("không kết nối được Claude API (%s)" % _connection_cause(error))
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

def _start_drain_thread(dbname, config, deadline=None):
    """Mở một luồng chạy hàng chờ. Trả thread (đã start).

    Không daemon: worker Odoo tự tắt (đủ số request, quá RAM mềm) sẽ đợi lượt đang dở xong
    thay vì cắt ngang giữa chừng một lệnh tạo mã.
    """
    thread = threading.Thread(target=_drain_in_thread, args=(dbname, config, deadline),
                              name='hlv_product_agent_api', daemon=False)
    thread.start()
    return thread


def _drain_in_thread(dbname, config, deadline):
    """Thân luồng: cursor riêng (cursor của request / cron không dùng chung luồng được)."""
    threading.current_thread().dbname = dbname
    try:
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['hlv.product.agent.api.runner']._drain(config, deadline)
    except Exception:  # noqa: BLE001 — lỗi một luồng không được giết worker
        _logger.exception("PRODUCT_AGENT API luồng xử lý chết")
