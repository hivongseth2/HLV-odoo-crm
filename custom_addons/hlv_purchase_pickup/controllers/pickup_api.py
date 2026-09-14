"""API cho trang /pickup.

Ba quy tắc chung của mọi route ghi nhận trong file này:

1. **Chống bấm trùng.** Client gửi ``client_event_id`` sinh một lần cho mỗi lần BẤM. Gửi
   lại bao nhiêu lần cũng chỉ tính một.
2. **Ghi theo giờ bấm, không theo giờ máy chủ nhận.** Điện thoại mất sóng rồi gửi lại sau
   20 phút thì giờ máy chủ không còn là lúc người ta đứng ở nhà cung cấp.
3. **Luôn trả về nguyên trạng chuyến sau thao tác.** Client vẽ lại từ dữ liệu server chứ
   không tự đoán trạng thái mới — điện thoại mất sóng giữa chừng thì màn hình vẫn đúng sau
   lần gọi kế tiếp.

Kiểm quyền "chuyến này có phải của tôi không" nằm ở đây chứ không ở record rule, vì quản lý
cũng phải mở được chuyến của người khác để hỗ trợ qua điện thoại.
"""

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..services import pickup_metrics

GROUP_RUNNER = 'hlv_purchase_pickup.group_pickup_runner'
GROUP_MANAGER = 'hlv_purchase_pickup.group_pickup_manager'


def _ok(**kw):
    return dict({'status': 'success'}, **kw)


def _err(message):
    return {'status': 'error', 'message': message}


