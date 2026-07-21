from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    stt = fields.Char(
        string="STT",
        compute="_compute_stt",
        store=False,
        help="Số thứ tự tự động của dòng sản phẩm trong đơn mua hàng",
    )
    production_year = fields.Char(
        string="Năm sản xuất",
        help="Năm sản xuất của sản phẩm",
    )
    country_of_origin = fields.Char(
        string="Xuất xứ",
        help="Quốc gia/Nơi xuất xứ của sản phẩm",
    )

    @api.depends("order_id.order_line", "order_id.order_line.sequence", "order_id.order_line.display_type")
    def _compute_stt(self):
        for line in self:
            line.stt = False

        for order in self.mapped("order_id"):
            number = 0
            for line in order.order_line:
                if line.display_type:
                    line.stt = False
                    continue
                number += 1
                line.stt = str(number)

    def _prepare_stock_moves(self, picking):
        res = super()._prepare_stock_moves(picking)
        for re in res:
            re["production_year"] = self.production_year
            re["country_of_origin"] = self.country_of_origin
        return res

