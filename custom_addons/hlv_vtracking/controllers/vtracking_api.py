"""API đọc vị trí đội xe cho ứng dụng ngoài.

Xác thực bằng header ``X-API-Key`` với khoá cấp ở Cấu hình > Khoá API — không dùng
session Odoo, vì bên gọi là ứng dụng khác máy, không có cookie.

**Chỉ xe bật "Theo dõi vTracking" mới được trả về.** Đó là ranh giới duy nhất quyết định
ứng dụng ngoài nhìn thấy gì; không có tham số nào nới được nó.

Mọi endpoint trả về cùng một khung:
    {"success": true,  "data": {...}}
    {"success": false, "error": {"code": "...", "message": "..."}}
"""

import json
import logging
from datetime import date, datetime

import pytz

from odoo import http
from odoo.http import Response, request

from ..services import vtracking_sync
from ..services.vtracking_client import VTrackingError
from ..tools.vtracking_parse import day_bounds_ms, ms_to_utc_naive

_logger = logging.getLogger(__name__)

# Trần số xe trả về một lần. Đội xe thực tế vài chục chiếc; có trần để một tài khoản cấu
# hình sai không kéo về nghìn bản ghi.
MAX_VEHICLES = 500

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
    'Access-Control-Max-Age': '86400',
}


