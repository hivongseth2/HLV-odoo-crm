"""Thói quen khách và thủ tục chặn, gắn vào từng điểm trong kế hoạch.

Tách khỏi ``vtracking_plan_line.py`` vì đây là một mối quan tâm riêng và là mối quan tâm
duy nhất có quyền CHẶN kế hoạch: xe tới nơi mà chưa khai hải quan là mất trắng một lượt
chạy, hàng phải chở về.

``delivery_channel`` được **chụp lại** lúc xếp, cùng lối với địa chỉ và tiền: kênh giao đổi
sau khi kế hoạch đã chốt thì con số trên kế hoạch không được đổi sau lưng người điều phối.
"""

from odoo import api, fields, models

from ..tools.vtracking_channel import CHANNEL_LABELS, needs_company_truck


class HlvVtrackingPlanLineProfile(models.Model):
    _inherit = 'hlv.vtracking.plan.line'

    profile_id = fields.Many2one(
        related='place_id.profile_id', store=True, string='Thói quen khách', readonly=True,
    )
    procedure_required = fields.Selection(
        related='profile_id.procedure_required', store=True, index=True, readonly=True,
        string='Thủ tục trước khi giao',
    )
    procedure_ready = fields.Boolean(
        string='Thủ tục đã xong', tracking=True,
        help='Tích khi đã khai hải quan / đã đăng ký người và xe với khách. Chưa tích thì '
             'kế hoạch không xác nhận được.',
    )
    procedure_blocked = fields.Boolean(
        compute='_compute_procedure_blocked', store=True, string='Đang vướng thủ tục',
    )

    delivery_channel = fields.Selection(
        [(key, CHANNEL_LABELS[key]) for key in
         ('company', 'pickup', 'express', 'grab', 'other')],
        string='Kênh giao', readonly=True, index=True,
        help='Chụp lại lúc xếp, suy từ ô "hình thức giao hàng" trên chứng từ; ô trống thì '
             'lấy theo thói quen của khách.',
    )
    needs_truck = fields.Boolean(
        compute='_compute_needs_truck', store=True, string='Cần xe công ty',
        help='Sai nghĩa là điểm này đang chiếm một chỗ trên xe mà lẽ ra không cần — khách '
             'tự lấy, gửi CPN hoặc book Grab.',
    )
    extra_service_minutes = fields.Integer(
        related='profile_id.extra_service_minutes', store=True, readonly=True,
        string='Phút lâu hơn thường lệ',
    )
    driver_note = fields.Text(
        related='profile_id.free_note', readonly=True, string='Ghi chú cho tài xế',
    )

    @api.depends('procedure_required', 'procedure_ready')
    def _compute_procedure_blocked(self):
        for line in self:
            line.procedure_blocked = bool(
                line.procedure_required and line.procedure_required != 'none'
                and not line.procedure_ready
            )

    @api.depends('delivery_channel')
    def _compute_needs_truck(self):
        for line in self:
            line.needs_truck = needs_company_truck(line.delivery_channel)

    def _source_values(self):
        """Thêm kênh giao vào bộ giá trị chụp từ chứng từ.

        Thứ tự: ô trên chứng từ → thói quen của khách → để trống. Ô trên chứng từ thắng vì
        nó nói về CHUYẾN NÀY, còn thói quen chỉ nói về thường lệ.
        """
        values = super()._source_values()
        if not values:
            return values
        document = self.picking_id or self.sale_order_id
        channel = document._vtracking_delivery_channel() if document else ''
        values['delivery_channel'] = (
            channel or self.place_id.profile_id.delivery_method or False
        )
        return values

    def action_mark_procedure_ready(self):
        """Đánh dấu đã xong thủ tục cho các dòng đang chọn."""
        self.write({'procedure_ready': True})
        for line in self:
            line.plan_id.message_post(
                body='Đã xác nhận xong thủ tục cho %s.' % line.display_reference,
                message_type='notification',
            )
        return True
