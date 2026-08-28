from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from .stock_picking import MISA_INVOICE_RECONCILE_GROUP

# Các action "Đánh dấu ngoại lệ" / "Gắn mã đề nghị thủ công" (cả mức phiếu lẫn mức đơn hàng) —
# tách khỏi stock_picking.py (đã quá lớn). Chỉ ghi field/mở wizard/gọi lại
# action_check_misa_invoice_status (core, vẫn nằm ở stock_picking.py) — không tự cài logic
# đối soát/khớp dòng hàng nào ở đây, an toàn để tách riêng.


class StockPickingMisaInvoiceException(models.Model):
    _inherit = 'stock.picking'

    def action_mark_misa_invoice_exception(self):
        """Mở wizard nhập lý do — dùng chung cho nút trên form (1 phiếu), bulk action trên
        list (nhiều phiếu), và nút trên drawer dashboard (1 phiếu, gọi qua doAction).

        ⚠️ Action dict dựng tay: khi gọi qua nút form (type="object") hoặc ir.actions.server,
        Odoo tự nới đủ field còn thiếu trước khi đưa cho JS. Nhưng khi JS gọi thẳng qua
        orm.call() rồi đưa kết quả cho action.doAction(), KHÔNG có bước nới đó — thiếu
        "views" sẽ làm _preprocessAction() lỗi ngay (đã gặp y hệt ở
        get_misa_invoice_order_report_action). Nên trả đủ "views" ở đây luôn để an toàn cho
        mọi đường gọi."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.exception.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_picking_ids': self.ids},
        }

    def _misa_invoice_apply_exception(self, reason, source_note=''):
        """Ghi nhận đánh dấu ngoại lệ — dùng chung cho wizard nội bộ
        (misa.invoice.exception.wizard) và hành động từ trang public /misa_sale_status.
        source_note: ghi chú thêm vào chatter (VD "trang public — mã sale NV001") để biết
        nguồn gốc thao tác khi không có res.users cụ thể để trỏ vào (public/anonymous)."""
        self.write({
            'misa_invoice_exception': True,
            'misa_invoice_exception_reason': reason,
            'misa_invoice_exception_by_id': self.env.user.id,
            'misa_invoice_exception_date': fields.Datetime.now(),
        })
        note_html = (Markup(" (%s)") % source_note) if source_note else ""
        for picking in self:
            picking.message_post(
                body=Markup("<b>Đã đánh dấu ngoại lệ xuất hóa đơn MISA%s.</b><br/>Lý do: %s")
                % (note_html, reason)
            )

    def action_unmark_misa_invoice_exception(self):
        self.write({
            'misa_invoice_exception': False,
            'misa_invoice_exception_reason': False,
            'misa_invoice_exception_by_id': False,
            'misa_invoice_exception_date': False,
        })
        self.message_post(body=Markup("Đã bỏ đánh dấu ngoại lệ xuất hóa đơn MISA."))
        return True

    def action_apply_manual_invoice_link(self, refno, source_note=''):
        """Gắn mã đề nghị MISA thủ công + kiểm tra lại theo mã đó ngay — dùng chung cho wizard
        nội bộ (misa.invoice.manual.link.wizard) và hành động từ trang public
        /misa_sale_status. Trả về dict kết quả kiểm tra (xem action_check_misa_invoice_status)
        thay vì raise khi MISA chưa xác nhận đã xuất HĐ — mã vẫn được lưu lại để lần kiểm tra
        sau (kể cả cron) tự dùng, caller tự quyết định có cảnh báo người dùng hay không."""
        self.ensure_one()
        refno = (refno or '').strip()
        if not refno:
            raise UserError("Vui lòng nhập mã đề nghị MISA.")
        self.misa_invoice_manual_refno = refno
        note_html = (Markup(" (%s)") % source_note) if source_note else ""
        self.message_post(
            body=Markup(
                "Đã gắn mã đề nghị MISA thủ công%s: <b>%s</b> (dùng khi refno tự sinh trên "
                "MISA không khớp tên phiếu)."
            ) % (note_html, refno)
        )
        results = self.action_check_misa_invoice_status()
        return results[0] if results else {}

    def action_open_misa_invoice_manual_link_wizard(self):
        """Mở wizard gắn mã đề nghị MISA thủ công cho 1 phiếu (nút form/list, hoặc gọi qua
        doAction từ drawer phiếu trên dashboard) — dùng khi sale quên ghi đúng số phiếu xuất
        kho lúc tạo đề nghị xuất HĐ trên MISA."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.manual.link.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'allowed_picking_ids': self.ids,
            },
        }

    @api.model
    def action_mark_misa_invoice_exception_for_order(self, order_id):
        """Đánh dấu ngoại lệ cho TẤT CẢ phiếu xuất kho (đã done, chưa ngoại lệ) của 1 đơn
        bán — dùng từ drawer đơn hàng, gộp chung 1 lý do cho cả nhóm thay vì phải mở từng
        phiếu riêng lẻ."""
        order = self.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return {'type': 'ir.actions.act_window_close'}
        pickings = order.misa_invoice_picking_ids.filtered(
            lambda p: p.state == 'done' and not p.misa_invoice_exception
        )
        if not pickings:
            return {'type': 'ir.actions.act_window_close'}
        return pickings.action_mark_misa_invoice_exception()

    @api.model
    def action_unmark_misa_invoice_exception_for_order(self, order_id):
        order = self.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return 0
        pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.misa_invoice_exception)
        if pickings:
            pickings.action_unmark_misa_invoice_exception()
        return len(pickings)

    @api.model
    def action_open_misa_invoice_manual_link_wizard_for_order(self, order_id):
        """Như action_open_misa_invoice_manual_link_wizard nhưng gọi từ drawer đơn hàng —
        chưa biết trước phiếu nào nên để trống picking_id, chỉ giới hạn lựa chọn trong các
        phiếu (đã done, chưa xuất HĐ) của đúng đơn hàng đang xem."""
        order = self.env['sale.order'].sudo().browse(order_id)
        picking_ids = order.misa_invoice_picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done'
            and p.misa_invoice_state != 'invoiced'
        ).ids
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.manual.link.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'allowed_picking_ids': picking_ids},
        }

    @api.model
    def get_misa_invoice_can_configure(self):
        """Cờ quyền cho trang danh sách đơn hàng độc lập (misa_order_list_page.js) — dashboard
        chính đã có sẵn field này trong get_misa_invoice_dashboard_data, nhưng trang riêng
        không tải dữ liệu dashboard nên cần 1 endpoint nhẹ riêng."""
        return self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP)
