# -*- coding: utf-8 -*-
from odoo import api, fields, models

class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    misa_line_id = fields.Char(
        string="MISA Line ID",
        index=True,
        help="ID dòng từ MISA CRM Database, dùng làm khóa định danh duy nhất 1-1 giữa MISA và Odoo. "
             "Mỗi dòng trong Yêu Cầu Mua Hàng trên MISA có một ID riêng, không phụ thuộc vào Mã Hàng.",
    )

    history_po_line_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Chọn giá từ lịch sử PO",
        domain="[('product_id', '=', product_id), ('state', 'in', ['purchase', 'done'])]",
        help="Chọn một dòng từ lịch sử mua hàng để lấy giá cho chi phí ước tính."
    )

    # --- Các trường lấy từ MISA CRM (Sale tự điền) ---
    misa_supplier_id = fields.Many2one('res.partner', string="Mã/Tên NCC (MISA)")
    sale_proposed_supplier_id = fields.Many2one('res.partner', string="NCC Sale Đề Xuất")
    misa_price_before_tax = fields.Float(string="Đơn giá trước thuế (MISA)")
    misa_price_after_tax = fields.Float(string="Đơn giá sau thuế (MISA)")
    misa_amount = fields.Float(string="Thành tiền (MISA)")
    misa_tax_amount = fields.Float(string="Thuế (MISA)")
    misa_tax_rate = fields.Float(string="% Thuế (MISA)")
    misa_discount_rate = fields.Float(string="TL chiết khấu (MISA)")
    misa_discount_amount = fields.Float(string="Tiền chiết khấu (MISA)")
    misa_stock_total = fields.Float(string="Tổng SL tồn kho (MISA)")
    misa_stock_selected = fields.Float(string="SL tồn kho đã chọn (MISA)")
    misa_stock_undelivered = fields.Float(string="SL tồn kho chưa giao (MISA)")

    @api.onchange("product_id")
    def onchange_product_id(self):
        res = super(PurchaseRequestLine, self).onchange_product_id()
        if self.product_id:
            # Ưu tiên lấy giá từ Nhà cung cấp, nếu không có thì lấy giá chuẩn (Cost)
            supplier_info = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)
            ], limit=1, order='sequence, min_qty desc, price')
            
            if supplier_info:
                self.estimated_cost = supplier_info.price
            else:
                last_po_line = self.env['purchase.order.line'].search([
                    ('product_id', '=', self.product_id.id),
                    ('state', 'in', ['purchase', 'done'])
                ], limit=1, order='create_date desc')
                
                if last_po_line:
                    self.estimated_cost = last_po_line.price_unit
                else:
                    self.estimated_cost = self.product_id.standard_price
        return res

    @api.onchange("history_po_line_id")
    def _onchange_history_po_line_id(self):
        if self.history_po_line_id:
            self.estimated_cost = self.history_po_line_id.price_unit

    def action_view_price_history(self):
        """Hiển thị lịch sử giá mua từ product.supplierinfo."""
        self.ensure_one()
        if not self.product_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lịch sử giá mua - %s' % self.product_id.display_name,
            'res_model': 'product.supplierinfo',
            'view_mode': 'list,form',
            'domain': [('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)],
            'context': dict(self.env.context, create=False),
        }
