"""API cho AI — bối cảnh chung, tra toạ độ, và thử phương án.

Controller chỉ đọc tham số rồi gọi service; mọi luật nằm ở ``services/ai``.
"""

from odoo import http

from ...services.ai import context_service, plan_service
from ..api_common import ROUTE_DEFAULTS, ApiError, api_endpoint

# Trần số điểm của một phương án thử. Một xe một buổi hiếm khi quá 20 điểm; có trần để một
# request lỗi không bắt máy chủ tra vài nghìn địa chỉ.
MAX_WHAT_IF_STOPS = 60


class AiContextController(http.Controller):

    @http.route('/api/v1/ai/context', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def context(self, ctx, **_params):
        """Kho, xe, buổi, định mức tính đường và các luật nghiệp vụ. GỌI ĐẦU TIÊN."""
        return context_service.build_context(ctx.env, ctx.company)

    @http.route('/api/v1/ai/estimate', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def estimate(self, ctx, **_params):
        """Ước lượng km/thời gian của một lộ trình GIẢ ĐỊNH. Không ghi gì vào hệ thống.

        Body: ``{"start_place_id": 3, "stops": [{"picking_id": 1}, {"sale_order_id": 2},
        {"latitude": 10.7, "longitude": 106.9}, {"address": "..."}]}``
        """
        body = ctx.json_body()
        stops = body.get('stops')
        if not isinstance(stops, list) or not stops:
            raise ApiError('BAD_PARAM', '"stops" phải là một mảng không rỗng.')
        if len(stops) > MAX_WHAT_IF_STOPS:
            raise ApiError('BAD_PARAM', 'Tối đa %s điểm cho một phương án.' % MAX_WHAT_IF_STOPS)
        if not all(isinstance(stop, dict) for stop in stops):
            raise ApiError('BAD_PARAM', 'Mỗi phần tử của "stops" phải là một object.')

        start_place = None
        if body.get('start_place_id'):
            start_place = ctx.browse_or_404(
                'hlv.vtracking.place', body['start_place_id'], 'địa điểm xuất phát',
            )
        return plan_service.what_if(ctx.env, ctx.company, start_place, stops)

    @http.route('/api/v1/ai/geocode', methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint(write=True)
    def geocode(self, ctx, **_params):
        """Tra toạ độ một địa chỉ: tìm trong kho toạ độ trước, không có mới gọi geocoder.

        Đòi quyền ghi vì lượt tra mới TỐN TIỀN (Google tính theo lượt) và ghi một bản ghi
        vào kho toạ độ. Body: ``{"address": "..."}``.
        """
        address = (ctx.json_body().get('address') or '').strip()
        if not address:
            raise ApiError('BAD_PARAM', 'Thiếu "address".')
        record = ctx.env['hlv.vtracking.address'].resolve(address)
        if not record:
            raise ApiError('BAD_PARAM', 'Địa chỉ không rút được khoá so khớp (quá ngắn hoặc chỉ có ký hiệu).')
        usable = record.has_coords and not record.outside_vietnam
        return {
            'address_id': record.id,
            'raw_address': record.raw_address,
            'normalized_address': record.normalized_address,
            'geo_state': record.geo_state,
            'latitude': record.latitude if usable else None,
            'longitude': record.longitude if usable else None,
            'from_cache': bool(record.hit_count),
        }
