from odoo import api, fields, models


class MisaInvoiceGroupedLine(models.Model):
    _name = 'misa.invoice.grouped.line'
    _description = 'Dòng hàng của 1 đơn KHÁC được xuất hóa đơn CHUNG qua đề nghị của 1 phiếu xuất kho khác'
    _order = 'fetched_at desc, order_code'

    # Ghi nhận TỰ ĐỘNG (không nhập tay như misa.invoice.customs.line) khi
    # stock_picking._misa_invoice_discover_grouped_orders đọc chi tiết dòng hàng đề nghị xuất
    # HĐ của 1 phiếu đại diện (master_picking_id) và thấy có order_code KHÁC đơn hàng của
    # chính phiếu đó — tách theo TỪNG DÒNG HÀNG (mã hàng + số lượng) vì đề nghị có thể chỉ phủ
    # 1 PHẦN giá trị của đơn hàng kia. Case thật đã gặp: phiếu KBC/OUT/11002 xuất hóa đơn
    # chung, nhưng đề nghị chỉ phủ đúng 1/3 sản phẩm của phiếu KBC/OUT/11016 (cùng đơn hàng) —
    # nếu không tách theo dòng hàng, phần ~19M còn lại của KBC/OUT/11016 sẽ bị mất dấu vết.
    master_picking_id = fields.Many2one(
        'stock.picking', string='Phiếu đại diện (có đề nghị)', required=True, ondelete='cascade', index=True,
    )
    request_refid = fields.Char(
        string='MISA Request RefID', related='master_picking_id.misa_invoice_request_refid', store=True,
    )
    invoice_no = fields.Char(string='Số hóa đơn MISA', related='master_picking_id.misa_invoice_no', store=True)
    invoice_date = fields.Date(string='Ngày hóa đơn', related='master_picking_id.misa_invoice_date', store=True)

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', ondelete='set null', index=True)
    # Giữ lại mã gốc từ MISA dù có khớp được sale.order hay không — để biết ngay khi khớp thất
    # bại thay vì mất luôn thông tin.
    order_code = fields.Char(string='Mã đơn hàng (MISA)', required=True, index=True)

    inventory_item_code = fields.Char(string='Mã hàng', required=True)
    description = fields.Char(string='Tên hàng')
    quantity = fields.Float(string='Số lượng')
    unit_price = fields.Float(string='Đơn giá (chưa VAT)')
    amount_oc = fields.Float(string='Thành tiền (chưa VAT)')
    vat_amount_oc = fields.Float(string='Tiền VAT')
    discount_amount_oc = fields.Float(string='Tiền chiết khấu')
    amount = fields.Float(
        string='Thành tiền (có VAT)', compute='_compute_amount', store=True,
        help='= amount_oc + vat_amount_oc − discount_amount_oc, dùng số này để đối soát với '
             'misa_invoice_net_actual_amount (cũng đã có VAT) của phiếu xuất kho.',
    )

    # 1 dòng hàng có thể được xuất kho THÀNH NHIỀU ĐỢT (nhiều phiếu của cùng 1 đơn bán) — tách
    # quan hệ line-picking ra bảng riêng thay vì 1 Many2one duy nhất, giống hệt kiến trúc
    # misa.invoice.customs.line/.match đã dùng cho hàng hải quan.
    match_ids = fields.One2many('misa.invoice.grouped.match', 'line_id', string='Các lượt khớp phiếu xuất kho')
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu xuất kho (gần nhất)', compute='_compute_matched_qty', store=True,
    )
    matched_qty = fields.Float(string='Số lượng đã khớp', compute='_compute_matched_qty', store=True)
    match_state = fields.Selection([
        ('pending', 'Chờ xuất kho'),
        ('partial', 'Khớp một phần'),
        ('matched', 'Đã khớp phiếu xuất kho'),
    ], string='Trạng thái khớp', default='pending', index=True, required=True)
    matched_at = fields.Datetime(string='Thời điểm khớp')
    match_note = fields.Char(string='Ghi chú khớp')

    fetched_at = fields.Datetime(string='Thời điểm ghi nhận')

    @api.depends('amount_oc', 'vat_amount_oc', 'discount_amount_oc')
    def _compute_amount(self):
        for line in self:
            line.amount = (line.amount_oc or 0.0) + (line.vat_amount_oc or 0.0) - (line.discount_amount_oc or 0.0)

    @api.depends('match_ids.quantity', 'match_ids.picking_id', 'match_ids.matched_at')
    def _compute_matched_qty(self):
        for line in self:
            line.matched_qty = sum(line.match_ids.mapped('quantity'))
            line.picking_id = line.match_ids[-1].picking_id if line.match_ids else False

    def remaining_qty(self):
        self.ensure_one()
        return max(self.quantity - self.matched_qty, 0.0)
