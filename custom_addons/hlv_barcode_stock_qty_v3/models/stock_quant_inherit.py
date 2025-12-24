# -*- coding: utf-8 -*-
from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    # ---------- helpers ----------
    def _get_base_location_by_prefix(self, prefix):
        """
        Xác định location gốc của kho theo prefix (TSN/KBC/KHD).
        ƯU TIÊN: stock.warehouse.code == prefix -> lot_stock_id.
        FALLBACK: tìm internal location có complete_name bắt đầu bằng
                  '<prefix>/Stock' hoặc '<prefix>/Tồn kho'.
        Cuối cùng: lấy bất kỳ internal dưới view location '<prefix>/'.
        """
        if not prefix:
            return False

        Warehouse = self.env['stock.warehouse']
        Location = self.env['stock.location']

        wh = Warehouse.search([('code', '=', prefix)], limit=1)
        if wh and wh.lot_stock_id:
            return wh.lot_stock_id

        # 'Stock' (EN) và 'Tồn kho' (VI)
        for key in ('Stock', 'Tồn kho'):
            loc = Location.search([
                ('usage', '=', 'internal'),
                ('complete_name', 'ilike', prefix + '/' + key + '%'),
            ], order='id', limit=1)
            if loc:
                return loc

        # fallback: view location + child_of internal
        view_loc = Location.search([
            ('usage', '=', 'view'),
            ('name', '=', prefix)
        ], limit=1)
        if not view_loc:
            view_loc = Location.search([
                ('usage', '=', 'view'),
                ('complete_name', 'ilike', prefix + '/%')
            ], limit=1)
        if view_loc:
            loc = Location.search([
                ('usage', '=', 'internal'),
                ('id', 'child_of', view_loc.id)
            ], order='id', limit=1)
            if loc:
                return loc
        return False

    # ---------- public RPC ----------
    @api.model
    def get_qty_by_default_code_at_warehouse(self, default_code, wh_prefix=None):
        """
        TÍNH 'Số lượng hiện có' (on-hand = quantity, gồm reserved) theo kho TSN/KBC/KHD.
        TÌM SẢN PHẨM CHỈ THEO default_code:
          - ưu tiên product.product.default_code
          - nếu không có: product.template.default_code -> cộng tất cả variant
        """
        if not default_code:
            return {"error": "Thiếu mã tham chiếu."}

        Product = self.env["product.product"]
        Template = self.env["product.template"]

        prod = Product.search([("default_code", "=", default_code)], limit=1)
        if prod:
            products = prod
        else:
            tmpl = Template.search([("default_code", "=", default_code)], limit=1)
            if not tmpl:
                return {"error": "Không tìm thấy sản phẩm với mã tham chiếu: %s" % default_code}
            products = tmpl.product_variant_ids  # cộng tất cả biến thể

        base_loc = self._get_base_location_by_prefix(wh_prefix)

        domain = [("product_id", "in", products.ids)]
        if base_loc:
            domain.append(("location_id", "child_of", base_loc.id))
        else:
            # nếu không đọc được prefix -> tổng internal (để vẫn có số)
            domain.append(("location_id.usage", "=", "internal"))

        quants = self.sudo().search(domain)

        # ON-HAND: dùng quantity (KHÔNG trừ reserved)
        qty_on_hand = sum(quants.mapped("quantity"))

        return {
            "default_code": default_code,
            "qty": qty_on_hand,
            "uom": (products[:1].uom_id.name if products else ""),
            "warehouse_prefix": wh_prefix,
            "base_location": (base_loc.complete_name if base_loc else None),
        }

    @api.model
    def get_alternative_locations(self, product_id, current_location_id=None):
        """
        Tìm các vị trí nội bộ khác đang có hàng (quantity > 0).
        Trả về chuỗi text gợi ý.
        """
        domain = [
            ('product_id', '=', product_id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0)
        ]
        # Trừ vị trí hiện tại đang hết hàng ra (nếu có truyền vào)
        if current_location_id:
            domain.append(('location_id', '!=', current_location_id))

        # Lấy Top 5 vị trí có nhiều hàng nhất
        quants = self.search(domain, order='quantity desc', limit=5)
        
        if not quants:
            return False

        suggestions = []
        for q in quants:
            suggestions.append("- %s: %.2f" % (q.location_id.display_name, q.quantity))
        
        return "\n".join(suggestions)