from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    line_number = fields.Char(
        string="STT",
        compute="_compute_line_number",
    )
    origin_country_id = fields.Many2one(
        comodel_name="res.country",
        string="Xuất xứ",
        index=True,
        help="Quốc gia xuất xứ của lô hàng được mua trên dòng này.",
    )

    @api.depends("order_id.order_line.sequence", "order_id.order_line.display_type")
    def _compute_line_number(self):
        self.line_number = False
        for order in self.mapped("order_id"):
            number = 0
            for line in order.order_line:
                if line.display_type:
                    line.line_number = False
                    continue
                number += 1
                line.line_number = str(number)

    @api.constrains("origin_country_id", "product_id")
    def _check_origin_requires_tracking(self):
        invalid_lines = self.filtered(
            lambda line: line.origin_country_id
            and line.product_id
            and line.product_id.tracking == "none"
        )
        if invalid_lines:
            products = ", ".join(invalid_lines.mapped("product_id.display_name"))
            raise ValidationError(
                _(
                    "Sản phẩm có xuất xứ phải được theo dõi theo lô hoặc số sê-ri "
                    "để tồn kho không bị gộp giữa nhiều xuất xứ. Vui lòng bật theo dõi "
                    "cho sản phẩm: %(products)s",
                    products=products,
                )
            )
