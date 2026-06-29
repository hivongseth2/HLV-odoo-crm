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
    def _prepare_item(self, line):
        res = super(PurchaseRequestLineMakePurchaseOrder, self)._prepare_item(line)
        res['keep_description'] = True
        res['keep_estimated_cost'] = True
        if hasattr(line, 'misa_supplier_id') and line.misa_supplier_id:
            res['supplier_id'] = line.misa_supplier_id.id
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
        # Nu kA-ch hot gi_ giA (keep_estimated_cost), Odoo t chia estimated_cost.
        # Nhng ta A set estimated_cost = 0, nAn chAng ta cn ghi A li bng giA MISA
        if item.keep_estimated_cost and item.line_id:
            if hasattr(item.line_id, 'misa_price_before_tax') and item.line_id.misa_price_before_tax:
                po_line.price_unit = item.line_id.misa_price_before_tax
                po_line._compute_amount()
