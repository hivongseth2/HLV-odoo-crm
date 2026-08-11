from odoo import fields, models


class MisaInvoiceCustomsLine(models.Model):
    _name = 'misa.invoice.customs.line'
    _description = 'Dòng hàng đã xuất hóa đơn MISA trước khi xuất kho Odoo (hàng hải quan)'
    _order = 'fetched_at desc, invoice_no, order_code'

    # Trường hợp "hải quan": hóa đơn được lập trên MISA TRƯỚC khi phiếu xuất kho Odoo tồn
    # tại, nên không thể đối soát theo refno=tên phiếu như luồng thông thường. Ghi nhận thủ
    # công (nhập số hóa đơn, fetch 1 lần) ở mức ĐƠN HÀNG + MÃ HÀNG (không phải toàn đơn) vì
    # 1 hóa đơn có thể chỉ phủ MỘT PHẦN đơn hàng (xuất kho từng phần).
    invoice_no = fields.Char(string='Số hóa đơn MISA', required=True, index=True)
    invoice_refid = fields.Char(string='MISA Voucher RefID')
    # Số chứng từ hạch toán (khác số hóa đơn) — kế toán dùng để đối chiếu sổ sách, MISA trả
    # riêng field này (refno_finance) tách biệt với inv_no.
    refno_finance = fields.Char(string='Số chứng từ (refno_finance)')
    invoice_date = fields.Date(string='Ngày hóa đơn')
    partner_name = fields.Char(string='Khách hàng')

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', ondelete='set null', index=True)
    # Giữ lại mã gốc từ MISA dù có khớp được sale.order hay không — để biết ngay khi khớp
    # thất bại (VD sai tên đơn, đơn chưa tồn tại trong Odoo) thay vì mất luôn thông tin.
    order_code = fields.Char(string='Mã đơn hàng (MISA)', required=True, index=True)

    inventory_item_code = fields.Char(string='Mã hàng', required=True)
    description = fields.Char(string='Tên hàng')
    quantity = fields.Float(string='Số lượng')
    unit_price = fields.Float(string='Đơn giá')
    amount = fields.Float(string='Thành tiền (chưa VAT)')

    # Khi lưu, hệ thống thử tìm NGAY 1 phiếu xuất kho (đã done) khớp đơn bán + mã hàng + số
    # lượng — nếu phiếu chưa tồn tại hoặc chưa hoàn tất, dòng này ở lại 'pending' và cron định
    # kỳ (_cron_scan_misa_customs_pending) sẽ tự thử lại, không cần thao tác gì thêm.
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho khớp', ondelete='set null', index=True)
    match_state = fields.Selection([
        ('pending', 'Chờ xuất kho'),
        ('matched', 'Đã khớp phiếu xuất kho'),
    ], string='Trạng thái khớp', default='pending', index=True, required=True)
    matched_at = fields.Datetime(string='Thời điểm khớp')

    fetched_by_id = fields.Many2one('res.users', string='Người ghi nhận')
    fetched_at = fields.Datetime(string='Thời điểm ghi nhận')
