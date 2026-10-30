# -*- coding: utf-8 -*-
"""Chạy trợ lý quản trị bằng Claude API: Odoo tự gọi Claude, không qua máy văn phòng.

Gửi tin là Odoo mở NGAY một luồng nền (sau khi request /send commit) chạy lượt của đúng cuộc đó —
không đợi cron, cũng không chạy trong chính request: một lượt có thể mất cả phút. Cron 1 phút chỉ
vớt tin sót (worker khởi động lại giữa chừng) và dọn lượt treo.

Dùng lại của trợ lý tạo mã: gọi API + đổi lỗi (_request), đếm token (_record_usage), dựng nội dung
request (services.claude_api_payload), model phụ tra cứu, toàn bộ tool tạo mã / tra cứu.
"""
import json
import logging
import threading
import time
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules.registry import Registry

from odoo.addons.hlv_product_agent.models.product_agent_api_runner import (
    DELEGATE_TOOL_NAME, TurnFailed, _StaleHistory,
)
from odoo.addons.hlv_product_agent.services.claude_api_payload import (
    CACHE_CONTROL, MAX_TOKENS, build_system, history_content, load_history, request_extras, tool_result,
    tool_uses, turn_reply, user_content,
)
from odoo.addons.hlv_product_agent.services.claude_client import load_anthropic, make_client

from ..services.admin_payload import admin_context_key, admin_tools, history_expired
from ..services.crm_tools import CRM_TOOL_NAMES, CRM_WRITE_TOOL_NAMES

_logger = logging.getLogger(__name__)

# Lượt đang chạy giữ khoá advisory (khoá này + id cuộc) trên kết nối DB của luồng chạy nó: worker
# chết là kết nối đóng, khoá tự mất — cron nhờ đó biết lượt đã mồ côi mà thả ngay, khỏi đợi 12 phút.
TURN_LOCK_KEY = 'hlv_admin_agent.turn'
# Từ lúc cầm cuộc tới lúc luồng kịp giữ khoá chỉ vài mili giây; chừa rộng để cron không thả nhầm.
TURN_LOCK_SETTLE_SECONDS = 30
DEAD_TURN_ERROR = "lượt trả lời bị ngắt giữa chừng do máy chủ khởi động lại"
# Một báo giá nhiều dòng cần tra từng mã + giá cho khách: nhiều bước hơn trợ lý tạo mã. Hạn giờ vẫn
# dưới CLAIM_TIMEOUT_MINUTES của cuộc chat để lượt không bị thả oan khi đang chạy.
MAX_STEPS = 25
TURN_DEADLINE_SECONDS = 480
REQUEST_TIMEOUT_SECONDS = 180
# Tool ghi: chạy thành công rồi thì trong cùng lượt không chạy lại cùng tham số (Claude thử lại sau
# một kết quả nó hiểu nhầm là lỗi = báo giá thứ hai trên MISA).
PRODUCT_WRITE_TOOLS = frozenset({'create_product_misa', 'create_combo_misa', 'update_combo_misa',
                                 'update_product_misa'})
WRITE_TOOLS = CRM_WRITE_TOOL_NAMES | PRODUCT_WRITE_TOOLS


class _ProductSessionView:
    """Cuộc chat quản trị dưới dạng tool của trợ lý tạo mã cần (hlv.product.agent.tools.run).

    ``id`` False: nhật ký tạo hàng có khoá ngoại tới bảng hội thoại của sale — ghi id cuộc quản trị
    vào đó là lỗi khoá ngoại hoặc gắn nhầm sang cuộc chat của một sale. Nhật ký vẫn ghi tài khoản.
    """

    def __init__(self, session):
        self._session = session
        self.id = False
        self.user_id = session.user_id
        self.sale_name = session.user_id.name
        self.sale_code = False

    def previous_reply(self):
        return self._session.previous_reply()

    def post_event(self, text):
        return self._session.post_event(text)

    def post_client_action(self, text, action):
        return self._session.post_client_action(text, action)


