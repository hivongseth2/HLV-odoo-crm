# -*- coding: utf-8 -*-
from odoo import api, fields, models

class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    history_po_line_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Chọn giá từ lịch sử PO",
        domain="[('product_id', '=', product_id), ('state', 'in', ['purchase', 'done'])]",
        help="Chọn một dòng từ lịch sử mua hàng để lấy giá cho chi phí ước tính."
    )

    @api.onchange("product_id")
    def onchange_product_id(self):
        res = super(PurchaseRequestLine, self).onchange_product_id()
        if self.product_id:
            # Ưu tiên lấy giá từ Nhà cung cấp, nếu không có thì lấy giá chuẩn (Cost)
            supplier_info = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)
            ], limit=1, order='sequence, min_qty descending, price')
            
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
