from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def _find_product_by_code(self, code):
        """Tìm product theo nhiều khóa: barcode, default_code, template.barcode"""
        if not code:
            return self.env['product.product']
        Product = self.env['product.product']
        # 1) barcode của variant
        prod = Product.search([('barcode', '=', code)], limit=1)
        if prod:
            return prod
        # 2) default_code (mã tham chiếu)
        prod = Product.search([('default_code', '=', code)], limit=1)
        if prod:
            return prod
        # 3) barcode của template
        tmpl = self.env['product.template'].search([('barcode', '=', code)], limit=1)
        if tmpl:
            # nếu template 1 variant thì lấy luôn; nhiều variant thì lấy variant đầu
            return tmpl.product_variant_id or self.env['product.product'].search(
                [('product_tmpl_id', '=', tmpl.id)], limit=1
            )
        # (tuỳ chọn) 4) bao bì có barcode -> map về product
        packaging = self.env['product.packaging'].search([('barcode', '=', code)], limit=1)
        if packaging and packaging.product_id:
            return packaging.product_id
        return Product.browse()  # rỗng

    @api.model
    def get_qty_by_barcode_at_warehouse(self, code, wh_prefix=None):
        """
        Trả ON-HAND (quantity, bao gồm reserved) theo kho có code = wh_prefix (TSN/KBC/…).
        Tìm product theo nhiều khóa: barcode / default_code / template.barcode / packaging.barcode.
        """
        product = self._find_product_by_code(code)
        if not product:
            return {"error": "Không tìm thấy sản phẩm: %s" % code}

        # Xác định location gốc của kho từ warehouse.lot_stock_id (không phụ thuộc tên Tồn kho/Stock)
        base_loc = False
        if wh_prefix:
            wh = self.env['stock.warehouse'].search([('code', '=', wh_prefix)], limit=1)
            if not wh:
                wh = self.env['stock.warehouse'].search(
                    [('lot_stock_id.complete_name', 'ilike', wh_prefix + '/%')], limit=1
                )
            if wh and wh.lot_stock_id:
                base_loc = wh.lot_stock_id
            else:
                view_loc = self.env['stock.location'].search(
                    [('usage', '=', 'view'), ('name', '=', wh_prefix)], limit=1
                )
                if not view_loc:
                    view_loc = self.env['stock.location'].search(
                        [('usage', '=', 'view'), ('complete_name', 'ilike', wh_prefix + '/%')], limit=1
                    )
                if view_loc:
                    base_loc = self.env['stock.location'].search(
                        [('usage', '=', 'internal'), ('id', 'child_of', view_loc.id)], limit=1
                    )

        domain = [('product_id', '=', product.id)]
        if base_loc:
            domain.append(('location_id', 'child_of', base_loc.id))
        else:
            domain.append(('location_id.usage', '=', 'internal'))

        quants = self.sudo().search(domain)
        qty_on_hand = sum(quants.mapped('quantity'))  # ON-HAND (bao gồm reserved)

        return {
            "product": product.display_name,
            "barcode_or_code": code,
            "qty": qty_on_hand,
            "uom": product.uom_id.name,
            "warehouse_prefix": wh_prefix,
            "base_location": base_loc.complete_name if base_loc else None,
        }
