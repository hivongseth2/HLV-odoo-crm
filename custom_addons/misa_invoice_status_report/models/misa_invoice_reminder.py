import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .stock_picking import MISA_INVOICE_RECONCILE_GROUP

_logger = logging.getLogger(__name__)


def _misa_invoice_reminder_bus_channel(saler_code):
    """Tên kênh bus.bus dùng chung cho gửi (action_send_misa_invoice_reminder) và nhận (JS
    trang /misa_sale_status mở WebSocket subscribe kênh này) — 1 kênh riêng cho MỖI mã sale
    (không phải theo user, vì nhiều tài khoản có thể cùng xem 1 mã qua x_misa_saler_codes).
    Payload gửi qua kênh này CHỈ là tín hiệu "có gì mới, tự tải lại" (không kèm nội dung thật
    của thông báo) — client vẫn phải gọi lại /misa_sale_status/api/reminders (có xác thực
    saler_code qua session) mới lấy được nội dung, nên biết được TÊN kênh không tự nó lộ gì."""
    return 'misa_invoice_reminder_%s' % (saler_code or '').strip().upper()


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


class StockPickingMisaInvoiceReminder(models.Model):
    """Các action/API liên quan "Nhắc nhở xuất hóa đơn" gắn trên stock.picking — tách khỏi
    stock_picking.py (đã quá lớn) sang đây, cùng file với model misa.invoice.reminder cho
    liền mạch (đọc 1 file là hiểu hết cả model lẫn cách nó được tạo/dùng).

    Nút "Nhắc xuất HĐ" (dashboard nội bộ + /misa_sale_status khi isAdmin) — CHỈ tài khoản
    thuộc nhóm Đối soát XHD được gửi (đây là hành động ADMIN/kế toán nhắc SALE, không phải
    sale tự thao tác lên dữ liệu của mình). Nhắc theo ĐƠN HÀNG là chính (misa sale order code)
    vì mục đích là nhắc "đơn này chưa xuất đủ HĐ", nhưng vẫn nhận thêm picking_ids để hỗ trợ
    nhắc nhanh 1/nhiều PHIẾU từ tab "Phiếu xuất kho" (tự suy ra đơn liên quan)."""
    _inherit = 'stock.picking'

    @api.model
    def action_send_misa_invoice_reminder(self, order_ids=None, picking_ids=None, message=False):
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError("Bạn không có quyền gửi nhắc nhở xuất hóa đơn.")

        Order = self.env['sale.order'].sudo()
        orders = Order.browse(order_ids or []).exists()
        reminded_picking_ids = set()
        if picking_ids:
            pickings = self.sudo().browse(picking_ids).exists()
            orders |= pickings.mapped('misa_invoice_sale_order_ids')
            # Highlight riêng ở mức phiếu — trường hợp chọn lẻ vài phiếu trong 1 đơn có nhiều
            # phiếu, không muốn "ăn theo" nhắc luôn các phiếu KHÁC chưa được chọn của cùng đơn.
            now = fields.Datetime.now()
            pickings.write({
                'misa_invoice_reminder_at': now,
                'misa_invoice_reminder_by_id': self.env.user.id,
            })
            reminded_picking_ids = set(pickings.ids)
        if not orders:
            raise UserError("Không tìm thấy đơn hàng nào để nhắc.")

        now = fields.Datetime.now()
        Reminder = self.env['misa.invoice.reminder'].sudo()
        Bus = self.env['bus.bus'].sudo()
        created = Reminder.browse()
        skipped_no_code = []
        notified_codes = set()
        for order in orders:
            order.write({
                'misa_invoice_reminder_at': now,
                'misa_invoice_reminder_by_id': self.env.user.id,
            })
            code = (order.x_studio_misa_saler_code or '').strip()
            if not code:
                skipped_no_code.append(order.name)
                continue
            created |= Reminder.create({
                'saler_code': code,
                'order_id': order.id,
                'order_name': order.name,
                'picking_ids': [(6, 0, order.misa_invoice_picking_ids.ids)],
                'message': message or False,
            })
            notified_codes.add(code.upper())

        # Đẩy tín hiệu real-time qua bus.bus (WebSocket) cho từng mã sale VỪA bị nhắc — chuông
        # trên /misa_sale_status subscribe kênh này để tự tải lại NGAY, không cần chờ tới lượt
        # poll định kỳ (60s, vẫn giữ làm lưới an toàn nếu WebSocket rớt/không khả dụng).
        for code in notified_codes:
            try:
                Bus._sendone(_misa_invoice_reminder_bus_channel(code), 'misa_invoice_reminder', {'saler_code': code})
            except Exception:
                _logger.exception("❌ [MISA REMINDER BUS] Lỗi gửi tín hiệu real-time cho mã sale %s", code)
        return {
            'reminded_order_count': len(orders),
            'notification_count': len(created),
            'reminded_picking_count': len(reminded_picking_ids),
            'skipped_no_saler_code': skipped_no_code,
        }

    @api.model
    def get_misa_invoice_public_reminders(self, saler_code, unread_only=True, limit=50):
        """Danh sách nhắc nhở của mã sale đang xem — dùng cho chuông thông báo trên
        /misa_sale_status. total_unread luôn tính lại riêng (không phụ thuộc limit) để hiện
        đúng số trên badge chuông kể cả khi danh sách bị cắt bớt."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        Reminder = self.env['misa.invoice.reminder'].sudo()
        domain = [('saler_code', '=', code)]
        total_unread = Reminder.search_count(domain + [('is_read', '=', False)])
        if unread_only:
            domain.append(('is_read', '=', False))
        reminders = Reminder.search(domain, order='create_date desc', limit=limit)
        return {
            'total_unread': total_unread,
            'bus_channel': _misa_invoice_reminder_bus_channel(code),
            'reminders': [{
                'id': r.id,
                'order_id': r.order_id.id if r.order_id else False,
                'order_name': r.order_name or (r.order_id.name if r.order_id else ''),
                'picking_names': r.picking_ids.mapped('name'),
                'message': r.message or '',
                'created_by': r.created_by_id.name or '',
                'create_date': fields.Datetime.to_string(r.create_date) if r.create_date else False,
                'is_read': r.is_read,
            } for r in reminders],
        }

    @api.model
    def mark_misa_invoice_reminder_read(self, saler_code, reminder_ids=None):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        Reminder = self.env['misa.invoice.reminder'].sudo()
        domain = [('saler_code', '=', code), ('is_read', '=', False)]
        if reminder_ids:
            domain.append(('id', 'in', reminder_ids))
        reminders = Reminder.search(domain)
        reminders.write({'is_read': True, 'read_at': fields.Datetime.now()})
        return {'marked': len(reminders)}
