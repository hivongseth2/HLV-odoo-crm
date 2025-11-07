# models/stock_quant_inherit.py
from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def get_qty_by_default_code_at_warehouse(self, default_code, wh_prefix=None):
        """
        Tính ON-HAND (quantity) theo kho có code = wh_prefix (TSN/KBC/KHD...),
        TÌM THEO default_code:
          1) product.product.default_code
          2) product.template.default_code  -> cộng tồn mọi variant của template
        """
        if not default_code:
            return {"error": "Thiếu mã tham chiếu."}

        Product = self.env["product.product"]
        Template = self.env["product.template"]

        product_ids = Product.browse()
        # 1) default_code ở variant
        prod = Product.search([("default_code", "=", default_code)], limit=1)
        if prod:
            product_ids = prod
        else:
            # 2) default_code ở template
            tmpl = Template.search([("default_code", "=", default_code)], limit=1)
            if not tmpl:
                return {"error": "Không tìm thấy sản phẩm với mã tham chiếu: %s" % default_code}
            product_ids = tmpl.product_variant_ids  # cộng tất cả variant

        # Xác định location gốc của kho từ lot_stock_id
        base_loc = False
        if wh_prefix:
            wh = self.env["stock.warehouse"].search([("code", "=", wh_prefix)], limit=1)
            if not wh:
                wh = self.env["stock.warehouse"].search(
                    [("lot_stock_id.complete_name", "ilike", wh_prefix + "/%")], limit=1
                )
            if wh and wh.lot_stock_id:
                base_loc = wh.lot_stock_id
            else:
                view_loc = self.env["stock.location"].search(
                    [("usage", "=", "view"), ("name", "=", wh_prefix)], limit=1
                )
                if not view_loc:
                    view_loc = self.env["stock.location"].search(
                        [("usage", "=", "view"),
                         ("complete_name", "ilike", wh_prefix + "/%")], limit=1
                    )
                if view_loc:
                    base_loc = self.env["stock.location"].search(
                        [("usage", "=", "internal"), ("id", "child_of", view_loc.id)], limit=1
                    )

        domain = [("product_id", "in", product_ids.ids)]
        if base_loc:
            domain.append(("location_id", "child_of", base_loc.id))
        else:
            domain.append(("location_id.usage", "=", "internal"))

        quants = self.sudo().search(domain)
        qty_on_hand = sum(quants.mapped("quantity"))

        # Lấy UoM hiển thị (lấy của variant đầu tiên)
        uom_name = (product_ids[:1].uom_id.name) if product_ids else ""

        return {
            "default_code": default_code,
            "qty": qty_on_hand,
            "uom": uom_name,
            "warehouse_prefix": wh_prefix,
            "base_location": base_loc.complete_name if base_loc else None,
        }
