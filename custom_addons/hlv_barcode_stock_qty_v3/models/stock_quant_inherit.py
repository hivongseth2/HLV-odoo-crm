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
    
    
    @api.model
    def check_barcode_availability(self, barcode, wh_prefix=None, location_id=None):
        """
        Check tồn kho.
        - Ưu tiên check tại location_id cụ thể (nếu JS gửi lên).
        - Nếu không có location_id, check theo wh_prefix (toàn kho).
        """
        if not barcode:
            return {'allow': True}

        # 1. Tìm Product
        Product = self.env["product.product"]
        product = Product.search([("barcode", "=", barcode)], limit=1)
        if not product:
            product = Product.search([("default_code", "=", barcode)], limit=1)
        
        # Nếu quét mã lạ (không phải sp), cho qua
        if not product:
            return {'allow': True}

        # 2. XÁC ĐỊNH PHẠM VI CHECK (Scope)
        domain = [("product_id", "=", product.id), ("quantity", ">", 0)]
        scope_name = ""

        # Ưu tiên 1: Check chính xác tại vị trí nguồn (VD: Tủ 3)
        if location_id:
            loc = self.env['stock.location'].browse(location_id)
            if loc.usage == 'internal':
                domain.append(("location_id", "child_of", location_id))
                scope_name = loc.display_name
        
        # Ưu tiên 2: Check theo Prefix Kho (VD: KBC)
        if not scope_name and wh_prefix:
            base_loc = self._get_base_location_by_prefix(wh_prefix)
            if base_loc:
                domain.append(("location_id", "child_of", base_loc.id))
                scope_name = base_loc.display_name
        
        # LỖI: Nếu không xác định được phạm vi nào -> CHẶN LUÔN
        if not scope_name:
            return {
                'allow': False, # <--- ĐỔI TỪ TRUE SANG FALSE
                'message': "❌ LỖI: Không xác định được kho/vị trí hiện tại.\nJS gửi lên: Prefix=%s, LocID=%s" % (wh_prefix, location_id)
            }

        # 3. CHECK TỒN KHO
        quants = self.sudo().search(domain)
        total_qty = sum(quants.mapped("quantity"))

        if total_qty > 0:
            return {'allow': True}

        # 4. HẾT HÀNG -> GỢI Ý
        msg = "⛔ KHÔNG CÓ HÀNG TẠI: %s\n📦 SP: %s" % (scope_name, product.display_name)
        
        # Tìm gợi ý ở chỗ khác (Toàn hệ thống nội bộ)
        alt_quants = self.sudo().search([
            ("product_id", "=", product.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ], order="quantity desc", limit=5)

        if alt_quants:
            msg += "\n\n💡 Có thể lấy tại:"
            for q in alt_quants:
                # Bỏ qua vị trí vừa check bị fail
                if scope_name in q.location_id.display_name: continue
                msg += "\n   • %s: %s" % (q.location_id.display_name, q.quantity)
        else:
            msg += "\n\n⚠️ Hết sạch hàng trên toàn hệ thống!"

        return {'allow': False, 'message': msg}