class VtrackingPublicAPI(http.Controller):

    # ------------------------------------------------------------------
    # Endpoint
    # ------------------------------------------------------------------
    @http.route('/api/v1/fleet/vehicles', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, save_session=False)
    def list_vehicles(self, **params):
        """Danh sách xe đang theo dõi kèm vị trí gần nhất đã đồng bộ.

        Không gọi sang vTracking: trả về đúng những gì cron đã đồng bộ. Ứng dụng ngoài
        gọi dồn dập cũng không làm tài khoản vTracking dính 429.

        Tham số: ``plate`` lọc theo biển số (khớp một phần), ``status`` lọc theo trạng thái.
        """
        preflight = self._preflight()
        if preflight:
            return preflight
        api_key = self._authenticate()
        if isinstance(api_key, Response):
            return api_key

        domain = [
            ('vtracking_enabled', '=', True),
            ('company_id', 'in', [api_key.company_id.id, False]),
        ]
        if params.get('plate'):
            domain.append(('license_plate', 'ilike', params['plate']))
        if params.get('status'):
            domain.append(('vtracking_status', '=', params['status']))

        vehicles = request.env['fleet.vehicle'].sudo().search(
            domain, limit=MAX_VEHICLES, order='license_plate',
        )
        return self._ok({
            'count': len(vehicles),
            'vehicles': [v._vtracking_map_payload() for v in vehicles],
        })

    @http.route('/api/v1/fleet/vehicles/<int:vehicle_id>/journey', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, save_session=False)
    def vehicle_journey(self, vehicle_id, **params):
        """Hành trình một xe trong một ngày.

        ``date`` dạng YYYY-MM-DD, mặc định hôm nay. ``source``:
        - ``stored`` (mặc định) — đọc từ lịch sử đã lưu trong Odoo. Nhanh, không tốn
          lượt gọi vTracking, nhưng chỉ có dữ liệu cron đã kéo về.
        - ``live`` — hỏi thẳng vTracking. Dùng cho ngày hôm nay, khi cron chưa chạy.

        Mặc định là ``stored`` có chủ ý: để một ứng dụng gọi vòng lặp không vô tình bắn
        hàng loạt request sang vTracking và làm khoá bị chặn.
        """
        preflight = self._preflight()
        if preflight:
            return preflight
        api_key = self._authenticate()
        if isinstance(api_key, Response):
            return api_key

        vehicle = request.env['fleet.vehicle'].sudo().browse(vehicle_id)
        if not vehicle.exists() or not vehicle.vtracking_enabled:
            return self._error('NOT_FOUND', 'Không có xe này hoặc xe không được theo dõi.', 404)
        if vehicle.company_id and vehicle.company_id != api_key.company_id:
            return self._error('FORBIDDEN', 'Khoá API không có quyền với xe này.', 403)

        try:
            day = self._parse_date(params.get('date'))
        except ValueError:
            return self._error('BAD_REQUEST', 'Tham số date phải có dạng YYYY-MM-DD.', 400)

        if (params.get('source') or 'stored') == 'live':
            try:
                result = vtracking_sync.fetch_journey(request.env, vehicle, day, store=True)
            except VTrackingError as exc:
                return self._error('UPSTREAM_ERROR', str(exc), 502)
            pings = result['pings']
            distance = result['distance_km']
        else:
            pings = self._stored_pings(vehicle, day)
            distance = None

        return self._ok({
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate or '',
            'date': day.isoformat(),
            'distance_km': distance,
            'count': len(pings),
            'points': [self._ping_payload(ping) for ping in pings],
        })

    @http.route('/api/v1/fleet/places', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, save_session=False)
    def list_places(self, **params):
        """Địa điểm cố định trên bản đồ (kho, đối tác...) kèm cách hiển thị của từng loại.

        Chỉ trả địa điểm ĐÃ có toạ độ: địa điểm chưa tra được là việc cần xử lý trong
        Odoo, gửi ra ngoài thì ứng dụng cũng không vẽ được gì.

        Tham số: ``type`` lọc theo mã loại (``code``), ``confirmed_only=1`` chỉ lấy toạ độ
        đã duyệt hoặc nhập tay — dùng khi ứng dụng không muốn hiển thị phỏng đoán của máy.
        """
        preflight = self._preflight()
        if preflight:
            return preflight
        api_key = self._authenticate()
        if isinstance(api_key, Response):
            return api_key

        domain = [('has_coords', '=', True), ('company_id', '=', api_key.company_id.id)]
        if params.get('type'):
            domain.append(('type_id.code', '=', params['type']))
        if params.get('confirmed_only') in ('1', 'true', 'True'):
            domain.append(('geo_state', 'in', ('confirmed', 'manual')))

        places = request.env['hlv.vtracking.place'].sudo().search(domain, order='type_id, name')
        types = request.env['hlv.vtracking.place.type'].sudo().search([])
        return self._ok({
            'count': len(places),
            'types': [{
                'id': t.id, 'code': t.code or '', 'name': t.name,
                'color': t.color, 'size': t.size,
            } for t in types],
            'places': [p._map_payload() for p in places],
        })

    @http.route('/api/v1/fleet/map-config', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, save_session=False)
    def map_config(self, **_params):
        """Nguồn tile bản đồ, để ứng dụng ngoài vẽ cùng nền bản đồ với Odoo."""
        preflight = self._preflight()
        if preflight:
            return preflight
        api_key = self._authenticate()
        if isinstance(api_key, Response):
            return api_key
        company = api_key.company_id
        return self._ok({
            'tile_url': company.vtracking_map_tile_url or '',
            'tile_attribution': company.vtracking_map_attribution or '',
        })

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _stored_pings(self, vehicle, day):
        """Bản tin đã lưu của một ngày ĐỊA PHƯƠNG, đổi sang khoảng UTC để truy vấn."""
        tz = request.env.user.tz or vtracking_sync.DEFAULT_TZ
        start, end = self._day_bounds_utc(day, tz)
        records = request.env['hlv.vtracking.position'].sudo().search([
            ('vehicle_id', '=', vehicle.id),
            ('ts', '>=', start),
            ('ts', '<=', end),
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
    def _day_bounds_utc(day, tz_name):
        """Ngày địa phương -> cặp datetime naive UTC bao trọn ngày đó."""
        start_ms, end_ms = day_bounds_ms(day, pytz.timezone(tz_name))
        return ms_to_utc_naive(start_ms), ms_to_utc_naive(end_ms)

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

    @staticmethod
    def _parse_date(value):
        """Chuỗi YYYY-MM-DD -> date. Rỗng thì trả hôm nay. Ném ValueError nếu sai dạng."""
        if not value:
            return date.today()
        return datetime.strptime(value, '%Y-%m-%d').date()

    def _preflight(self):
        """200 rỗng cho OPTIONS. Trả None nếu không phải preflight."""
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=dict(CORS_HEADERS))
        return None

    def _authenticate(self):
        """Bản ghi khoá hợp lệ, hoặc Response lỗi 401 để caller trả thẳng ra."""
        raw_key = request.httprequest.headers.get('X-API-Key') or ''
        api_key = request.env['hlv.vtracking.api.key'].sudo().authenticate(raw_key)
        if not api_key:
            # Không nói khoá sai hay khoá đã thu hồi: chênh lệch đó giúp người dò khoá.
            return self._error('UNAUTHORIZED', 'Khoá API không hợp lệ.', 401)
        api_key.mark_used(request.httprequest.remote_addr)
        return api_key

    @staticmethod
    def _ok(data):
        return Response(
            json.dumps({'success': True, 'data': data}, default=str, ensure_ascii=False),
            status=200, content_type='application/json; charset=utf-8',
            headers=dict(CORS_HEADERS),
        )

    @staticmethod
    def _error(code, message, status):
        return Response(
            json.dumps(
                {'success': False, 'error': {'code': code, 'message': message}},
                ensure_ascii=False,
            ),
            status=status, content_type='application/json; charset=utf-8',
            headers=dict(CORS_HEADERS),
        )
