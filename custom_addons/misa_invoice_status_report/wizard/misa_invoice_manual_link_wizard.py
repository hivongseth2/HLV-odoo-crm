from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError


class MisaInvoiceManualLinkWizard(models.TransientModel):
    _name = 'misa.invoice.manual.link.wizard'
    _description = 'Gắn mã đề nghị MISA thủ công (đánh dấu đã xuất HĐ)'

    # Trường hợp dùng: sale quên ghi đúng số phiếu xuất kho làm "refno" lúc tạo đề nghị xuất
    # hóa đơn trên MISA, khiến MISA tự sinh 1 mã đề nghị khác (VD "DN00123") không khớp tên
    # phiếu — đối soát tự động (tra theo refno = tên phiếu) sẽ không bao giờ tìm ra. Wizard
    # này cho nhập tay đúng mã đề nghị đó rồi gọi lại MISA để xác nhận thật (không tin mù).
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu xuất kho', required=True,
        domain="[('id', 'in', context.get('allowed_picking_ids', []))]",
    )
    manual_refno = fields.Char(string='Mã đề nghị MISA', required=True)

    def action_confirm(self):
        self.ensure_one()
        refno = (self.manual_refno or '').strip()
        if not refno:
            raise UserError("Vui lòng nhập mã đề nghị MISA.")
        picking = self.picking_id
        picking.misa_invoice_manual_refno = refno
        picking.message_post(
            body=Markup(
                "Đã gắn mã đề nghị MISA thủ công: <b>%s</b> (dùng khi refno tự sinh trên "
                "MISA không khớp tên phiếu)."
            ) % refno
        )
        results = picking.action_check_misa_invoice_status()
        result = results[0] if results else {}
        if result.get('error'):
            raise UserError(
                "Đã lưu mã đề nghị nhưng kiểm tra MISA thất bại: %s\n"
                "Bấm \"Kiểm tra MISA ngay\" trên phiếu để thử lại." % result['error']
            )
        return {'type': 'ir.actions.act_window_close'}
