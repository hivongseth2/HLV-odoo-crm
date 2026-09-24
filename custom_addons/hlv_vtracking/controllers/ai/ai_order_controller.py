"""API cho AI — đơn bán và phiếu kho: cái gì còn phải giao, hàng về chưa, kho soạn tới đâu,
ai dặn gì.
"""

from odoo import http

from ...services.ai import chatter_service, order_service, picking_service
from ..api_common import ROUTE_DEFAULTS, ApiError, api_endpoint


class AiOrderController(http.Controller):

    # ------------------------------------------------------------------
    # Đơn bán
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/orders/pending', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def pending_orders(self, ctx, **params):
        """Đơn bán CÒN PHẢI GIAO (đã xác nhận, chưa giao đủ), hẹn giao sớm nhất trước.

        Tham số: ``warehouse_id``, ``search`` (số đơn / tên khách), ``commitment_from``,
        ``commitment_to`` (YYYY-MM-DD), ``stage`` (mã giai đoạn kho), ``unplanned_only=1``,
        ``limit`` (mặc định 50, tối đa 200), ``offset``.
        """
        for name in ('commitment_from', 'commitment_to'):
            ctx.parse_date(params.get(name), default_today=False)
        limit = ctx.parse_int(params.get('limit'), 'limit', order_service.DEFAULT_LIMIT,
                              minimum=1, maximum=order_service.MAX_LIMIT)
        offset = ctx.parse_int(params.get('offset'), 'offset', 0, minimum=0)
        return order_service.pending_orders(ctx.env, ctx.company, params, limit, offset)

    @http.route('/api/v1/ai/orders/<int:order_id>', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def order_detail(self, ctx, order_id, **_params):
        """Một đơn đầy đủ: dòng hàng, từng phiếu kho, từng đơn mua, khối lượng, hội thoại."""
        order = ctx.browse_or_404('sale.order', order_id, 'đơn bán')
        return order_service.order_detail(order)

    @http.route('/api/v1/ai/orders/by-name', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def order_by_name(self, ctx, **params):
        """Như trên nhưng tra theo SỐ ĐƠN (``?name=DH125524949235898``).

        Người điều phối và chatter nhắc tới đơn bằng số đơn, không bằng id — AI đọc được
        một số đơn trong lời dặn thì phải tra ngay được.
        """
        name = (params.get('name') or '').strip()
        if not name:
            raise ApiError('BAD_PARAM', 'Thiếu tham số "name".')
        order = ctx.env['sale.order'].search([
            ('name', '=', name), ('company_id', '=', ctx.company.id),
        ], limit=1)
        if not order:
            raise ApiError('NOT_FOUND', 'Không có đơn bán số "%s".' % name, 404)
        return order_service.order_detail(order)

    @http.route('/api/v1/ai/orders/<int:order_id>/chatter',
                methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def order_chatter(self, ctx, order_id, **params):
        """Hội thoại của một đơn, mới nhất trước.

        Tham số: ``limit`` (mặc định 30, tối đa 100), ``include_system=1`` để lấy cả tin hệ
        thống kèm lịch sử đổi giá trị field.
        """
        order = ctx.browse_or_404('sale.order', order_id, 'đơn bán')
        limit = ctx.parse_int(params.get('limit'), 'limit', chatter_service.DEFAULT_LIMIT,
                              minimum=1, maximum=chatter_service.MAX_LIMIT)
        include_system = params.get('include_system') in ('1', 'true', 'True')
        messages = chatter_service.record_messages(order, limit, include_system)
        return {'order_id': order.id, 'order': order.name, 'count': len(messages), 'messages': messages}

    # ------------------------------------------------------------------
    # Phiếu kho
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/pickings/ready', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def ready_pickings(self, ctx, **params):
        """Phiếu XUẤT xếp lên xe được NGAY (Sẵn sàng, chưa xếp xe, đơn chưa đóng).

        Tham số: ``warehouse_id``, ``search``, ``limit`` (mặc định 100, tối đa 300), ``offset``.
        """
        limit = ctx.parse_int(params.get('limit'), 'limit', picking_service.DEFAULT_LIMIT,
                              minimum=1, maximum=picking_service.MAX_LIMIT)
        offset = ctx.parse_int(params.get('offset'), 'offset', 0, minimum=0)
        return picking_service.ready_pickings(ctx.env, ctx.company, params, limit, offset)

    @http.route('/api/v1/ai/pickings/<int:picking_id>', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def picking_detail(self, ctx, picking_id, **_params):
        """Một phiếu kho đầy đủ: từng dòng hàng, kiện đã đóng, lời dặn trên phiếu."""
        picking = ctx.browse_or_404('stock.picking', picking_id, 'phiếu kho')
        return picking_service.picking_detail(picking)
