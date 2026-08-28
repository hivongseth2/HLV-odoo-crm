from odoo import api, fields, models


class MisaInvoiceReminder(models.Model):
    _name = 'misa.invoice.reminder'
    _description = 'Nhắc nhở xuất hóa đơn MISA'
    _order = 'create_date desc'

    # Khóa để tra "chuông thông báo" trên /misa_sale_status — nhắc theo MÃ SALE (không phải
    # theo user đăng nhập, vì 1 mã sale có thể được nhiều tài khoản cùng xem qua
    # res.users.x_misa_saler_codes) khớp với sale.order.x_studio_misa_saler_code lúc tạo nhắc.
    saler_code = fields.Char(required=True, index=True)
    order_id = fields.Many2one('sale.order', string='Đơn hàng', ondelete='cascade', index=True)
    # Snapshot tên đơn — vẫn hiển thị được trong lịch sử nhắc nhở kể cả khi order_id bị xóa.
    order_name = fields.Char(string='Mã đơn hàng')
    picking_ids = fields.Many2many('stock.picking', string='Phiếu xuất kho liên quan')
    picking_names = fields.Char(string='Tên phiếu', compute='_compute_picking_names', store=True)
    message = fields.Text(string='Ghi chú')
    created_by_id = fields.Many2one('res.users', string='Người nhắc', default=lambda self: self.env.user)
    is_read = fields.Boolean(string='Đã xem', default=False, index=True)
    read_at = fields.Datetime(string='Đã xem lúc')

    @api.depends('picking_ids.name')
    def _compute_picking_names(self):
        for rec in self:
            rec.picking_names = ', '.join(rec.picking_ids.mapped('name'))
