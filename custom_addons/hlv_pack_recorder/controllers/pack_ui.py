# -*- coding: utf-8 -*-
"""Route cho màn hình đóng gói gọi vào: khai báo máy, bật/tắt ghi hình."""
import logging

from markupsafe import escape
from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PackRecorderUi(http.Controller):

    @http.route('/pack_recorder/set_station', type='http', auth='user', methods=['GET'])
    def set_station(self, key=None, **kw):
        """Gán mã bàn cho máy này, chạy một lần lúc lắp máy.

        Mã được lưu vào localStorage của trình duyệt trên máy đóng gói, sau đó
        mọi lần mở phiếu đều gửi kèm. Không dùng tài khoản Odoo để nhận diện bàn
        vì nhiều bàn thường dùng chung một login.
        """
        key = (key or '').strip()
        station = request.env['hlv.pack.station'].sudo().search(
            [('station_key', '=', key)], limit=1) if key else None

        if not station:
            options = request.env['hlv.pack.station'].sudo().search([])
            rows = ''.join(
                '<li><a href="/pack_recorder/set_station?key=%s">%s — %s (%d camera)</a></li>' % (
                    escape(s.station_key), escape(s.warehouse_id.name or ''),
                    escape(s.name), s.camera_count,
                ) for s in options
            )
            body = (
                '<h2>Chọn bàn đóng gói cho máy này</h2>'
                '<p>Bấm vào đúng bàn mà máy này đang đặt. Chỉ cần làm một lần.</p>'
                '<ul>%s</ul>' % (rows or '<li><i>Chưa khai bàn nào trong Odoo.</i></li>')
            )
            return Response(_page(body), content_type='text/html; charset=utf-8')

        body = (
            '<h2>Đã gán máy này cho bàn: %s</h2>'
            '<p>Kho %s · %d camera</p>'
            '<p>Đóng tab này và mở lại màn hình đóng gói là xong.</p>'
            '<script>try{localStorage.setItem("hlvPackStationKey",%s);}catch(e){}</script>'
        ) % (
            escape(station.name), escape(station.warehouse_id.name or ''),
            station.camera_count, _js_string(station.station_key),
        )
        return Response(_page(body), content_type='text/html; charset=utf-8')

    @http.route('/pack_recorder/start', type='json', auth='user', methods=['POST'])
    def start(self, **kw):
        """Màn hình đóng gói báo: bắt đầu quay phiếu này ở bàn này."""
        picking, station, err = _resolve(kw)
        if err:
            return err

        # Quy tắc "bàn nào được ghi hình" nằm ở start_for_picking, đừng chép lại
        # ở đây: hai chỗ cùng định nghĩa một luật là bug đang chờ xảy ra.
        recordings = request.env['hlv.pack.recording'].sudo().start_for_picking(picking, station)
        if not recordings:
            # Không phải lỗi của nhân viên: báo qua console cho kỹ thuật, không
            # hiện gì trên màn hình để khỏi làm gián đoạn việc đóng gói.
            return {
                'ok': False,
                'error': 'no_recording',
                'station': station.name,
                'agent_status': station.agent_status,
            }
        return {
            'ok': True,
            'station': station.name,
            'cameras': recordings.mapped('camera_id.name'),
        }

    @http.route('/pack_recorder/heartbeat', type='json', auth='user', methods=['POST'])
    def heartbeat(self, **kw):
        """Màn hình đóng gói báo nó vẫn đang mở, 10 giây một lần."""
        picking, _station, err = _resolve(kw, need_station=False)
        if err:
            return err
        alive = request.env['hlv.pack.recording'].sudo().touch_heartbeat(picking)
        return {'ok': True, 'alive': alive}

    @http.route('/pack_recorder/stop', type='json', auth='user', methods=['POST'])
    def stop(self, **kw):
        """Màn hình đóng gói báo: phiếu xong, đóng file lại."""
        picking, _station, err = _resolve(kw, need_station=False)
        if err:
            return err
        recordings = request.env['hlv.pack.recording'].sudo().stop_for_picking(picking)
        return {'ok': True, 'stopped': len(recordings)}


def _resolve(params, need_station=True):
    """Đọc picking_id / station_key từ payload.

    Trả về (picking, station, error_dict). error_dict là None khi mọi thứ hợp lệ.
    Biên: thiếu station_key -> không coi là lỗi cứng, trả error 'no_station' để
    màn hình đóng gói chỉ ghi log chứ không chặn nhân viên làm việc.
    """
    try:
        picking_id = int(params.get('picking_id') or 0)
    except (TypeError, ValueError):
        picking_id = 0
    picking = request.env['stock.picking'].sudo().browse(picking_id).exists()
    if not picking:
        return None, None, {'ok': False, 'error': 'unknown picking'}

    if not need_station:
        return picking, None, None

    station_key = (params.get('station_key') or '').strip()
    if not station_key:
        return picking, None, {'ok': False, 'error': 'no_station'}

    station = request.env['hlv.pack.station'].sudo().search(
        [('station_key', '=', station_key)], limit=1)
    if not station:
        _logger.warning("PACK_REC máy gửi mã bàn lạ: %s", station_key)
        return picking, None, {'ok': False, 'error': 'no_station'}
    return picking, station, None


def _js_string(value):
    """Nhúng một chuỗi vào JS an toàn: bọc nháy kép và escape theo HTML."""
    return '"%s"' % escape(value or '')


def _page(body_html):
    return (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        '<title>Bàn đóng gói</title>'
        '<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;'
        'margin:40px auto;padding:0 16px;line-height:1.6}a{color:#1a73e8}'
        'li{margin:6px 0}</style></head><body>%s</body></html>' % body_html
    )
