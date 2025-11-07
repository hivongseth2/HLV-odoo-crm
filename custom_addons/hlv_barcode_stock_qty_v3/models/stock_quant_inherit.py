# models/stock_quant_inherit.py
from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _get_base_location_by_prefix(self, prefix):
        """Trả về location gốc của kho theo prefix (TSN/KBC/KHD).
        Ưu tiên warehouse.code == prefix -> lot_stock_id.
        Fallback: tìm internal location có complete_name bắt đầu bằng '<prefix>/Stock' hoặc '<prefix>/Tồn kho' (kể cả tiếng Việt)."""
        if not prefix:
            return False

        # 1) Ưu tiên kho theo code
        wh = self.env['stock.warehouse'].search([('code', '=', prefix)], limit=1)
        if wh and wh.lot_stock_id:
            return wh.lot_stock_id

        # 2) Fallback: tìm internal dưới prefix + 'Stock' hoặc 'Tồn kho'
        Location = self.env['stock.location']
        for key in ('Stock', 'Tồn kho'):
            loc = Location.search([
                ('usage', '=', 'internal'),
                ('complete_name', 'ilike', prefix + '/' + key + '%'),
            ], order='id', limit=1)
            if loc:
                return loc

        # 3) Fallback cuối: lấy bất kỳ internal con dưới view location prefix
        view_loc = self.env['stock.location'].search([
            ('usage', '=', 'view'),
            ('name', '=', prefix)
        ], limit=1)
        if not view_loc:
            view_loc = self.env['stock.location'].search([
                ('usage', '=', 'view'),
                ('complete_name', 'ilike', prefix + '/%')
            ], limit=1)
        if view_loc:
            loc = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('id', 'child_of', view_loc.id)
            ], order='id', limit=1)
            if loc:
                return loc
        return False

    @api.model
    def get_qty_by_default_code_at_warehouse(self, default_code, wh_prefix=None):
        """ON-HAND (quantity, gồm reserved) theo kho TSN/KBC/KHD. Tìm theo default_code (variant hoặc template)."""
        if not default_code:
            return {"error": "Thiếu mã tham chiếu."}

        Product = self.env['product.product']
        Template = self.env['product.template']

        prod = Product.search([('default_code', '=', default_code)], limit=1)
        if prod:
            products = prod
        else:
            tmpl = Template.search([('default_code', '=', default_code)], limit=1)
            if not tmpl:
                return {"error": "Không tìm thấy sản phẩm với mã tham chiếu: %s" % default_code}
            products = tmpl.product_variant_ids  # cộng mọi biến thể

        base_loc = self._get_base_location_by_prefix(wh_prefix)

        domain = [('product_id', 'in', products.ids)]
        if base_loc:
            domain.append(('location_id', 'child_of', base_loc.id))
        else:
            domain.append(('location_id.usage', '=', 'internal'))

        quants = self.sudo().search(domain)
        qty_on_hand = sum(quants.mapped('quantity'))  # Số lượng hiện có

        return {
            "default_code": default_code,
            "qty": qty_on_hand,
            "uom": (products[:1].uom_id.name if products else ''),
            "warehouse_prefix": wh_prefix,
            "base_location": (base_loc.complete_name if base_loc else None),
        }
