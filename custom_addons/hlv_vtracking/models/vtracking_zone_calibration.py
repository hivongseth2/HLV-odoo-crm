"""Đề xuất định mức học từ chuyến đã chạy, và nút áp dụng.

Nửa còn thiếu của vòng đối chiếu: trước đây hệ thống đã ĐO được giờ thực tế từng điểm,
nhưng không có gì ghi ngược về định mức cụm — số trên kế hoạch cứ giữ nguyên con số đo một
lần hồi tháng 9 dù đường sá, đội xe đã đổi.

Cron chạy HẰNG NGÀY, ghi đề xuất. Không tự sửa định mức — xem lý do ở
``tools/vtracking_calibration``.
"""

from odoo import api, fields, models

from ..services.vtracking_calibration import calibrate_company
from .vtracking_calibration_log import KIND_SELECTION

# kind trong tools/vtracking_calibration -> field định mức của cụm
NORM_FIELDS = {
    'hub': 'hub_to_first_minutes',
    'leg': 'median_leg_minutes',
    'return': 'return_minutes',
}
KIND_LABELS = dict(KIND_SELECTION)


class HlvVtrackingZoneCalibration(models.Model):
    _inherit = 'hlv.vtracking.zone'

    # 0 = chưa có đề xuất (chưa đủ mẫu hoặc lệch không đáng kể).
    calib_hub_suggest = fields.Integer(string='Đề xuất kho → điểm đầu', readonly=True)
    calib_leg_suggest = fields.Integer(string='Đề xuất điểm → điểm', readonly=True)
    calib_return_suggest = fields.Integer(string='Đề xuất về kho', readonly=True)
    calib_hub_median = fields.Integer(string='Đo được: kho → điểm đầu', readonly=True)
    calib_leg_median = fields.Integer(string='Đo được: điểm → điểm', readonly=True)
    calib_return_median = fields.Integer(string='Đo được: về kho', readonly=True)
    calib_hub_count = fields.Integer(string='Số mẫu kho → điểm đầu', readonly=True)
    calib_leg_count = fields.Integer(string='Số mẫu điểm → điểm', readonly=True)
    calib_return_count = fields.Integer(string='Số mẫu về kho', readonly=True)
    calib_plan_count = fields.Integer(string='Số chuyến đã xét', readonly=True)
    calib_computed_at = fields.Datetime(string='Tính đề xuất lúc', readonly=True)
    calib_has_suggestion = fields.Boolean(
        string='Có đề xuất', readonly=True, index=True,
        help='Có ít nhất một định mức đủ mẫu và lệch đáng kể so với số đang dùng.',
    )
    calib_applied_at = fields.Datetime(string='Áp dụng lần cuối lúc', readonly=True)
    calib_applied_by_id = fields.Many2one('res.users', string='Người áp dụng', readonly=True)
    calib_applied_note = fields.Char(string='Lần áp dụng cuối', readonly=True)

    def _calibration_values(self, by_kind, plan_count, now):
        """Kết quả của ``tools.vtracking_calibration.suggestions`` cho cụm này -> values."""
        self.ensure_one()
        values = {'calib_plan_count': plan_count, 'calib_computed_at': now}
        for kind in NORM_FIELDS:
            item = by_kind.get(kind) or {}
            values['calib_%s_suggest' % kind] = item.get('suggest') or 0
            values['calib_%s_median' % kind] = item.get('median') or 0
            values['calib_%s_count' % kind] = item.get('count') or 0
        values['calib_has_suggestion'] = any(
            values['calib_%s_suggest' % kind] for kind in NORM_FIELDS
        )
        return values

    def action_apply_calibration(self):
        """Ghi các đề xuất đang có vào định mức. Loại nào chưa có đề xuất thì giữ nguyên."""
        for zone in self:
            values, changes = {}, []
            for kind, field in NORM_FIELDS.items():
                suggest = zone['calib_%s_suggest' % kind]
                if not suggest:
                    continue
                changes.append('%s %s → %s phút (%s mẫu)' % (
                    KIND_LABELS[kind], zone[field], suggest, zone['calib_%s_count' % kind],
                ))
                zone.env['hlv.vtracking.calibration.log']._log_applied(
                    zone, kind, zone[field], suggest, zone['calib_%s_median' % kind],
                    zone['calib_%s_count' % kind],
                )
                values[field] = suggest
                values['calib_%s_suggest' % kind] = 0
            if not values:
                continue
            values.update({
                'calib_has_suggestion': False,
                'calib_applied_at': fields.Datetime.now(),
                'calib_applied_by_id': self.env.user.id,
                'calib_applied_note': '; '.join(changes),
            })
            zone.write(values)
        return True

    def action_recalibrate_now(self):
        """Tính lại đề xuất ngay, không chờ cron."""
        for company in self.mapped('company_id'):
            calibrate_company(self.env, company)
        return True

    @api.model
    def _cron_calibrate_norms(self):
        """Hằng ngày: đọc chuyến đã chạy trong ``LOOKBACK_DAYS`` ngày, ghi đề xuất."""
        companies = self.sudo().search([]).mapped('company_id')
        for company in companies:
            calibrate_company(self.env, company)
        return True
