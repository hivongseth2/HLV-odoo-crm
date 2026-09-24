"""API đọc vị trí đội xe cho ứng dụng ngoài (màn bản đồ của app khác).

**Chỉ xe bật "Theo dõi vTracking" mới được trả về.** Đó là ranh giới duy nhất quyết định
ứng dụng ngoài nhìn thấy gì; không có tham số nào nới được nó.

Khung phản hồi và cách xác thực: xem ``api_common``. API dành cho AI lập kế hoạch nằm ở
thư mục ``controllers/ai``.
"""

import pytz

from odoo import http

from ..services import vtracking_sync
from ..services.vtracking_client import VTrackingError
from ..tools.vtracking_parse import day_bounds_ms, ms_to_utc_naive
from .api_common import ROUTE_DEFAULTS, ApiError, api_endpoint

# Trần số xe trả về một lần. Đội xe thực tế vài chục chiếc; có trần để một tài khoản cấu
# hình sai không kéo về nghìn bản ghi.
MAX_VEHICLES = 500


class VtrackingPublicAPI(http.Controller):

    @http.route('/api/v1/fleet/vehicles', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def list_vehicles(self, ctx, **params):
        """Danh sách xe đang theo dõi kèm vị trí gần nhất đã đồng bộ.

        Không gọi sang vTracking: trả về đúng những gì cron đã đồng bộ. Ứng dụng ngoài
        gọi dồn dập cũng không làm tài khoản vTracking dính 429.

        Tham số: ``plate`` lọc theo biển số (khớp một phần), ``status`` lọc theo trạng thái.
        """
        domain = [
            ('vtracking_enabled', '=', True),
            ('company_id', 'in', [ctx.company.id, False]),
        ]
        if params.get('plate'):
            domain.append(('license_plate', 'ilike', params['plate']))
        if params.get('status'):
            domain.append(('vtracking_status', '=', params['status']))
        vehicles = ctx.env['fleet.vehicle'].search(domain, limit=MAX_VEHICLES, order='license_plate')
        return {
            'count': len(vehicles),
            'vehicles': [v._vtracking_map_payload() for v in vehicles],
        }

    @http.route('/api/v1/fleet/vehicles/<int:vehicle_id>/journey',
                methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def vehicle_journey(self, ctx, vehicle_id, **params):
        """Hành trình một xe trong một ngày.

        ``date`` dạng YYYY-MM-DD, mặc định hôm nay. ``source``:
        - ``stored`` (mặc định) — đọc từ lịch sử đã lưu trong Odoo. Nhanh, không tốn
          lượt gọi vTracking, nhưng chỉ có dữ liệu cron đã kéo về.
        - ``live`` — hỏi thẳng vTracking. Dùng cho ngày hôm nay, khi cron chưa chạy.

        Mặc định là ``stored`` có chủ ý: để một ứng dụng gọi vòng lặp không vô tình bắn
        hàng loạt request sang vTracking và làm khoá bị chặn.
        """
        vehicle = ctx.env['fleet.vehicle'].browse(vehicle_id).exists()
        if not vehicle or not vehicle.vtracking_enabled:
            raise ApiError('NOT_FOUND', 'Không có xe này hoặc xe không được theo dõi.', 404)
        if vehicle.company_id and vehicle.company_id != ctx.company:
            raise ApiError('FORBIDDEN', 'Khoá API không có quyền với xe này.', 403)
        day = ctx.parse_date(params.get('date'))

        distance = None
        if (params.get('source') or 'stored') == 'live':
            try:
                result = vtracking_sync.fetch_journey(ctx.env, vehicle, day, store=True)
            except VTrackingError as exc:
                raise ApiError('UPSTREAM_ERROR', str(exc), 502) from exc
            pings, distance = result['pings'], result['distance_km']
        else:
            pings = self._stored_pings(ctx.env, vehicle, day)

        return {
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate or '',
            'date': day.isoformat(),
            'distance_km': distance,
            'count': len(pings),
            'points': [self._ping_payload(ping) for ping in pings],
        }

    @http.route('/api/v1/fleet/places', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def list_places(self, ctx, **params):
        """Địa điểm cố định trên bản đồ (kho, đối tác...) kèm cách hiển thị của từng loại.

        Chỉ trả địa điểm ĐÃ có toạ độ: địa điểm chưa tra được là việc cần xử lý trong
        Odoo, gửi ra ngoài thì ứng dụng cũng không vẽ được gì.

        Tham số: ``type`` lọc theo mã loại (``code``), ``confirmed_only=1`` chỉ lấy toạ độ
        đã duyệt hoặc nhập tay — dùng khi ứng dụng không muốn hiển thị phỏng đoán của máy.
        """
        domain = [('has_coords', '=', True), ('company_id', '=', ctx.company.id)]
        if params.get('type'):
            domain.append(('type_id.code', '=', params['type']))
        if params.get('confirmed_only') in ('1', 'true', 'True'):
            domain.append(('geo_state', 'in', ('confirmed', 'manual')))
        places = ctx.env['hlv.vtracking.place'].search(domain, order='type_id, name')
        types = ctx.env['hlv.vtracking.place.type'].search([])
        return {
            'count': len(places),
            'types': [{
                'id': t.id, 'code': t.code or '', 'name': t.name,
                'color': t.color, 'size': t.size,
            } for t in types],
            'places': [p._map_payload() for p in places],
        }

    @http.route('/api/v1/fleet/map-config', methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
    @api_endpoint()
    def map_config(self, ctx, **_params):
        """Nguồn tile bản đồ, để ứng dụng ngoài vẽ cùng nền bản đồ với Odoo."""
        return {
            'tile_url': ctx.company.vtracking_map_tile_url or '',
            'tile_attribution': ctx.company.vtracking_map_attribution or '',
        }

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    @staticmethod
    def _stored_pings(env, vehicle, day):
        """Bản tin đã lưu của một ngày ĐỊA PHƯƠNG, đổi sang khoảng UTC để truy vấn."""
        tz = pytz.timezone(env.user.tz or vtracking_sync.DEFAULT_TZ)
        start_ms, end_ms = day_bounds_ms(day, tz)
        records = env['hlv.vtracking.position'].search([
            ('vehicle_id', '=', vehicle.id),
            ('ts', '>=', ms_to_utc_naive(start_ms)),
            ('ts', '<=', ms_to_utc_naive(end_ms)),
        ], order='ts asc')
        return [{
            'ts': record.ts,
            'latitude': record.latitude,
            'longitude': record.longitude,
            'speed': record.speed,
            'direction': record.direction,
            'status': record.status,
            'geocoding': record.geocoding,
        } for record in records]

    @staticmethod
    def _ping_payload(ping):
        moment = ping.get('ts')
        return {
            'ts': moment.isoformat() + 'Z' if moment else '',
            'latitude': ping.get('latitude'),
            'longitude': ping.get('longitude'),
            'speed': ping.get('speed') or 0.0,
            'direction': ping.get('direction') or 0.0,
            'status': ping.get('status') or '',
            'geocoding': ping.get('geocoding') or '',
        }
