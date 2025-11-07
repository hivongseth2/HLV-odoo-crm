# -*- coding: utf-8 -*-
from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def get_qty_by_default_code_at_warehouse(self, default_code, wh_prefix=None):
        """
        Trả về ON-HAND (quantity) của product theo kho có code = wh_prefix (TSN/KBC/KHD...),
        TÌM product CHỈ THEO default_code (mã tham chiếu).

        - default_code: mã tham chiếu (product.product.default_code).
        - wh_prefix: code của kho (stock.warehouse.code), ví dụ 'TSN', 'KBC'...
        - Lấy location gốc của kho từ warehouse.lot_stock_id, rồi cộng quantity của mọi quants con.
        """
        if not default_code:
            return {"error": "Thiếu mã tham chiếu."}

        Product = self.env["product.product"]
        product = Product.search([("default_code", "=", default_code)], limit=1)
        if not product:
            return {"error": "Không tìm thấy sản phẩm với mã tham chiếu: %s" % default_code}

        # Xác định location gốc của kho từ warehouse.lot_stock_id
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
                # Fallback: tìm view location theo prefix rồi chọn 1 internal bên dưới
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

        # Domain quants
        domain = [("product_id", "=", product.id)]
        if base_loc:
            domain.append(("location_id", "child_of", base_loc.id))
        else:
            domain.append(("location_id.usage", "=", "internal"))  # tổng internal nếu không xác định được kho

        quants = self.sudo().search(domain)

        # ON-HAND (bao gồm reserved): dùng quantity, KHÔNG dùng available_quantity
        qty_on_hand = sum(quants.mapped("quantity"))

        return {
            "product": product.display_name,
            "default_code": default_code,
            "qty": qty_on_hand,
            "uom": product.uom_id.name,
            "warehouse_prefix": wh_prefix,
            "base_location": base_loc.complete_name if base_loc else None,
        }
