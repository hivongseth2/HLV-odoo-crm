"""Tài xế của một kế hoạch — theo TÀI KHOẢN quét barcode, không theo đối tác Đội xe.

Mặc định lấy tài xế đang gắn với xe, nhưng sửa được theo ngày: hôm nay tài xế nghỉ, người
khác lái xe đó là chuyện thường. Sau chuyến, so với người THẬT SỰ quét nhận hàng (số thực
tế từ app shipper) để lộ ra những chuyến lệch người.
"""

from odoo import api, fields, models


class HlvVtrackingPlanDriver(models.Model):
    _inherit = 'hlv.vtracking.plan'

    driver_user_id = fields.Many2one(
        'res.users', string='Tài xế', index=True, tracking=True,
        compute='_compute_driver_user_id', store=True, readonly=False,
        help='Mặc định là tài xế gắn với xe (V-Tracking > Xe theo dõi). Đổi được cho riêng '
             'kế hoạch này mà không đổi phân công của xe.',
    )
    driver_name = fields.Char(
        related='driver_user_id.shipper_name', string='Tên shipper', readonly=True,
    )
    driver_mismatch = fields.Char(
        compute='_compute_driver_mismatch', string='Lệch tài xế',
        help='Người quét nhận hàng trong app shipper khác tài xế của kế hoạch.',
    )

    @api.depends('vehicle_id')
    def _compute_driver_user_id(self):
        """Lấy theo xe lúc chọn xe; sửa tay sau đó thì giữ nguyên.

        Cố ý CHỈ phụ thuộc ``vehicle_id``, không phụ thuộc tài xế hiện tại của xe: đổi
        phân công xe hôm nay mà kế hoạch cũ đổi theo là viết lại lịch sử — chuyến tuần trước
        bỗng thành do người khác chạy, và đối chiếu thực tế ra kết quả sai.
        """
        for plan in self:
            plan.driver_user_id = plan.vehicle_id.dispatch_driver_user_id

    @api.depends('driver_user_id', 'line_ids.shipper_id')
    def _compute_driver_mismatch(self):
        for plan in self:
            actual = plan.line_ids.mapped('shipper_id')
            others = actual - plan.driver_user_id if plan.driver_user_id else actual.browse()
            plan.driver_mismatch = (
                'Thực tế nhận hàng: %s — kế hoạch giao cho %s.' % (
                    ', '.join(user.shipper_name or user.name for user in others),
                    plan.driver_name or plan.driver_user_id.name,
                ) if others else False
            )
