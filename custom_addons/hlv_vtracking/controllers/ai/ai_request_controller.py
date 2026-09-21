"""API cho worker AI: lấy phiếu yêu cầu của nhân viên, nhận việc, trả lời.

Quy trình bắt buộc: ``claim`` trước, ``answer`` sau. Nhận việc là cách duy nhất để hai máy
chạy worker không trả lời trùng một phiếu.
"""

from odoo import http
from odoo.http import request

from ...services.ai import request_service
from ..api_common import ROUTE_DEFAULTS, api_endpoint

READ = dict(methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
WRITE = dict(methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)


class AiRequestController(http.Controller):

    @http.route('/api/v1/ai/requests', **READ)
    @api_endpoint()
    def requests(self, ctx, **_params):
        """Lọc: ``state`` (mặc định ``pending``, ``all`` để xem hết), ``limit``, ``offset``."""
        params = dict(request.httprequest.args)
        params['limit'] = ctx.parse_int(params.get('limit'), 'limit', default=20, minimum=1,
                                        maximum=100)
        params['offset'] = ctx.parse_int(params.get('offset'), 'offset', default=0, minimum=0)
        return request_service.list_requests(ctx.env, ctx.company, params)

    @http.route('/api/v1/ai/requests/<int:request_id>', **READ)
    @api_endpoint()
    def request_detail(self, ctx, request_id, **_params):
        return request_service.request_block(self._request(ctx, request_id))

    @http.route('/api/v1/ai/requests/<int:request_id>/claim', **WRITE)
    @api_endpoint(write=True)
    def claim(self, ctx, request_id, **_params):
        """``{"worker": "laptop-Luan"}``. ``claimed: false`` = máy khác đã nhận, bỏ qua."""
        return request_service.claim_request(self._request(ctx, request_id), ctx.json_body())

    @http.route('/api/v1/ai/requests/<int:request_id>/answer', **WRITE)
    @api_endpoint(write=True)
    def answer(self, ctx, request_id, **_params):
        """``{"verdict", "answer", "applied"}`` — xem mục 25 của tài liệu."""
        return request_service.answer_request(
            self._request(ctx, request_id), ctx.json_body(), ctx.api_key.name)

    @http.route('/api/v1/ai/requests/<int:request_id>/fail', **WRITE)
    @api_endpoint(write=True)
    def fail(self, ctx, request_id, **_params):
        """``{"error": "..."}`` — không xử lý được, để người điều phối làm tay."""
        return request_service.fail_request(self._request(ctx, request_id), ctx.json_body())

    @staticmethod
    def _request(ctx, request_id):
        return ctx.browse_or_404('hlv.vtracking.ai.request', request_id, 'yêu cầu')
