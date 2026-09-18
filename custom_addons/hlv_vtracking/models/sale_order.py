from odoo import api, fields, models

# Địa chỉ giao MISA đẩy sang. Đọc qua ``_fields`` vì module này không phụ thuộc module
# đồng bộ MISA — thiếu nó thì lùi về địa chỉ liên hệ, không được gãy.
MISA_SHIPPING_ADDRESS_FIELD = 'misa_shipping_address'


class SaleOrder(models.Model):
    """Đơn bán có thể được xếp vào kế hoạch giao từ trước khi kho soạn hàng."""

    _inherit = 'sale.order'

    vtracking_plan_line_ids = fields.One2many(
        'hlv.vtracking.plan.line', 'sale_order_id', string='Dòng kế hoạch giao',
    )
    vtracking_plan_id = fields.Many2one(
        'hlv.vtracking.plan', string='Kế hoạch giao', compute='_compute_vtracking_plan_id',
        store=True,
        help='Kế hoạch đang chứa đơn này khi chưa có phiếu xuất. Khi phiếu ra đời, dòng kế '
             'hoạch chuyển sang trỏ vào phiếu.',
    )

    @api.depends('vtracking_plan_line_ids', 'vtracking_plan_line_ids.plan_id')
    def _compute_vtracking_plan_id(self):
        for order in self:
            order.vtracking_plan_id = order.vtracking_plan_line_ids[:1].plan_id

    def _vtracking_delivery_address(self):
        """Địa chỉ giao của đơn, dùng khi CHƯA có phiếu xuất.

        Ưu tiên địa chỉ giao MISA đẩy sang: đó là nơi hàng thật sự tới, còn địa chỉ liên
        hệ của khách thường là trụ sở. Xếp đơn vào kế hoạch từ sáng (lúc kho chưa soạn
        hàng) mà lấy nhầm trụ sở thì toạ độ sai, cụm sai, và định mức thời gian sai theo.

        Khi phiếu xuất ra đời, dòng kế hoạch chuyển sang đọc địa chỉ trên phiếu.
        """
        self.ensure_one()
        if MISA_SHIPPING_ADDRESS_FIELD in self._fields:
            value = (self[MISA_SHIPPING_ADDRESS_FIELD] or '').strip()
            if value:
                return value
        shipping = self.partner_shipping_id or self.partner_id
        return (shipping.contact_address or '').replace('\n', ', ').strip(' ,')
