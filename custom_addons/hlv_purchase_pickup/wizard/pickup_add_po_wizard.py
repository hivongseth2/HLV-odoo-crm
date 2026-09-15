from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.pickup_line import OPEN_RUN_STATES

# Đơn đáng đi lấy là đơn đã xác nhận. Đơn nháp còn đang thương lượng, đi tới nơi mới biết
# nhà cung cấp chưa chuẩn bị gì.
SELECTABLE_PO_STATES = ('purchase', 'done')


class HlvPickupAddPoWizard(models.TransientModel):
    """Chọn đơn mua hàng để xếp vào chuyến đi nhận.

    Wizard chỉ chọn và gọi ``run.add_purchase_orders`` — việc gom đơn theo nhà cung cấp và
    tạo điểm dừng nằm ở model chuyến, để API và wizard không gom theo hai kiểu khác nhau.
    """

    _name = 'hlv.pickup.add.po.wizard'
    _description = 'Thêm đơn mua hàng vào chuyến nhận'

    run_id = fields.Many2one(
        'hlv.pickup.run', string='Chuyến', required=True,
        default=lambda self: self.env.context.get('active_id'),
    )
    partner_id = fields.Many2one('res.partner', string='Lọc theo nhà cung cấp')
    date_from = fields.Date(string='Đặt từ ngày')
    date_to = fields.Date(string='Đặt đến ngày')

    available_order_ids = fields.Many2many(
        'purchase.order', 'hlv_pickup_wizard_available_rel', 'wizard_id', 'order_id',
        compute='_compute_available_order_ids', string='Đơn chọn được',
    )
    order_ids = fields.Many2many(
        'purchase.order', 'hlv_pickup_wizard_selected_rel', 'wizard_id', 'order_id',
        string='Đơn sẽ đi lấy', domain="[('id', 'in', available_order_ids)]",
    )

    @api.depends('partner_id', 'date_from', 'date_to')
    def _compute_available_order_ids(self):
        """Đơn đã xác nhận, chưa nằm trong chuyến nào đang mở.

        Lọc "đang mở" ở đây chứ không ở domain XML: luật là đơn chưa lấy được ở chuyến cũ
        thì phải chọn lại được, viết trong domain sẽ thành một dòng không ai đọc nổi.
        """
        taken = self.env['hlv.pickup.line'].search([
            ('run_id.state', 'in', OPEN_RUN_STATES),
            ('purchase_order_id', '!=', False),
        ]).mapped('purchase_order_id').ids

        for wizard in self:
            domain = [('state', 'in', SELECTABLE_PO_STATES), ('id', 'not in', taken)]
            if wizard.partner_id:
                domain.append(('partner_id', '=', wizard.partner_id.id))
            if wizard.date_from:
                domain.append(('date_order', '>=', wizard.date_from))
            if wizard.date_to:
                domain.append(('date_order', '<=', wizard.date_to))
            wizard.available_order_ids = self.env['purchase.order'].search(domain, limit=500)

    point_preview = fields.Text(
        string='Điểm nhận sẽ dùng', compute='_compute_point_preview',
        help='Địa chỉ và điện thoại mặc định của từng nhà cung cấp trong danh sách đã chọn. '
             'Sau khi thêm vào chuyến, sửa được từng dòng ở tab Điểm nhận.',
    )

    @api.depends('order_ids')
    def _compute_point_preview(self):
        """Cho thấy trước sẽ tới đâu, gọi cho ai — TRƯỚC khi bấm thêm vào chuyến.

        Dùng ``resolve_for_partner`` chứ không phải ``find_or_create_for_partner``: hàm sau
        tạo bản ghi, mà tạo bản ghi trong compute thì chỉ cần người dùng mở wizard rồi đóng
        lại là đã sinh ra một loạt điểm rác.
        """
        Point = self.env['hlv.pickup.point']
        for wizard in self:
            seen = set()
            lines = []
            for order in wizard.order_ids:
                partner = order.partner_id
                if partner.id in seen:
                    continue
                seen.add(partner.id)
                point = Point.resolve_for_partner(partner)
                if not point:
                    lines.append('• %s → sẽ tạo điểm mới từ địa chỉ của liên hệ'
                                 % partner.display_name)
                    continue
                others = len(point.partner_id.x_pickup_point_ids) - 1 if point.partner_id else 0
                lines.append('• %s\n    %s\n    %s%s' % (
                    point.name,
                    point.address or '(chưa có địa chỉ — sẽ không hiện trên bản đồ)',
                    point.contact_phone or '(chưa có điện thoại)',
                    '  ·  công ty còn %d địa chỉ khác, đổi được ở tab Điểm nhận' % others
                    if others > 0 else '',
                ))
            wizard.point_preview = '\n'.join(lines)

    def action_add(self):
        self.ensure_one()
        if not self.order_ids:
            raise UserError('Chưa chọn đơn nào.')
        added = self.run_id.add_purchase_orders(self.order_ids)
        if not added:
            raise UserError('Các đơn đã chọn đều có sẵn trong chuyến rồi.')
        return {'type': 'ir.actions.act_window_close'}