class PickupApiController(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_access(self):
        if not request.env.user.has_group(GROUP_RUNNER):
            raise AccessError('Tài khoản chưa có quyền đi nhận hàng.')

    def _is_manager(self):
        return request.env.user.has_group(GROUP_MANAGER)

    def _get_run(self, run_id):
        run = request.env['hlv.pickup.run'].browse(int(run_id or 0)).exists()
        if not run:
            raise UserError('Không tìm thấy chuyến.')
        if run.driver_user_id != request.env.user and not self._is_manager():
            raise AccessError('Chuyến này không phải của bạn.')
        return run

    def _get_stop(self, stop_id):
        stop = request.env['hlv.pickup.stop'].browse(int(stop_id or 0)).exists()
        if not stop:
            raise UserError('Không tìm thấy điểm nhận.')
        self._get_run(stop.run_id.id)
        return stop

    def _get_line(self, line_id):
        line = request.env['hlv.pickup.line'].browse(int(line_id or 0)).exists()
        if not line:
            raise UserError('Không tìm thấy đơn.')
        self._get_run(line.run_id.id)
        return line

    def _event_time(self, client_ts):
        """Mốc để ghi: giờ bấm trên máy người dùng nếu còn đáng tin, không thì giờ máy chủ."""
        return pickup_metrics.pick_event_time(
            pickup_metrics.parse_iso_datetime(client_ts), fields.Datetime.now(),
        )

    def _claim(self, client_event_id, route, record):
        """False nghĩa là lần bấm này đã xử lý rồi — bỏ qua, không làm lại."""
        return request.env['hlv.pickup.client.event'].claim(client_event_id, route, record)

    # ------------------------------------------------------------------
    # Đọc
    # ------------------------------------------------------------------
    @http.route('/api/pickup/config', type='json', auth='user', methods=['POST'])
    def api_config(self, **kwargs):
        self._check_access()
        params = request.env['ir.config_parameter'].sudo()
        return _ok(
            user_name=request.env.user.name,
            is_manager=self._is_manager(),
            require_return=params.get_param(
                'hlv_purchase_pickup.require_return', 'True'
            ) not in ('False', 'false', '0', ''),
        )

    @http.route('/api/pickup/my_run', type='json', auth='user', methods=['POST'])
    def api_my_run(self, date=None, run_id=None, **kwargs):
        """Chuyến đang đi của tôi.

        Không có ``run_id`` thì tự tìm: ưu tiên chuyến đang dở (kể cả của hôm trước — chuyến
        đi muộn qua nửa đêm là có thật), sau đó mới tới chuyến được giao trong ngày.
        """
        self._check_access()
        try:
            run = self._get_run(run_id) if run_id else self._find_current_run(date)
        except (UserError, AccessError) as error:
            return _err(str(error))
        if not run:
            return _ok(run=None)
        return _ok(run=self._run_payload(run))

    def _find_current_run(self, date):
        Run = request.env['hlv.pickup.run']
        base = [('driver_user_id', '=', request.env.user.id)]
        running = Run.search(base + [('state', '=', 'departed')], order='date desc', limit=1)
        if running:
            return running
        day = date or fields.Date.to_string(fields.Date.context_today(request.env.user))
        return Run.search(
            base + [('date', '=', day), ('state', 'in', ('assigned', 'draft'))],
            order='id desc', limit=1,
        )

    def _run_payload(self, run):
        return {
            'id': run.id,
            'name': run.name,
            'date': fields.Date.to_string(run.date),
            'state': run.state,
            'warehouse_name': run.warehouse_id.name or '',
            'vehicle_note': run.vehicle_note or '',
            'note': run.note or '',
            'depart_at': fields.Datetime.to_string(run.depart_at) if run.depart_at else '',
            'returned_at': fields.Datetime.to_string(run.returned_at) if run.returned_at else '',
            'stop_count': run.stop_count,
            'done_stop_count': run.done_stop_count,
            'line_count': run.line_count,
            'received_line_count': run.received_line_count,
            'total_travel_minutes': run.total_travel_minutes,
            'total_service_minutes': run.total_service_minutes,
            'total_minutes': run.total_minutes,
            'origin': self._partner_coords(run.warehouse_id.partner_id),
            'stops': [
                self._stop_payload(stop)
                for stop in run.stop_ids.sorted(lambda s: (s.sequence, s.id))
            ],
        }

    def _stop_payload(self, stop):
        point = stop.point_id
        return {
            'id': stop.id,
            'sequence': stop.sequence,
            'state': stop.state,
            'point_name': point.name or '',
            'address': point.address or '',
            'contact_name': point.contact_name or '',
            'contact_phone': point.contact_phone or '',
            'point_note': point.note or '',
            'lat': point.latitude or 0.0,
            'lng': point.longitude or 0.0,
            'map_url': point.map_url or '',
            'arrived_at': fields.Datetime.to_string(stop.arrived_at) if stop.arrived_at else '',
            'done_at': fields.Datetime.to_string(stop.done_at) if stop.done_at else '',
            'travel_minutes': stop.travel_minutes,
            'service_minutes': stop.service_minutes,
            'planned_travel_minutes': stop.planned_travel_minutes,
            'planned_arrival': (
                fields.Datetime.to_string(stop.planned_arrival) if stop.planned_arrival else ''
            ),
            'expected_service_minutes': point.median_service_minutes,
            'sample_count': point.sample_count,
            'skip_reason': stop.skip_reason or '',
            'lines': [self._line_payload(line) for line in stop.line_ids],
        }

    def _line_payload(self, line):
        return {
            'id': line.id,
            'po_name': line.po_name or '',
            'state': line.state,
            'package_note': line.package_note or '',
            'note': line.note or '',
            'amount': line.po_amount or 0.0,
        }

    def _partner_coords(self, partner):
        if partner and partner.partner_latitude and partner.partner_longitude:
            return {'lat': partner.partner_latitude, 'lng': partner.partner_longitude}
        return None

    # ------------------------------------------------------------------
    # Ghi mốc
    # ------------------------------------------------------------------
    @http.route('/api/pickup/run_depart', type='json', auth='user', methods=['POST'])
    def api_run_depart(self, run_id=None, client_event_id=None, client_ts=None, **kwargs):
        self._check_access()
        try:
            run = self._get_run(run_id)
            if self._claim(client_event_id, 'run_depart', run):
                run.mark_departed(self._event_time(client_ts))
            return _ok(run=self._run_payload(run))
        except (UserError, AccessError) as error:
            return _err(str(error))

    @http.route('/api/pickup/stop_arrive', type='json', auth='user', methods=['POST'])
    def api_stop_arrive(self, stop_id=None, gps=None, client_event_id=None, client_ts=None,
                        **kwargs):
        self._check_access()
        try:
            stop = self._get_stop(stop_id)
            if self._claim(client_event_id, 'stop_arrive', stop):
                stop.mark_arrived(self._event_time(client_ts), self._clean_gps(gps))
            return _ok(run=self._run_payload(stop.run_id))
        except (UserError, AccessError) as error:
            return _err(str(error))

    def _clean_gps(self, gps):
        """Lọc toạ độ trình duyệt gửi lên. Thiếu hoặc sai kiểu thì coi như không có GPS.

        Không được để một giá trị rác làm hỏng cả thao tác bấm "đã tới": mốc thời gian quan
        trọng hơn toạ độ nhiều.
        """
        if not isinstance(gps, dict):
            return None
        try:
            lat = float(gps.get('lat'))
            lng = float(gps.get('lng'))
        except (TypeError, ValueError):
            return None
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0) or (not lat and not lng):
            return None
        try:
            accuracy = int(float(gps.get('accuracy') or 0))
        except (TypeError, ValueError):
            accuracy = 0
        return {'lat': lat, 'lng': lng, 'accuracy': accuracy}

    @http.route('/api/pickup/stop_done', type='json', auth='user', methods=['POST'])
    def api_stop_done(self, stop_id=None, client_event_id=None, client_ts=None, **kwargs):
        self._check_access()
        try:
            stop = self._get_stop(stop_id)
            if self._claim(client_event_id, 'stop_done', stop):
                stop.mark_done(self._event_time(client_ts))
            return _ok(run=self._run_payload(stop.run_id))
        except (UserError, AccessError) as error:
            return _err(str(error))

    @http.route('/api/pickup/stop_skip', type='json', auth='user', methods=['POST'])
    def api_stop_skip(self, stop_id=None, reason=None, failed=False, client_event_id=None,
                      **kwargs):
        self._check_access()
        try:
            stop = self._get_stop(stop_id)
            if self._claim(client_event_id, 'stop_skip', stop):
                stop.mark_skipped(reason, failed=bool(failed))
            return _ok(run=self._run_payload(stop.run_id))
        except (UserError, AccessError) as error:
            return _err(str(error))

    @http.route('/api/pickup/line_state', type='json', auth='user', methods=['POST'])
    def api_line_state(self, line_id=None, state=None, note=None, package_note=None,
                       client_event_id=None, client_ts=None, **kwargs):
        self._check_access()
        try:
            line = self._get_line(line_id)
            if self._claim(client_event_id, 'line_state', line):
                line.mark_state(state, note=note, package_note=package_note,
                                when=self._event_time(client_ts))
            return _ok(run=self._run_payload(line.run_id))
        except (UserError, AccessError) as error:
            return _err(str(error))

    @http.route('/api/pickup/run_finish', type='json', auth='user', methods=['POST'])
    def api_run_finish(self, run_id=None, client_event_id=None, client_ts=None, **kwargs):
        self._check_access()
        try:
            run = self._get_run(run_id)
            if self._claim(client_event_id, 'run_finish', run):
                run.mark_finished(self._event_time(client_ts))
            return _ok(run=self._run_payload(run))
        except (UserError, AccessError) as error:
            return _err(str(error))
