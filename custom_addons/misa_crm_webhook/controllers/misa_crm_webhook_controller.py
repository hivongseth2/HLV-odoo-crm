# -*- coding: utf-8 -*-
import json
import logging
import hmac
import hashlib
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class MisaCrmWebhookController(http.Controller):
    """
    Nhận webhook POST từ MISA AMIS CRM.

    Đăng ký URL này trong AMIS CRM:
        Thiết lập → Kết nối → API → Địa chỉ Webhook

    Endpoint: POST /misa/crm/webhook
    Headers CRM gửi kèm (tuỳ phiên bản):
        X-App-Id: <AppID>
        X-Signature: <HMAC-SHA256 signature>
        Content-Type: application/json
    """

    WEBHOOK_ROUTE = '/misa/crm/webhook'

    @http.route(
        WEBHOOK_ROUTE,
        type='http',        # Dùng type='http' để đọc raw body
        auth='none',        # Không yêu cầu đăng nhập Odoo
        methods=['POST'],
        csrf=False,         # Bắt buộc False cho external webhook
        save_session=False,
    )
    def receive_webhook(self, **kwargs):
        """
        Xử lý webhook từ MISA AMIS CRM.
        Luồng:
          1. Đọc raw body + headers
          2. Xác thực AppID / chữ ký (nếu bật)
          3. Parse JSON
          4. Tạo log record (state=received)
          5. Gọi processor để xử lý nghiệp vụ
          6. Trả về HTTP 200 JSON
        """
        try:
            raw_body = request.httprequest.get_data(as_text=True)
            headers  = request.httprequest.headers
        except Exception as e:
            _logger.error('MISA CRM webhook: failed to read request: %s', e)
            return self._error_response(400, 'Cannot read request body')

        # ── 1. Xác thực chữ ký ────────────────────────────────────────────────
        env = request.env(user=request.env.ref('base.user_root').id)
        params = env['ir.config_parameter'].sudo()

        verify = params.get_param('misa_crm.verify_signature', 'False') == 'True'
        if verify:
            ok, msg = self._verify_request(raw_body, headers, params)
            if not ok:
                _logger.warning('MISA CRM webhook auth failed: %s', msg)
                return self._error_response(401, msg)

        # ── 2. Parse JSON ──────────────────────────────────────────────────────
        try:
            payload = json.loads(raw_body or '{}')
        except json.JSONDecodeError as e:
            _logger.warning('MISA CRM webhook: invalid JSON: %s', e)
            # Vẫn ghi log để debug
            payload = {}

        # ── 3. Xác định event type ─────────────────────────────────────────────
        event_type = (
            payload.get('event_type')
            or payload.get('event')
            or payload.get('EventType')
            or headers.get('X-Event-Type', '')
        ).lower().strip()

        crm_object_id = str(
            payload.get('id')
            or (payload.get('data') or {}).get('customer_id')
            or (payload.get('data') or {}).get('order_id')
            or ''
        )
        app_id_recv = (
            payload.get('app_id')
            or payload.get('AppId')
            or headers.get('X-App-Id', '')
        )

        _logger.info(
            'MISA CRM webhook received: event=%s app_id=%s crm_obj=%s',
            event_type, app_id_recv, crm_object_id
        )

        # ── 4. Ghi log record ──────────────────────────────────────────────────
        try:
            log = env['misa.crm.webhook.log'].sudo().create({
                'event_type':    event_type,
                'app_id':        app_id_recv,
                'crm_object_id': crm_object_id,
                'raw_payload':   raw_body,
                'http_method':   request.httprequest.method,
                'state':         'received',
            })
            env.cr.commit()   # Commit log ngay, tránh mất nếu processor lỗi
        except Exception as e:
            _logger.error('MISA CRM webhook: failed to create log: %s', e)
            return self._error_response(500, 'Internal error creating log')

        # ── 5. Xử lý nghiệp vụ ────────────────────────────────────────────────
        try:
            env['misa.crm.processor'].sudo().process_log(log)
            env.cr.commit()
        except Exception as e:
            _logger.exception('MISA CRM webhook: processor error: %s', e)
            # Không return error – CRM cần nhận 200 để không retry liên tục.
            # State đã được set error trong processor.

        # ── 6. Trả về 200 ─────────────────────────────────────────────────────
        return self._ok_response(log.id, event_type)

    # ─── HEAD / GET để MISA CRM verify endpoint còn sống ─────────────────────

    @http.route(
        WEBHOOK_ROUTE,
        type='http',
        auth='none',
        methods=['GET', 'HEAD'],
        csrf=False,
        save_session=False,
    )
    def verify_endpoint(self, **kwargs):
        """AMIS CRM gọi GET/HEAD để kiểm tra endpoint trước khi lưu cấu hình."""
        return Response(
            json.dumps({'status': 'ok', 'service': 'MISA CRM Webhook – Odoo 18'}),
            status=200,
            mimetype='application/json',
        )

    # ─── Private helpers ──────────────────────────────────────────────────────

    def _verify_request(self, raw_body, headers, params):
        """
        Xác thực request:
        - AppID khớp với cấu hình
        - Chữ ký HMAC-SHA256 hợp lệ (nếu có)
        """
        expected_app_id = params.get_param('misa_crm.app_id', '')
        secret_key      = params.get_param('misa_crm.secret', '')

        # Đọc app_id từ header hoặc parse nhanh JSON
        recv_app_id = headers.get('X-App-Id', '')
        if not recv_app_id:
            try:
                recv_app_id = json.loads(raw_body or '{}').get('app_id', '')
            except Exception:
                recv_app_id = ''

        if expected_app_id and recv_app_id and recv_app_id != expected_app_id:
            return False, f'AppID không khớp: nhận {recv_app_id}'

        # Kiểm tra chữ ký HMAC nếu CRM gửi kèm
        signature = headers.get('X-Signature') or headers.get('X-Hmac-Signature')
        if signature and secret_key:
            expected_sig = hmac.new(
                secret_key.encode('utf-8'),
                raw_body.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_sig, signature.lower()):
                return False, 'Chữ ký HMAC không hợp lệ'

        return True, 'OK'

    @staticmethod
    def _ok_response(log_id, event_type):
        body = json.dumps({
            'success':    True,
            'log_id':     log_id,
            'event_type': event_type,
            'message':    'Webhook received',
        })
        return Response(body, status=200, mimetype='application/json')

    @staticmethod
    def _error_response(code, message):
        body = json.dumps({'success': False, 'message': message})
        return Response(body, status=code, mimetype='application/json')
