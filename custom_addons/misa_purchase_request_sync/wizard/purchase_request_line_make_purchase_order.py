from odoo import api, fields, models


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    supplier_id = fields.Many2one(required=False)

    toggle_keep_description = fields.Boolean(
        string="Giữ Mô tả (Tất cả)",
        default=True,
    )
    toggle_keep_estimated_cost = fields.Boolean(
        string="Giữ Giá (Tất cả)",
        default=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super(PurchaseRequestLineMakePurchaseOrder, self).default_get(fields_list)
        # Xóa trường supplier_id (Nhà cung cấp chung) để không tự động chọn,
        # tránh việc Odoo (hoặc module OCA) tự động gán tên NCC chung và ghi đè lên các dòng bên dưới.
        if 'supplier_id' in res:
            res['supplier_id'] = False
        return res

    @api.model
    def _prepare_item(self, line):
        res = super(PurchaseRequestLineMakePurchaseOrder, self)._prepare_item(line)
        res['keep_description'] = True
        res['keep_estimated_cost'] = True
        # Ưu tiên sale_proposed_supplier_id (field được set khi đồng bộ từ extension)
        # Fallback sang misa_supplier_id nếu không có
        supplier = line.sale_proposed_supplier_id if hasattr(line, 'sale_proposed_supplier_id') and line.sale_proposed_supplier_id else False
        if not supplier:
            supplier = line.misa_supplier_id if hasattr(line, 'misa_supplier_id') and line.misa_supplier_id else False
        if supplier:
            res['supplier_id'] = supplier.id
        return res

    def _reload_wizard(self):
        """Trả về action mở lại wizard hiện tại (đã lưu) để refresh giao diện."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Toggle Giữ Mô tả ──────────────────────────────────────────
    def action_toggle_description_on(self):
        """Bật Giữ Mô tả cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_description = True
        self.item_ids.write({'keep_description': True})
        return self._reload_wizard()

    def action_toggle_description_off(self):
        """Tắt Giữ Mô tả cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_description = False
        self.item_ids.write({'keep_description': False})
        return self._reload_wizard()

    # ── Toggle Giữ Giá ────────────────────────────────────────────
    def action_toggle_cost_on(self):
        """Bật Giữ Giá cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_estimated_cost = True
        self.item_ids.write({'keep_estimated_cost': True})
        return self._reload_wizard()

    def action_toggle_cost_off(self):
        """Tắt Giữ Giá cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_estimated_cost = False
        self.item_ids.write({'keep_estimated_cost': False})
        return self._reload_wizard()


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(default=True)
    keep_estimated_cost = fields.Boolean(default=True)
    misa_price_before_tax = fields.Float(
        related='line_id.misa_price_before_tax', 
        string="Đơn giá MISA", 
        readonly=True
    )

    def _post_process_po_line(self, item, po_line, new_pr_line):
        super()._post_process_po_line(item, po_line, new_pr_line)
        if item.line_id:
            # ── Cập nhật đơn giá ──
            # Ưu tiên misa_price_before_tax, fallback về estimated_cost (giá gốc Odoo)
            price = False
            if hasattr(item.line_id, 'misa_price_before_tax') and item.line_id.misa_price_before_tax:
                price = item.line_id.misa_price_before_tax
            elif item.line_id.estimated_cost:
                price = item.line_id.estimated_cost
            if price:
                po_line.price_unit = price

            # ── Cập nhật thuế ──
            if hasattr(item.line_id, 'misa_tax_rate') and item.line_id.misa_tax_rate:
                tax_rate = item.line_id.misa_tax_rate / 100.0
                Tax = po_line.env['account.tax']
                matched_tax = Tax.search([
                    ('type_tax_use', '=', 'purchase'),
                    ('amount', '=', tax_rate),
                    ('company_id', '=', po_line.company_id.id)
                ], limit=1)
                if matched_tax:
                    po_line.taxes_id = [(6, 0, [matched_tax.id])]
            # Nếu không có misa_tax_rate, giữ nguyên taxes_id mặc định (từ product/company)

            po_line._compute_amount()
