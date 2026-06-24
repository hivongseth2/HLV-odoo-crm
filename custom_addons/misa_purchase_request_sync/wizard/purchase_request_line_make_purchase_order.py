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
        return res

    def action_apply_keep_description(self):
        """Server action: Áp dụng toggle Giữ Mô tả cho tất cả dòng."""
        self.ensure_one()
        self.item_ids.write({'keep_description': self.toggle_keep_description})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply_keep_estimated_cost(self):
        """Server action: Áp dụng toggle Giữ Giá cho tất cả dòng."""
        self.ensure_one()
        self.item_ids.write({'keep_estimated_cost': self.toggle_keep_estimated_cost})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(default=True)
    keep_estimated_cost = fields.Boolean(default=True)