class HlvAdminAgentRunner(models.AbstractModel):
    _name = 'hlv.admin.agent.runner'
    _description = "Chạy trợ lý quản trị bằng Claude API"

    @api.model
    def wake(self, session_id):
        """Có tin mới: chạy luồng nền cho cuộc này SAU khi request commit (trước đó luồng chưa thấy tin)."""
        dbname = self.env.cr.dbname
        self.env.cr.postcommit.add(lambda: _start_thread(dbname, session_id))

    # =========================================================================
    # Cron
    # =========================================================================
    @api.model
    def _cron_sweep(self):
        """Thả lượt treo / mồ côi, rồi chạy các cuộc còn tin chờ mà không luồng nào nhận."""
        self._release_dead_turns()
        self.env['hlv.admin.chat.session'].release_stale()
        self.env.cr.commit()
        self.env.cr.execute("""
            SELECT DISTINCT m.session_id FROM hlv_admin_chat_message m
              JOIN hlv_admin_chat_session s ON s.id = m.session_id
             WHERE m.to_send AND s.state = 'idle'
        """)
        threads = [_start_thread(self.env.cr.dbname, row[0]) for row in self.env.cr.fetchall()]
        for thread in threads:
            thread.join()

    @api.model
    def _release_dead_turns(self):
        """Thả ngay các lượt mà luồng chạy nó đã chết theo worker (lấy được khoá = không ai giữ)."""
        cr = self.env.cr
        settled = fields.Datetime.now() - timedelta(seconds=TURN_LOCK_SETTLE_SECONDS)
        sessions = self.env['hlv.admin.chat.session'].sudo().search([
            ('state', '=', 'processing'), ('claim_date', '<', settled)])
        for session in sessions:
            cr.execute("SELECT pg_try_advisory_lock(hashtext(%s), %s)", [TURN_LOCK_KEY, session.id])
            if not cr.fetchone()[0]:
                continue
            cr.execute("SELECT pg_advisory_unlock(hashtext(%s), %s)", [TURN_LOCK_KEY, session.id])
            _logger.warning("ADMIN_AGENT cuộc %s: luồng chạy lượt đã chết, thả lượt", session.id)
            session.deliver_reply('', error=DEAD_TURN_ERROR)

    # =========================================================================
    # Một cuộc, một lượt
    # =========================================================================
    @api.model
    def _serve(self, session_id):
        """Cầm và chạy lần lượt các lượt của một cuộc tới khi hết tin chờ.

        Tin gửi trong lúc Claude đang chạy được cầm ở vòng sau, không mất.
        """
        Session = self.env['hlv.admin.chat.session'].sudo()
        while True:
            self.env.invalidate_all()
            session = Session.browse(session_id).exists()
            token = session.claim() if session else ''
            self.env.cr.commit()
            if not token:
                return
            self._run_turn(session_id, token)

    @api.model
    def _run_turn(self, session_id, claim_token):
        """Chạy trọn một lượt, giữ khoá của lượt suốt thời gian chạy (xem _release_dead_turns)."""
        cr = self.env.cr
        cr.execute("SELECT pg_try_advisory_lock(hashtext(%s), %s)", [TURN_LOCK_KEY, session_id])
        try:
            self._play_turn(claim_token)
        finally:
            # Khoá cấp kết nối: commit / rollback không thả. Rollback trước vì lỗi lọt ra có thể để
            # transaction hỏng, không chạy thêm lệnh nào được.
            cr.rollback()
            cr.execute("SELECT pg_advisory_unlock(hashtext(%s), %s)", [TURN_LOCK_KEY, session_id])

    @api.model
    def _play_turn(self, claim_token):
        Session = self.env['hlv.admin.chat.session'].sudo()
        session = Session.from_claim(claim_token)
        if not session:
            return
        reply, error, history_vals = '', None, {}
        try:
            reply, history, key = self._converse(session, claim_token)
            history_vals = {'api_messages': json.dumps(history, ensure_ascii=False), 'api_context_key': key,
                            'api_history_date': fields.Datetime.now()}
        except TurnFailed as failure:
            error = str(failure)
        except Exception as failure:  # noqa: BLE001 — người dùng phải nhận được câu báo lỗi
            _logger.exception("ADMIN_AGENT lượt %s lỗi", claim_token)
            self.env.cr.rollback()
            error = "lỗi hệ thống: %s" % failure

        self.env.invalidate_all()
        session = Session.from_claim(claim_token)
        if not session:
            _logger.info("ADMIN_AGENT bỏ câu trả lời muộn của lượt %s", claim_token)
            return
        # Lượt lỗi: bỏ lịch sử API, lượt sau mở lại từ tin chữ (kèm lời dặn không chạy lại lệnh cũ) —
        # giữ lịch sử dở dang là Claude tưởng lệnh ghi chưa từng chạy.
        session.write(history_vals or {'api_messages': False, 'api_context_key': False})
        session.deliver_reply(reply, error=error)
        self.env.cr.commit()

    def _converse(self, session, claim_token):
        """Trả ``(reply, history, context_key)``. Raise TurnFailed khi không xong."""
        config_record = self.env['hlv.admin.agent.config'].current()
        config = config_record.run_config()
        if session.model:
            config['model'] = session.model
        if not config['api_key']:
            raise TurnFailed("chưa khai Anthropic API key (Cài đặt > Tồn kho > Trợ lý tạo mã hàng)")
        system_text = config_record.system_text()
        key = admin_context_key(config['model'], system_text)
        history = load_history(session.api_messages) if session.api_context_key == key else []
        idle_minutes = ((fields.Datetime.now() - session.api_history_date).total_seconds() / 60
                        if session.api_history_date else 0)
        if history and history_expired(history, session.api_last_prompt_tokens, idle_minutes):
            history = []
        turn = session.api_turn_input()
        try:
            return self._run_steps(session, claim_token, config, system_text, history, turn) + (key,)
        except _StaleHistory:
            _logger.info("ADMIN_AGENT API từ chối lịch sử cuộc %s, mở lại", session.id)
            return self._run_steps(session, claim_token, config, system_text, [], turn) + (key,)

    def _run_steps(self, session, claim_token, config, system_text, history, turn):
        """Vòng gọi API + chạy tool tới khi Claude trả lời xong. Trả ``(reply, messages)``."""
        anthropic = load_anthropic()
        if not anthropic:
            raise TurnFailed("Odoo chưa cài thư viện anthropic")
        client = make_client(anthropic, config['api_key'], timeout=REQUEST_TIMEOUT_SECONDS)
        ProductRunner = self.env['hlv.product.agent.api.runner']
        model = config['model']
        text = turn['prompt'] if history else turn['prompt_cold']
        messages = history + [{'role': 'user', 'content': user_content(text, turn['images'])}]
        params = dict(
            model=model, max_tokens=MAX_TOKENS, system=build_system(system_text), tools=admin_tools(model),
            thinking={'type': 'adaptive'}, output_config={'effort': config['effort']},
            cache_control=CACHE_CONTROL, **request_extras(model),
        )
        started, step_contents, done_writes = time.monotonic(), [], set()
        for step in range(MAX_STEPS):
            if time.monotonic() - started > TURN_DEADLINE_SECONDS:
                raise TurnFailed("Claude chạy quá %s giây" % TURN_DEADLINE_SECONDS)
            response = ProductRunner._request(anthropic, client, params, messages, stale_ok=bool(history) and step == 0)
            ProductRunner._record_usage(session, response)
            if response.stop_reason == 'refusal':
                raise TurnFailed("Claude từ chối xử lý yêu cầu này")
            content = history_content(response.to_dict(mode='json').get('content'))
            messages.append({'role': 'assistant', 'content': content})
            step_contents.append(content)
            if response.stop_reason == 'pause_turn':
                # Tool web chạy dài, máy chủ tạm dừng: gửi lại nguyên văn là chạy tiếp.
                continue
            calls = tool_uses(content)
            if response.stop_reason == 'tool_use' and calls:
                messages.append({'role': 'user', 'content': [
                    tool_result(call['id'], self._dispatch(claim_token, call, config, anthropic, client, done_writes))
                    for call in calls
                ]})
                continue
            if response.stop_reason == 'max_tokens':
                raise TurnFailed("câu trả lời quá dài, bị cắt")
            return turn_reply(step_contents), messages
        raise TurnFailed("Claude gọi tool quá %s lần trong một lượt" % MAX_STEPS)

    def _dispatch(self, claim_token, call, config, anthropic, client, done_writes):
        """Chạy một tool rồi commit ngay. Trả dict kết quả, luôn có 'status'.

        Commit từng tool: thứ đã ghi lên MISA phải nằm trong cuộc chat (ghi chú hệ thống, nhật ký)
        dù bước sau lỗi, và khoá tạo mã (advisory theo transaction) được nhả cho lượt khác.
        """
        name, args = call.get('name') or '', call.get('input') or {}
        self.env.invalidate_all()
        session = self.env['hlv.admin.chat.session'].sudo().from_claim(claim_token)
        if not session:
            return {'status': 'error', 'message': 'Lượt xử lý đã đóng, không chạy tool nữa.'}
        signature = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if signature in done_writes:
            return {'status': 'duplicate', 'message': "Lệnh này ĐÃ chạy thành công trong lượt này — KHÔNG "
                                                      "chạy lại; báo người dùng kết quả lần trước."}
        try:
            if name == DELEGATE_TOOL_NAME:
                result = self.env['hlv.product.agent.delegate'].run_task(
                    session, args.get('nhiem_vu'), config, anthropic, client)
            elif name in CRM_TOOL_NAMES:
                result = self.env['hlv.admin.crm.tools'].run(session, name, args)
            else:
                result = self.env['hlv.product.agent.tools'].sudo().run(_ProductSessionView(session), name, args)
            self.env.cr.commit()
        except Exception as error:  # noqa: BLE001 — Claude phải nhận được kết quả lỗi
            self.env.cr.rollback()
            _logger.exception("ADMIN_AGENT tool %s lỗi", name)
            result = {'status': 'error', 'message': str(error)[:300]}
        if name in WRITE_TOOLS and result.get('status') == 'success':
            done_writes.add(signature)
        return result


def _start_thread(dbname, session_id):
    """Mở luồng chạy một cuộc. Trả thread (đã start).

    Không daemon: worker tự tắt (đủ số request, quá RAM mềm) sẽ đợi lượt đang dở xong thay vì cắt
    ngang giữa chừng một lệnh tạo báo giá.
    """
    thread = threading.Thread(target=_serve_in_thread, args=(dbname, session_id),
                              name='hlv_admin_agent', daemon=False)
    thread.start()
    return thread


def _serve_in_thread(dbname, session_id):
    """Thân luồng: cursor riêng (cursor của request / cron không dùng chung luồng được)."""
    threading.current_thread().dbname = dbname
    try:
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['hlv.admin.agent.runner']._serve(session_id)
    except Exception:  # noqa: BLE001 — lỗi một luồng không được giết worker
        _logger.exception("ADMIN_AGENT luồng xử lý chết")
