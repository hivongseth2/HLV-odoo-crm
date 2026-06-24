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

class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(
        compute="_compute_keep_description",
        store=True,
        readonly=False,
    )
    keep_estimated_cost = fields.Boolean(
        compute="_compute_keep_estimated_cost",
        store=True,
        readonly=False,
    )

    @api.depends('wiz_id.toggle_keep_description')
    def _compute_keep_description(self):
        for item in self:
            if item.wiz_id:
                item.keep_description = item.wiz_id.toggle_keep_description
            else:
                item.keep_description = True

    @api.depends('wiz_id.toggle_keep_estimated_cost')
    def _compute_keep_estimated_cost(self):
        for item in self:
            if item.wiz_id:
                item.keep_estimated_cost = item.wiz_id.toggle_keep_estimated_cost
            else:
                item.keep_estimated_cost = True
