from odoo import fields, models


class MisaInvoiceCustomsMatch(models.Model):
    _name = 'misa.invoice.customs.match'
    _description = 'Lượt khớp 1 dòng hải quan với 1 phiếu xuất kho (hỗ trợ xuất kho nhiều đợt)'
    _order = 'matched_at'

    # 1 dòng hải quan (đơn hàng + mã hàng, số lượng ghi trên hóa đơn) có thể được xuất kho
    # THÀNH NHIỀU ĐỢT (nhiều phiếu), nên tách quan hệ line-picking ra bảng riêng thay vì giữ
    # 1 Many2one duy nhất trên dòng hải quan — mỗi lượt khớp ghi rõ phiếu nào đóng góp bao
    # nhiêu số lượng, để cộng dồn ra matched_qty và biết khi nào đã khớp đủ.
    line_id = fields.Many2one(
        'misa.invoice.customs.line', string='Dòng hải quan', required=True, ondelete='cascade', index=True,
    )
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True, ondelete='cascade', index=True)
    quantity = fields.Float(string='Số lượng khớp từ phiếu này', required=True)
    # Tiền quy đổi từ quantity (tỷ lệ theo unit_price của dòng hải quan) — dùng để cộng dồn
    # đúng số tiền quy cho TỪNG phiếu khi 1 dòng hải quan bị chia xuất kho nhiều đợt, tránh
    # tính trùng toàn bộ amount của dòng cho mỗi phiếu.
    amount = fields.Float(string='Thành tiền quy cho phiếu này')
    is_manual = fields.Boolean(
        string='Gán thủ công', default=False,
        help='True nếu người dùng tự chọn phiếu này (khi hệ thống tự động khớp sai hoặc khớp thiếu), '
             'False nếu do cron/hệ thống tự tìm và khớp.',
    )
    matched_by_id = fields.Many2one('res.users', string='Người khớp')
    matched_at = fields.Datetime(string='Thời điểm khớp')
