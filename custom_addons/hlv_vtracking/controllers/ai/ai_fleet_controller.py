"""API cho AI — tình hình đội xe."""

from odoo import http

from ...services.ai import fleet_service
from ..api_common import ROUTE_DEFAULTS, api_endpoint


class AiFleetController(http.Controller):

    @http.route('/api/v1/ai/fleet', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def fleet(self, ctx, **params):
        """Mọi xe: vị trí gần nhất, trạng thái, kế hoạch trong ngày, buổi còn trống.

        Tham số: ``date`` (YYYY-MM-DD, mặc định hôm nay) — ngày muốn xem kế hoạch. Vị trí
        xe luôn là vị trí hiện tại, không phụ thuộc ``date``.
        """
        day = ctx.parse_date(params.get('date'))
        return fleet_service.fleet_status(ctx.env, ctx.company, day)
