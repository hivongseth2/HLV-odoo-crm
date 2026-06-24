from odoo import api, fields, models

class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    toggle_keep_description = fields.Boolean(
        string="Giữ Mô tả cho tất cả",
        default=True,
        help="Bật để tất cả các dòng bên dưới đều lấy mô tả từ Yêu cầu mua hàng"
    )
    toggle_keep_estimated_cost = fields.Boolean(
        string="Giữ Giá dự trù cho tất cả",
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
            for item in self.item_ids:
                item.keep_description = self.toggle_keep_description

    @api.onchange('toggle_keep_estimated_cost')
    def _onchange_toggle_keep_estimated_cost(self):
        if self.item_ids:
            for item in self.item_ids:
                item.keep_estimated_cost = self.toggle_keep_estimated_cost
