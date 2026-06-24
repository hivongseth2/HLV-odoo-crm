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

    @api.onchange('toggle_keep_description')
    def _onchange_toggle_keep_description(self):
        if self.item_ids:
            new_items = []
            for item in self.item_ids:
                vals = {
                    'line_id': item.line_id.id,
                    'name': item.name,
                    'product_qty': item.product_qty,
                    'product_uom_id': item.product_uom_id.id,
                    'keep_description': self.toggle_keep_description,
                    'keep_estimated_cost': item.keep_estimated_cost,
                }
                new_items.append((0, 0, vals))
            self.item_ids = [(5, 0, 0)] + new_items

    @api.onchange('toggle_keep_estimated_cost')
    def _onchange_toggle_keep_estimated_cost(self):
        if self.item_ids:
            new_items = []
            for item in self.item_ids:
                vals = {
                    'line_id': item.line_id.id,
                    'name': item.name,
                    'product_qty': item.product_qty,
                    'product_uom_id': item.product_uom_id.id,
                    'keep_description': item.keep_description,
                    'keep_estimated_cost': self.toggle_keep_estimated_cost,
                }
                new_items.append((0, 0, vals))
            self.item_ids = [(5, 0, 0)] + new_items

class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(default=True)
    keep_estimated_cost = fields.Boolean(default=True)
