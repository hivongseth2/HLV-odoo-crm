"""API cho AI — dữ liệu VỊ TRÍ: kho toạ độ (địa chỉ) và địa điểm + thói quen khách.

Controller chỉ đọc tham số rồi gọi service; luật nằm ở ``services/ai``, ``models`` và
``tools/vtracking_dedup``. Gộp trùng luôn là hai bước: ``.../duplicates`` để XEM đề xuất,
``.../merge`` để gộp đúng các id đã chọn — không có lối "tự gộp hết".
"""

from odoo import http
from odoo.http import request

from ...services.ai import address_service, place_service
from ..api_common import ROUTE_DEFAULTS, ApiError, api_endpoint

READ = dict(methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
WRITE = dict(methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)
# Đường dẫn đã có rule GET kèm OPTIONS thì rule POST KHÔNG khai lại OPTIONS — hai rule cùng
# nhận OPTIONS thì Werkzeug chọn mập mờ. Giống cách POST /plans đang khai.
WRITE_SAME_PATH = dict(methods=['POST'], **ROUTE_DEFAULTS)


def _query(ctx):
    """Tham số query string + phân trang đã kiểm."""
    params = dict(request.httprequest.args)
    params['limit'] = ctx.parse_int(params.get('limit'), 'limit', default=50, minimum=1, maximum=200)
    params['offset'] = ctx.parse_int(params.get('offset'), 'offset', default=0, minimum=0)
    return params


def _merge_ids(ctx, body):
    if not body.get('keep_id'):
        raise ApiError('BAD_PARAM', 'Thiếu "keep_id".')
    merge_ids = ctx.parse_id_list(body.get('merge_ids'), 'merge_ids')
    if not merge_ids:
        raise ApiError('BAD_PARAM', 'Thiếu "merge_ids".')
    return int(body['keep_id']), merge_ids


class AiLocationController(http.Controller):

    # ------------------------------------------------------------------
    # Kho toạ độ
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/addresses', **READ)
    @api_endpoint()
    def addresses(self, ctx, **_params):
        """Lọc: search, geo_state, has_coords=0|1, outside_vietnam=1, include_aliases=1."""
        return address_service.list_addresses(ctx.env, ctx.company, _query(ctx))

    @http.route('/api/v1/ai/addresses/duplicates', **READ)
    @api_endpoint()
    def address_duplicates(self, ctx, **_params):
        return address_service.address_duplicates(ctx.env, ctx.company)

    @http.route('/api/v1/ai/addresses/<int:address_id>', **READ)
    @api_endpoint()
    def address(self, ctx, address_id, **_params):
        return address_service.address_block(
            ctx.browse_or_404('hlv.vtracking.address', address_id, 'địa chỉ'))

    @http.route('/api/v1/ai/addresses/<int:address_id>', **WRITE_SAME_PATH)
    @api_endpoint(write=True)
    def update_address(self, ctx, address_id, **_params):
        """``{"coords": "10.7, 106.9"}`` (nhập tay) hoặc ``{"confirm": true}`` (duyệt)."""
        record = ctx.browse_or_404('hlv.vtracking.address', address_id, 'địa chỉ')
        return address_service.update_address(record, ctx.json_body())

    @http.route('/api/v1/ai/addresses/<int:address_id>/geocode', **WRITE)
    @api_endpoint(write=True)
    def geocode_address(self, ctx, address_id, **_params):
        """Tra lại toạ độ — CÓ THỂ TỐN TIỀN (Google tính theo lượt)."""
        record = ctx.browse_or_404('hlv.vtracking.address', address_id, 'địa chỉ')
        return address_service.geocode_address(record)

    @http.route('/api/v1/ai/addresses/merge', **WRITE)
    @api_endpoint(write=True)
    def merge_addresses(self, ctx, **_params):
        """``{"keep_id": 5, "merge_ids": [7, 9]}`` — bản gộp thành bí danh của bản giữ."""
        keep_id, merge_ids = _merge_ids(ctx, ctx.json_body())
        return address_service.merge_addresses(ctx.env, ctx.company, keep_id, merge_ids)

    # ------------------------------------------------------------------
    # Địa điểm
    # ------------------------------------------------------------------
    @http.route('/api/v1/ai/places', **READ)
    @api_endpoint()
    def places(self, ctx, **_params):
        """Lọc: search, type_code, zone_id, geo_state, has_coords=0|1, no_zone=1,
        no_profile=1, no_partner=1, include_archived=1."""
        return place_service.list_places(ctx.env, ctx.company, _query(ctx))

    @http.route('/api/v1/ai/places', **WRITE_SAME_PATH)
    @api_endpoint(write=True)
    def create_place(self, ctx, **_params):
        return place_service.create_place(ctx.env, ctx.company, ctx.json_body(), ctx.api_key.name)

    @http.route('/api/v1/ai/places/duplicates', **READ)
    @api_endpoint()
    def place_duplicates(self, ctx, **_params):
        return place_service.place_duplicates(ctx.env, ctx.company)

    @http.route('/api/v1/ai/places/merge', **WRITE)
    @api_endpoint(write=True)
    def merge_places(self, ctx, **_params):
        """``{"keep_id": 5, "merge_ids": [7]}`` — bản gộp được lưu trữ, không xoá."""
        keep_id, merge_ids = _merge_ids(ctx, ctx.json_body())
        return place_service.merge_places(ctx.env, ctx.company, keep_id, merge_ids, ctx.api_key.name)

    @http.route('/api/v1/ai/places/<int:place_id>', **READ)
    @api_endpoint()
    def place(self, ctx, place_id, **_params):
        return place_service.place_block(self._place(ctx, place_id))

    @http.route('/api/v1/ai/places/<int:place_id>', **WRITE_SAME_PATH)
    @api_endpoint(write=True)
    def update_place(self, ctx, place_id, **_params):
        return place_service.update_place(self._place(ctx, place_id), ctx.json_body(), ctx.api_key.name)

    @http.route('/api/v1/ai/places/<int:place_id>/geocode', **WRITE)
    @api_endpoint(write=True)
    def geocode_place(self, ctx, place_id, **_params):
        """Tra lại toạ độ — CÓ THỂ TỐN TIỀN."""
        return place_service.geocode_place(self._place(ctx, place_id), ctx.api_key.name)

    @http.route('/api/v1/ai/places/<int:place_id>/confirm-geo', **WRITE)
    @api_endpoint(write=True)
    def confirm_place_geo(self, ctx, place_id, **_params):
        return place_service.confirm_place_geo(self._place(ctx, place_id), ctx.api_key.name)

    @http.route('/api/v1/ai/places/<int:place_id>/profile', **WRITE)
    @api_endpoint(write=True)
    def upsert_profile(self, ctx, place_id, **_params):
        return place_service.upsert_profile(self._place(ctx, place_id), ctx.json_body(), ctx.api_key.name)

    @http.route('/api/v1/ai/profiles/seed-known', **WRITE)
    @api_endpoint(write=True)
    def seed_known(self, ctx, **_params):
        return place_service.seed_known_profiles(ctx.env, ctx.company)

    @staticmethod
    def _place(ctx, place_id):
        """Địa điểm theo id, KỂ CẢ bản đã lưu trữ — để mở lại được bản gộp nhầm."""
        place = ctx.env['hlv.vtracking.place'].with_context(active_test=False).browse(place_id).exists()
        if not place or place.company_id != ctx.company:
            raise ApiError('NOT_FOUND', 'Không tìm thấy địa điểm có id %s.' % place_id, 404)
        return place
