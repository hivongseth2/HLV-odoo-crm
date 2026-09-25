# -*- coding: utf-8 -*-
"""API cho agent chạy Claude trên máy văn phòng.

Agent chỉ gọi RA, Odoo không bao giờ gọi vào máy đó — máy văn phòng không mở cổng
nào. Đổi lại tin của sale có độ trễ đúng bằng chu kỳ poll.

Các route ở đây auth='public' vì agent không phải một user Odoo. Thứ duy nhất chặn
người lạ là token agent, nên mọi route đều phải qua _agent_from() trước tiên. Tool
MISA còn phải kèm claim_token của một lượt đang mở: token rò ra ngoài thì vẫn phải
đoán thêm một mã lượt sống vài phút mới gọi được tool.
"""
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_JOBS_PER_POLL = 4


def _agent_from(params):
    return request.env['hlv.product.agent'].sudo()._authenticate(params.get('token'))


class ProductAgentApi(http.Controller):

    @http.route('/product_agent/agent/poll', type='json', auth='public', csrf=False, methods=['POST'])
    def poll(self, **kw):
        """Agent hỏi có tin nào cần trả lời không.

        Nhận: token, agent_version, max_jobs (số lượt agent còn chạy thêm được).
        Trả: ``{'ok': True, 'jobs': [...], 'prompt_version': ...}`` — job xem
        hlv.product.chat.session._claim; prompt_version đổi thì agent gọi /prompt.
        """
        agent = _agent_from(kw)
        if not agent:
            return {'ok': False, 'error': 'auth'}
        agent.touch(kw.get('agent_version'))

        Session = request.env['hlv.product.chat.session'].sudo()
        # Bám nhịp poll để dọn lượt treo — nhanh hơn cron mà không tốn thêm request.
        Session.release_stale()
        # Agent bận hết thì gửi 0: vẫn poll để báo còn sống, nhưng không nhận thêm việc.
        try:
            max_jobs = min(int(kw.get('max_jobs', 1)), MAX_JOBS_PER_POLL)
        except (TypeError, ValueError):
            max_jobs = 1
        jobs = Session.claim_jobs(max_jobs) if max_jobs > 0 else []
        _text, version = request.env['hlv.product.agent.prompt'].sudo().build_prompt()
        return {'ok': True, 'jobs': jobs, 'prompt_version': version}

    @http.route('/product_agent/agent/prompt', type='json', auth='public', csrf=False, methods=['POST'])
    def prompt(self, **kw):
        """System prompt hoàn chỉnh (sửa trên Odoo: Trợ lý tạo mã hàng > Prompt trợ lý)."""
        if not _agent_from(kw):
            return {'ok': False, 'error': 'auth'}
        text, version = request.env['hlv.product.agent.prompt'].sudo().build_prompt()
        return {'ok': True, 'content': text, 'version': version}

    @http.route('/product_agent/agent/tool', type='json', auth='public', csrf=False, methods=['POST'])
    def tool(self, **kw):
        """MCP server trên máy agent chuyển một lệnh gọi tool MISA của Claude lên đây.

        Luôn trả dict có 'status' để Claude đọc được, kể cả khi bị từ chối.
        """
        if not _agent_from(kw):
            return {'status': 'error', 'message': 'Agent không hợp lệ.'}
        session = request.env['hlv.product.chat.session'].sudo().from_claim(kw.get('claim_token'))
        if not session:
            return {'status': 'error', 'message': 'Lượt xử lý đã đóng, không chạy tool nữa.'}
        return request.env['hlv.product.agent.tools'].sudo().run(
            session, kw.get('name') or '', kw.get('args') or {},
        )

    @http.route('/product_agent/agent/reply', type='json', auth='public', csrf=False, methods=['POST'])
    def reply(self, **kw):
        """Agent gửi câu trả lời của Claude (hoặc lỗi) cho một lượt."""
        if not _agent_from(kw):
            return {'ok': False, 'error': 'auth'}
        session = request.env['hlv.product.chat.session'].sudo().from_claim(kw.get('claim_token'))
        if not session:
            # Lượt đã bị thả vì quá hạn: sale đã được báo gửi lại, trả lời muộn bỏ đi.
            _logger.info("PRODUCT_AGENT bỏ câu trả lời muộn của lượt %s", kw.get('claim_token'))
            return {'ok': False, 'error': 'stale'}
        session.deliver_reply(
            kw.get('reply') or '',
            claude_session_id=kw.get('claude_session_id') or None,
            error=kw.get('error') or None,
        )
        return {'ok': True}

    @http.route('/product_agent/agent/attachment', type='http', auth='public', csrf=False, methods=['POST'])
    def attachment(self, **kw):
        """Agent tải một ảnh sale gửi, để Claude đọc bằng Read.

        Chỉ trả ảnh thuộc tin của đúng lượt đang mở, không phải attachment bất kỳ.
        """
        form = request.httprequest.form
        if not _agent_from(form):
            return request.make_response('auth', status=403)
        session = request.env['hlv.product.chat.session'].sudo().from_claim(form.get('claim_token'))
        try:
            attachment_id = int(form.get('attachment_id') or 0)
        except (TypeError, ValueError):
            attachment_id = 0
        attachment = session.message_ids.attachment_ids.filtered(lambda a: a.id == attachment_id)
        if not session or not attachment:
            return request.make_response('not found', status=404)
        return request.make_response(
            attachment.raw or b'',
            headers=[('Content-Type', attachment.mimetype or 'application/octet-stream')],
        )
