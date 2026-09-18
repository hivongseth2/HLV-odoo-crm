"""API cho AI — đọc và sửa kế hoạch giao hàng.

Endpoint GHI đòi khoá API bật "Cho phép ghi" (``api_endpoint(write=True)``). Mọi thao tác
ghi để lại dấu vết trên chatter của kế hoạch, ghi tên khoá đã làm.
"""

from datetime import timedelta

from odoo import http

from ...services import plan_payload
from ...services.ai import plan_service
from ..api_common import ROUTE_DEFAULTS, ApiError, api_endpoint

# Khoảng ngày tối đa của một lần liệt kê. Lập kế hoạch giao hàng nhìn vài ngày tới, không
# nhìn cả quý; có trần để một tham số gõ nhầm không kéo về cả lịch sử.
MAX_RANGE_DAYS = 31


class AiPlanController(http.Controller):

    # ------------------------------------------------------------------
    # Đọc
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/plans', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def list_plans(self, ctx, **params):
        """Các kế hoạch trong khoảng ngày (tóm tắt, không kèm từng điểm).

        Tham số: ``date`` (một ngày) HOẶC ``date_from`` + ``date_to``; ``vehicle_id``;
        ``include_cancelled=1``. Không truyền gì thì lấy hôm nay.
        """
        date_from = ctx.parse_date(params.get('date_from') or params.get('date'))
        date_to = ctx.parse_date(params.get('date_to'), default_today=False) or date_from
        if date_to < date_from:
            raise ApiError('BAD_PARAM', '"date_to" phải từ "date_from" trở đi.')
        if (date_to - date_from) > timedelta(days=MAX_RANGE_DAYS):
            raise ApiError('BAD_PARAM', 'Khoảng ngày tối đa %s ngày.' % MAX_RANGE_DAYS)
        return plan_service.list_plans(
            ctx.env, ctx.company, date_from, date_to,
            vehicle_id=ctx.parse_int(params.get('vehicle_id'), 'vehicle_id'),
            include_cancelled=params.get('include_cancelled') in ('1', 'true', 'True'),
        )

    @http.route('/api/v1/ai/plans/<int:plan_id>', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def plan_detail(self, ctx, plan_id, **_params):
        """Một kế hoạch đầy đủ: từng điểm theo thứ tự ghé, km từng chặng, giờ tới cộng dồn."""
        return plan_service.plan_detail(self._plan(ctx, plan_id))

    @http.route('/api/v1/ai/plans/<int:plan_id>/vs-actual',
                methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def plan_vs_actual(self, ctx, plan_id, **_params):
        """Đối chiếu kế hoạch với thực tế: từng điểm dự kiến mấy giờ, thật sự mấy giờ.

        Đây là nguồn để sửa định mức. ``summary.mean_variance`` giữ dấu — luôn dương nghĩa
        là định mức của cụm đó quá lạc quan, không phải hôm đó xui.
        """
        return plan_service.plan_vs_actual(self._plan(ctx, plan_id))

    @http.route('/api/v1/ai/plans/<int:plan_id>/refresh-actual',
                methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def plan_refresh_actual(self, ctx, plan_id, **_params):
        """Đọc lại số thực tế ngay, không chờ tác vụ nền mỗi giờ."""
        return plan_service.refresh_actual(self._plan(ctx, plan_id), ctx.api_key.name)

    # ------------------------------------------------------------------
    # Ghi
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/plans', methods=['POST'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def create_plan(self, ctx, **_params):
        """Tạo kế hoạch cho (xe, ngày, buổi). Đã có thì trả lại cái có sẵn (``created: false``).

        Body: ``{"vehicle_id": 5, "date": "2026-09-18", "session": "morning",
        "start_place_id": 3}`` — ``session`` ∈ morning / afternoon / full_day.
        """
        body = ctx.json_body()
        session = body.get('session') or 'morning'
        if session not in plan_payload.SESSION_LABELS:
            raise ApiError('BAD_PARAM', '"session" phải là một trong: %s.' % ', '.join(plan_payload.SESSION_LABELS))
        if not body.get('vehicle_id'):
            raise ApiError('BAD_PARAM', 'Thiếu "vehicle_id".')
        vehicle = ctx.env['fleet.vehicle'].browse(int(body['vehicle_id'])).exists()
        if not vehicle or (vehicle.company_id and vehicle.company_id != ctx.company):
            raise ApiError('NOT_FOUND', 'Không có xe id %s.' % body['vehicle_id'], 404)
        start_place = None
        if body.get('start_place_id'):
            start_place = ctx.browse_or_404('hlv.vtracking.place', body['start_place_id'], 'địa điểm xuất phát')

        plan, created = plan_service.create_plan(
            ctx.env, vehicle, ctx.parse_date(body.get('date')), session, start_place, ctx.api_key.name,
        )
        detail = plan_service.plan_detail(plan)
        detail['created'] = created
        return detail

    @http.route('/api/v1/ai/plans/<int:plan_id>/documents', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def add_documents(self, ctx, plan_id, **_params):
        """Xếp phiếu giao và/hoặc đơn bán vào kế hoạch (nối vào cuối thứ tự ghé).

        Body: ``{"picking_ids": [..], "sale_order_ids": [..]}``. Chứng từ không xếp được
        (đã có kế hoạch, đơn đã đóng) KHÔNG làm cả lời gọi thất bại: chúng nằm trong
        ``rejected`` kèm lý do, phần còn lại vẫn được xếp.
        """
        plan = self._plan(ctx, plan_id)
        body = ctx.json_body()
        picking_ids = ctx.parse_id_list(body.get('picking_ids'), 'picking_ids')
        order_ids = ctx.parse_id_list(body.get('sale_order_ids'), 'sale_order_ids')
        if not picking_ids and not order_ids:
            raise ApiError('BAD_PARAM', 'Cần "picking_ids" hoặc "sale_order_ids".')

        company_domain = [('company_id', '=', ctx.company.id)]
        pickings = ctx.env['stock.picking'].search([('id', 'in', picking_ids)] + company_domain)
        orders = ctx.env['sale.order'].search([('id', 'in', order_ids)] + company_domain)
        result = plan_service.add_documents(plan, pickings, orders, ctx.api_key.name)
        result['not_found'] = {
            'picking_ids': sorted(set(picking_ids) - set(pickings.ids)),
            'sale_order_ids': sorted(set(order_ids) - set(orders.ids)),
        }
        result['plan'] = plan_service.plan_detail(plan)
        return result

    @http.route('/api/v1/ai/plans/<int:plan_id>/remove-lines', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def remove_lines(self, ctx, plan_id, **_params):
        """Gỡ dòng khỏi kế hoạch. Body: ``{"line_ids": [..]}`` (id dòng, không phải id phiếu)."""
        plan = self._plan(ctx, plan_id)
        line_ids = ctx.parse_id_list(ctx.json_body().get('line_ids'), 'line_ids')
        if not line_ids:
            raise ApiError('BAD_PARAM', 'Thiếu "line_ids".')
        result = plan_service.remove_lines(plan, line_ids, ctx.api_key.name)
        result['plan'] = plan_service.plan_detail(plan)
        return result

    @http.route('/api/v1/ai/plans/<int:plan_id>/resequence', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def resequence(self, ctx, plan_id, **_params):
        """Đặt lại thứ tự ghé. Body: ``{"line_ids": [..theo thứ tự mong muốn..]}`` hoặc
        ``{"strategy": "nearest"}`` để hệ thống tự sắp theo điểm gần nhất."""
        plan = self._plan(ctx, plan_id)
        body = ctx.json_body()
        if body.get('strategy') == 'nearest':
            return plan_service.optimize_order(plan, ctx.api_key.name)
        line_ids = ctx.parse_id_list(body.get('line_ids'), 'line_ids')
        if not line_ids:
            raise ApiError('BAD_PARAM', 'Cần "line_ids" hoặc "strategy": "nearest".')
        return plan_service.resequence(plan, line_ids, ctx.api_key.name)

    @http.route('/api/v1/ai/plans/<int:plan_id>/state', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def change_state(self, ctx, plan_id, **_params):
        """Chuyển trạng thái. Body: ``{"action": "confirm"}`` — confirm / back_to_draft /
        cancel / done."""
        action = (ctx.json_body().get('action') or '').strip()
        return plan_service.change_state(self._plan(ctx, plan_id), action, ctx.api_key.name)

    @staticmethod
    def _plan(ctx, plan_id):
        return ctx.browse_or_404('hlv.vtracking.plan', plan_id, 'kế hoạch')
