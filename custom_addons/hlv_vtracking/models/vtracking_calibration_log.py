"""Nhật ký hiệu chỉnh định mức: mỗi lần cron đo và mỗi lần người bấm áp dụng là một dòng.

Cụm tuyến chỉ giữ con số MỚI NHẤT. Không có nhật ký thì không trả lời được "định mức Nhơn
Trạch đổi thế nào ba tháng qua", "lần sửa trước ai bấm, dựa trên bao nhiêu mẫu" — tức là
không kiểm được việc tự hiệu chỉnh có đang học đúng hay không.

Chỉ ghi, không sửa: dòng nào cũng do code tạo bằng sudo, người dùng chỉ được đọc.
"""

from odoo import api, fields, models

from ..tools.vtracking_calibration import log_rows

KIND_SELECTION = [
    ('hub', 'Kho → điểm đầu'),
    ('leg', 'Điểm → điểm'),
    ('return', 'Về kho'),
]


class HlvVtrackingCalibrationLog(models.Model):
    _name = 'hlv.vtracking.calibration.log'
    _description = 'Nhật ký hiệu chỉnh định mức'
    _order = 'date desc, id desc'
    _rec_name = 'zone_id'

    date = fields.Date(string='Ngày', required=True, index=True,
                       default=fields.Date.context_today)
    company_id = fields.Many2one('res.company', required=True, index=True)
    zone_id = fields.Many2one('hlv.vtracking.zone', string='Cụm tuyến', required=True,
                              index=True, ondelete='cascade')
    kind = fields.Selection(KIND_SELECTION, string='Định mức', required=True)
    event = fields.Selection([
        ('computed', 'Đo lại'),
        ('applied', 'Áp dụng'),
    ], string='Sự kiện', required=True, index=True)
    norm_minutes = fields.Integer(
        string='Định mức lúc đó', aggregator='avg',
        help='Số phút cụm đang dùng TRƯỚC sự kiện này.',
    )
    measured_minutes = fields.Integer(
        string='Đo được', aggregator='avg',
        help='Trung vị các mẫu đo trong cửa sổ lấy mẫu.',
    )
    suggest_minutes = fields.Integer(
        string='Đề xuất / giá trị mới', aggregator='avg',
        help='Đo lại: đề xuất (0 = chưa đủ mẫu hoặc lệch không đáng kể). '
             'Áp dụng: giá trị đã ghi vào cụm.',
    )
    sample_count = fields.Integer(string='Số mẫu', aggregator='max')
    plan_count = fields.Integer(string='Số chuyến đã xét', aggregator='max')
    user_id = fields.Many2one('res.users', string='Người áp dụng')

    @api.model
    def _log_computed(self, zone, by_kind, plan_count):
        """Ghi một dòng cho mỗi loại định mức đã có mẫu trong lần đo này."""
        return self.sudo().create([
            dict(row, zone_id=zone.id, company_id=zone.company_id.id,
                 event='computed', plan_count=plan_count)
            for row in log_rows(by_kind)
        ])

    @api.model
    def _log_applied(self, zone, kind, old_minutes, new_minutes, measured, sample_count):
        """Ghi lần người bấm áp dụng một đề xuất: cũ -> mới, dựa trên bao nhiêu mẫu."""
        return self.sudo().create({
            'zone_id': zone.id,
            'company_id': zone.company_id.id,
            'kind': kind,
            'event': 'applied',
            'norm_minutes': old_minutes,
            'measured_minutes': measured,
            'suggest_minutes': new_minutes,
            'sample_count': sample_count,
            'user_id': self.env.user.id,
        })
