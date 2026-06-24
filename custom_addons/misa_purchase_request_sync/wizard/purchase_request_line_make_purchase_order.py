from odoo import api, fields, models

class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    supplier_id = fields.Many2one(required=False)

    toggle_keep_description = fields.Boolean(
        string="Giữ Mô tả (Tất cả)",
        default=True,
        help="Bật để tất cả các dòng bên dưới đều lấy mô tả từ Yêu cầu mua hàng"
    )
    toggle_keep_estimated_cost = fields.Boolean(
        string="Giữ Giá (Tất cả)",
        default=True,
        help="Bật để tất cả các dòng bên dưới đều lấy giá dự trù làm giá mua"
    )

    @api.model
    def _prepare_item(self, line):
        res = super(PurchaseRequestLineMakePurchaseOrder, self)._prepare_item(line)
        # Mặc định bật 2 cờ này khi mở popup tạo mới
        res['keep_description'] = True
        res['keep_estimated_cost'] = True
        return res

    @api.onchange('toggle_keep_description')
    def _onchange_toggle_keep_description(self):
        if self.item_ids:
            commands = [(1, item.id, {'keep_description': self.toggle_keep_description}) for item in self.item_ids]
            self.item_ids = commands

    @api.onchange('toggle_keep_estimated_cost')
    def _onchange_toggle_keep_estimated_cost(self):
        if self.item_ids:
            commands = [(1, item.id, {'keep_estimated_cost': self.toggle_keep_estimated_cost}) for item in self.item_ids]
            self.item_ids = commands
