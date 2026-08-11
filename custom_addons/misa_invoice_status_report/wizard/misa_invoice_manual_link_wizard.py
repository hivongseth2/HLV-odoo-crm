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
        result = self.picking_id.action_apply_manual_invoice_link(self.manual_refno)
        if result.get('error'):
            raise UserError(
                "Đã lưu mã đề nghị nhưng kiểm tra MISA thất bại: %s\n"
                "Bấm \"Kiểm tra MISA ngay\" trên phiếu để thử lại." % result['error']
            )
        return {'type': 'ir.actions.act_window_close'}
