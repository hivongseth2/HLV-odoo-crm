from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .stock_picking import (
    MISA_INVOICE_CUTOFF_DEFAULT,
    MISA_INVOICE_CUTOFF_PARAM,
    MISA_INVOICE_RECONCILE_GROUP,
    MISA_INVOICE_SHOW_ADMIN_TOOLS_PARAM,
)

# Cấu hình đơn giản (mốc ngày đối soát + ẩn/hiện công cụ quản trị) tách khỏi stock_picking.py
# (đã quá lớn) — chỉ đọc/ghi ir.config_parameter, không đụng gì tới logic đối soát/khớp dòng
# hàng, an toàn để tách riêng.


class StockPickingMisaInvoiceConfig(models.Model):
    _inherit = 'stock.picking'

    def _get_misa_invoice_cutoff_date(self):
        raw = (self.env['ir.config_parameter'].sudo().get_param(MISA_INVOICE_CUTOFF_PARAM) or '').strip()
        for value in (raw, MISA_INVOICE_CUTOFF_DEFAULT):
            if not value:
                continue
            try:
                return fields.Date.from_string(value)
            except Exception:
                continue
        return fields.Date.from_string(MISA_INVOICE_CUTOFF_DEFAULT)

    @api.model
    def set_misa_invoice_cutoff_date(self, date_str):
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Bạn không có quyền thay đổi mốc đối soát MISA."))
        try:
            parsed = fields.Date.from_string(date_str)
        except Exception:
            parsed = False
        if not parsed:
            raise UserError(_("Ngày không hợp lệ: %s") % date_str)
        self.env['ir.config_parameter'].sudo().set_param(
            MISA_INVOICE_CUTOFF_PARAM, fields.Date.to_string(parsed)
        )
        return self.get_misa_invoice_dashboard_data()

    def _get_misa_invoice_show_admin_tools(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(MISA_INVOICE_SHOW_ADMIN_TOOLS_PARAM)
        return raw != '0'  # mặc định HIỆN (chưa từng lưu param) — chỉ ẩn khi đã lưu rõ '0'

    @api.model
    def set_misa_invoice_show_admin_tools(self, value):
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Bạn không có quyền thay đổi cài đặt này."))
        self.env['ir.config_parameter'].sudo().set_param(
            MISA_INVOICE_SHOW_ADMIN_TOOLS_PARAM, '1' if value else '0'
        )
        return self.get_misa_invoice_dashboard_data()
