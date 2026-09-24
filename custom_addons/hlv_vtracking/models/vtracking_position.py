import logging

from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Xoá theo lô để một lần dọn không khoá bảng quá lâu.
GC_BATCH_SIZE = 5000


class HlvVtrackingPosition(models.Model):
    """Một bản tin vị trí do thiết bị gửi.

    Bảng này phình nhanh: một xe chạy cả ngày gửi hơn nghìn bản tin. Vì vậy nó chỉ giữ
    dữ liệu trong thời hạn khai ở cấu hình công ty (mặc định 30 ngày) và có cron dọn.
    Đừng dùng nó làm nơi lưu trữ lâu dài — cái đáng giữ lâu là kết luận rút ra từ nó,
    không phải từng bản tin.
    """

    _name = 'hlv.vtracking.position'
    _description = 'Bản tin vị trí vTracking'
    _order = 'vehicle_id, ts desc'
    _rec_name = 'ts'

    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe', required=True, index=True, ondelete='cascade',
    )
    ts = fields.Datetime(
        string='Thời điểm', required=True, index=True,
        help='Lúc thiết bị gửi bản tin, giờ UTC.',
    )
    latitude = fields.Float(string='Vĩ độ', digits=(10, 7))
    longitude = fields.Float(string='Kinh độ', digits=(10, 7))
    speed = fields.Float(string='Tốc độ (km/h)')
    direction = fields.Float(string='Hướng')
    status = fields.Selection(
        [
            ('run', 'Đang chạy'),
            ('stop', 'Dừng'),
            ('park', 'Đỗ'),
            ('offline', 'Mất tín hiệu'),
            ('badgps', 'GPS kém'),
        ],
        string='Trạng thái', index=True,
    )
    geocoding = fields.Char(string='Vị trí (mô tả)')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True, index=True)

    _sql_constraints = [
        # Cùng một ngày có thể được lấy lại nhiều lần (cron chạy lại, người bấm tải lại).
        # Không có ràng buộc này thì mỗi lần lấy lại nhân đôi dữ liệu và mọi phép đếm về
        # sau đều sai.
        ('vehicle_ts_uniq', 'unique(vehicle_id, ts)',
         'Mỗi xe chỉ có một bản tin tại một thời điểm.'),
    ]

    @api.model
    def _cron_gc_positions(self):
        """Xoá bản tin cũ hơn thời hạn khai ở từng công ty.

        Công ty để thời hạn 0 thì giữ vĩnh viễn — bỏ qua, không tự ý xoá.
        """
        companies = self.env['res.company'].sudo().search([('vtracking_retention_days', '>', 0)])
        total = 0
        for company in companies:
            cutoff = fields.Datetime.now() - timedelta(days=company.vtracking_retention_days)
            while True:
                stale = self.sudo().search([
                    ('company_id', '=', company.id),
                    ('ts', '<', cutoff),
                ], limit=GC_BATCH_SIZE)
                if not stale:
                    break
                count = len(stale)
                stale.unlink()
                total += count
                self.env.cr.commit()
                if count < GC_BATCH_SIZE:
                    break
        if total:
            _logger.info('vTracking: đã dọn %s bản tin vị trí quá hạn.', total)
        return total
