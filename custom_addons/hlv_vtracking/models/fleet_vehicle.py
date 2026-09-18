import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import map_data, vtracking_sync
from ..services.vtracking_client import VTrackingError
from ..tools.vtracking_parse import alarm_labels, normalize_plate

_logger = logging.getLogger(__name__)

# Quá mốc này mà không có tin mới thì coi là mất liên lạc. 30 phút: thiết bị gửi thưa khi
# xe đỗ nên ngưỡng ngắn hơn sẽ báo động giả cho cả bãi xe đang nghỉ.
STALE_MINUTES = 30

STATUS_LABELS = {
    'run': 'Đang chạy',
    'stop': 'Dừng',
    'park': 'Đỗ',
    'offline': 'Mất tín hiệu',
    'badgps': 'GPS kém',
}


class FleetVehicle(models.Model):
    """Gắn dữ liệu định vị vTracking vào xe của Đội xe.

    Chỉ xe bật ``vtracking_enabled`` mới được đồng bộ, mới hiện trên bản đồ và mới trả
    ra API ngoài. Tài khoản vTracking có thể chứa xe của pháp nhân khác; cờ này là ranh
    giới giữa "xe công ty quản" và "xe có trong tài khoản".
    """

    _inherit = 'fleet.vehicle'

    vtracking_enabled = fields.Boolean(
        string='Theo dõi vTracking', default=False, index=True,
        help='Bật thì xe này được đồng bộ vị trí, hiện trên bản đồ và trả ra API.',
    )
    vtracking_id = fields.Char(
        string='Mã vTracking', readonly=True, copy=False, index=True,
        help='UUID phía vTracking. Lấy tự động khi đồng bộ, dùng để gọi lịch sử hành trình.',
    )
    plate_key = fields.Char(
        string='Khoá biển số', compute='_compute_plate_key', store=True, index=True,
        help='Biển số bỏ hết dấu gạch, dấu chấm và khoảng trắng. vTracking ghi 51C77577 '
             'còn Odoo có thể ghi 51C-775.77 — ghép theo chuỗi thô sẽ trượt gần hết đội xe.',
    )

    # --- Vị trí gần nhất ----------------------------------------------------
    vtracking_latitude = fields.Float(string='Vĩ độ', digits=(10, 7), readonly=True, copy=False)
    vtracking_longitude = fields.Float(string='Kinh độ', digits=(10, 7), readonly=True, copy=False)
    vtracking_speed = fields.Float(string='Tốc độ (km/h)', readonly=True, copy=False)
    vtracking_direction = fields.Float(string='Hướng', readonly=True, copy=False)
    vtracking_odometer = fields.Float(
        string='Công-tơ-mét thiết bị (km)', readonly=True, copy=False,
        help='Số của thiết bị vTracking, không phải đồng hồ xe và không phải '
             'odometer của Đội xe.',
    )
    vtracking_status = fields.Selection(
        [(key, label) for key, label in STATUS_LABELS.items()],
        string='Trạng thái', readonly=True, copy=False, index=True,
    )
    vtracking_status_since = fields.Datetime(
        string='Giữ trạng thái từ', readonly=True, copy=False,
        help='Thời điểm BẮT ĐẦU trạng thái hiện tại, do vTracking trả về. Nhờ đó biết xe '
             'đã đứng yên bao lâu mà không phải tải cả lịch sử hành trình.',
    )
    vtracking_geocoding = fields.Char(
        string='Vị trí (mô tả)', readonly=True, copy=False,
        help='Địa chỉ do vTracking tự suy từ toạ độ, cấp phường/xã. Để tham khảo, không '
             'dùng làm địa chỉ chính thức.',
    )
    vtracking_position_at = fields.Datetime(
        string='Tin gần nhất lúc', readonly=True, copy=False, index=True,
    )
    vtracking_synced_at = fields.Datetime(string='Đồng bộ lúc', readonly=True, copy=False)

    # --- Cảm biến -----------------------------------------------------------
    # 'unknown' là giá trị thật, không phải thiếu dữ liệu: xe không lắp cảm biến cửa mà
    # hiển thị "Đóng" thì người xem tin vào một thứ không tồn tại.
    vtracking_acc = fields.Selection(
        [('on', 'Mở'), ('off', 'Tắt'), ('unknown', 'Không có cảm biến')],
        string='Khoá điện (ACC)', default='unknown', readonly=True, copy=False,
    )
    vtracking_door = fields.Selection(
        [('on', 'Mở'), ('off', 'Đóng'), ('unknown', 'Không có cảm biến')],
        string='Cửa thùng', default='unknown', readonly=True, copy=False,
    )
    vtracking_driver_name = fields.Char(
        string='Tài xế theo thiết bị', readonly=True, copy=False,
        help='Tên do thiết bị vTracking báo. Chỉ để đối chiếu — người chịu trách nhiệm '
             'vẫn là tài xế gán trong Đội xe.',
    )

    # --- Cảnh báo -----------------------------------------------------------
    vtracking_alarm_codes = fields.Char(string='Mã cảnh báo', readonly=True, copy=False)
    vtracking_alarm_text = fields.Char(
        string='Cảnh báo', compute='_compute_vtracking_alarm_text',
    )
    vtracking_is_stale = fields.Boolean(
        string='Mất liên lạc', compute='_compute_vtracking_is_stale',
    )

    position_ids = fields.One2many(
        'hlv.vtracking.position', 'vehicle_id', string='Lịch sử vị trí',
    )

    @api.depends('license_plate')
    def _compute_plate_key(self):
        for vehicle in self:
            vehicle.plate_key = normalize_plate(vehicle.license_plate)

    @api.depends('vtracking_alarm_codes')
    def _compute_vtracking_alarm_text(self):
        for vehicle in self:
            codes = (vehicle.vtracking_alarm_codes or '').split(',')
            # Gán False chứ không gán chuỗi rỗng: view dùng `!= False` để tô đỏ dòng có
            # cảnh báo, mà chuỗi rỗng thì khác False nên mọi dòng sẽ đỏ.
            vehicle.vtracking_alarm_text = alarm_labels([c for c in codes if c]) or False

    @api.depends('vtracking_position_at')
    def _compute_vtracking_is_stale(self):
        # Không store được: giá trị phụ thuộc thời điểm hiện tại, không phụ thuộc bản ghi.
        now = fields.Datetime.now()
        for vehicle in self:
            last = vehicle.vtracking_position_at
            vehicle.vtracking_is_stale = bool(
                vehicle.vtracking_enabled
                and (not last or (now - last).total_seconds() > STALE_MINUTES * 60)
            )

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_vtracking_sync_now(self):
        """Đồng bộ ngay vị trí toàn đội và báo kết quả, kể cả biển số không ghép được."""
        try:
            stats = vtracking_sync.sync_vehicles(self.env)
        except VTrackingError as exc:
            raise UserError(str(exc)) from exc
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đồng bộ vTracking',
                'message': self._vtracking_sync_message(stats),
                'type': 'warning' if (stats['unmatched_plates'] or stats['missing_plates'])
                        else 'success',
                'sticky': bool(stats['unmatched_plates'] or stats['missing_plates']),
            },
        }

    @api.model
    def _vtracking_sync_message(self, stats):
        """Câu tóm tắt kết quả đồng bộ. Nêu rõ xe lệch thay vì chỉ báo số xe thành công."""
        parts = ['Đã cập nhật %s/%s xe.' % (stats['matched'], stats['total'])]
        if stats['missing_plates']:
            parts.append(
                'vTracking không trả về: %s.' % ', '.join(stats['missing_plates'][:10])
            )
        if stats['unmatched_plates']:
            parts.append(
                'Có trên vTracking nhưng chưa khai trong Đội xe: %s.'
                % ', '.join(stats['unmatched_plates'][:10])
            )
        return ' '.join(parts)

    def action_open_vtracking_map(self):
        """Mở bản đồ và tự chọn xe này."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'hlv_vtracking_map',
            'name': 'Bản đồ đội xe',
            'params': {'focus_vehicle_id': self.id},
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_vtracking_sync_vehicles(self):
        """Cập nhật vị trí hiện tại cho từng công ty có cấu hình vTracking."""
        companies = self.env['res.company'].sudo().search([
            ('vtracking_api_key', '!=', False),
            ('vtracking_base_url', '!=', False),
        ])
        for company in companies:
            try:
                vtracking_sync.sync_vehicles(self.env, company)
            except VTrackingError as exc:
                # Một công ty cấu hình sai không được chặn các công ty còn lại.
                self.env.cr.rollback()
                _logger.warning(
                    'vTracking: đồng bộ công ty %s lỗi: %s', company.display_name, exc,
                )
            else:
                self.env.cr.commit()
        return True

    @api.model
    def _cron_vtracking_fetch_journeys(self):
        """Kéo hành trình của NGÀY HÔM QUA.

        Chạy sau nửa đêm để chắc chắn ngày đã khép lại: lấy hành trình của ngày đang
        chạy thì lần nào cũng thiếu phần cuối ngày.
        """
        yesterday = fields.Date.context_today(self) - timedelta(days=1)
        companies = self.env['res.company'].sudo().search([
            ('vtracking_api_key', '!=', False),
        ])
        for company in companies:
            vtracking_sync.sync_journeys_for_day(self.env, yesterday, company)
        return True

    # ------------------------------------------------------------------
    # Dữ liệu cho bản đồ
    # ------------------------------------------------------------------
    @api.model
    def get_vtracking_map_data(self):
        """Dữ liệu một lần vẽ bản đồ. Gọi từ màn bản đồ; phần dựng nằm ở ``services/map_data``."""
        return map_data.build_map_data(self.env, STALE_MINUTES)

    def _vtracking_map_payload(self):
        """Một xe ở dạng dict để vẽ ghim. Xe chưa có toạ độ vẫn trả về.

        Vẫn trả về để danh sách bên cạnh bản đồ hiện đủ đội xe — xe chưa có toạ độ là
        tình trạng cần thấy, không phải thứ nên giấu đi.
        """
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.license_plate or self.display_name,
            'model_name': self.model_id.display_name or '',
            'driver_name': self.driver_id.display_name or '',
            'device_driver_name': self.vtracking_driver_name or '',
            'latitude': self.vtracking_latitude or None,
            'longitude': self.vtracking_longitude or None,
            'speed': self.vtracking_speed or 0.0,
            'direction': self.vtracking_direction or 0.0,
            'status': self.vtracking_status or '',
            'status_label': STATUS_LABELS.get(self.vtracking_status, 'Chưa có dữ liệu'),
            'status_since': self._vtracking_iso(self.vtracking_status_since),
            'geocoding': self.vtracking_geocoding or '',
            'position_at': self._vtracking_iso(self.vtracking_position_at),
            'is_stale': self.vtracking_is_stale,
            'acc': self.vtracking_acc,
            'door': self.vtracking_door,
            'alarm_text': self.vtracking_alarm_text or '',
            'odometer': self.vtracking_odometer or 0.0,
        }

    @api.model
    def _vtracking_iso(self, value):
        """Datetime naive UTC -> chuỗi ISO có hậu tố Z, hoặc chuỗi rỗng.

        Gắn Z tường minh để trình duyệt không hiểu nhầm là giờ địa phương rồi hiển thị
        lệch 7 tiếng.
        """
        return value.isoformat() + 'Z' if value else ''
