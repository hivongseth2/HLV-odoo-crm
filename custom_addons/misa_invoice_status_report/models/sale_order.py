from odoo import fields, models


class SaleOrderMisaInvoiceStatus(models.Model):
    _inherit = 'sale.order'

    # Chiều ngược của stock.picking.misa_invoice_sale_order_ids — dùng cùng bảng quan hệ
    # để tra "đơn hàng này gắn với những phiếu xuất kho nào" cho tab Đơn hàng trên dashboard.
    misa_invoice_picking_ids = fields.Many2many(
        'stock.picking', 'misa_invoice_picking_sale_order_rel', 'order_id', 'picking_id',
        string='Phiếu xuất kho liên quan',
    )

    # Đánh dấu "đã nhắc sale xuất hóa đơn" — dùng để HIGHLIGHT đơn này trên tab Đơn hàng (cả
    # dashboard nội bộ lẫn /misa_sale_status) cho tới khi đơn được xuất HĐ đủ (xem
    # _misa_invoice_order_row: chỉ highlight khi state != 'invoiced', KHÔNG tự xóa field này để
    # còn giữ lịch sử "đã từng nhắc lúc nào, ai nhắc" — xem action_send_misa_invoice_reminder.
    misa_invoice_reminder_at = fields.Datetime(string='Lần nhắc xuất HĐ gần nhất', copy=False)
    misa_invoice_reminder_by_id = fields.Many2one('res.users', string='Người nhắc xuất HĐ', copy=False)

    # Số CHÍNH XÁC (quy đúng theo order_code qua API sống MISA, không đếm trùng khi 1 đề nghị
    # gộp chung nhiều đơn) — lấy từ _misa_invoice_compute_order_coverage_detail, lưu lại thay vì
    # tính-rồi-vứt như trước, để _misa_invoice_order_row đọc thẳng (rẻ, không cần gọi API lúc
    # render/export). shipped = tổng tiền thực xuất kho TOÀN BỘ phiếu của đơn (không lọc theo
    # ngày đang xem trên dashboard — xem giới hạn đã biết trong plan); invoiced = tổng tiền đã
    # xuất HĐ quy ĐÚNG về đơn này (không dính tiền của đơn khác dùng chung đề nghị).
    misa_invoice_exact_shipped_amount = fields.Float(string='Đã xuất kho (chính xác)', copy=False)
    misa_invoice_exact_invoiced_amount = fields.Float(string='Đã xuất HĐ (chính xác, quy đúng về đơn)', copy=False)
    misa_invoice_exact_checked_at = fields.Datetime(string='Lần tính chính xác gần nhất', copy=False)
