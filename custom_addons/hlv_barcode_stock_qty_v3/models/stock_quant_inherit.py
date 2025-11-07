from odoo import models, api

class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def get_qty_by_barcode_at_warehouse(self, barcode, wh_prefix=None):
        """
        Trả về on-hand (gồm cả reserved) theo 'kho chính' của 1 warehouse:
          - wh_prefix: 'TSN' / 'KBC' / 'KHD' ...
          - Lấy location gốc của kho (usage='internal') có tên là 'Tồn kho' hoặc 'Stock'
            dưới view location có name == wh_prefix, rồi cộng dồn tất cả child.
        """
        product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if not product:
            return {"error": "Không tìm thấy sản phẩm có mã vạch này."}

        # Tìm view location theo prefix (TSN/KBC/KHD)
        view_loc = None
        if wh_prefix:
            view_loc = self.env['stock.location'].search([
                ('usage', '=', 'view'),
                ('name', '=', wh_prefix)
            ], limit=1)
            if not view_loc:
                # Fallback: tìm theo complete_name bắt đầu bằng prefix
                view_loc = self.env['stock.location'].search([
                    ('usage', '=', 'view'),
                    ('complete_name', 'ilike', wh_prefix + '/%')
                ], limit=1)

        # Tìm "Tồn kho/Stock" bên dưới view_loc
        stock_loc = None
        if view_loc:
            stock_loc = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('name', 'in', ('Tồn kho', 'Stock')),
                ('id', 'child_of', view_loc.id),
            ], limit=1)

        # Nếu không tìm ra, fallback: cộng toàn bộ dưới view_loc (ít gặp)
        base_loc = stock_loc or view_loc

        domain = [('product_id', '=', product.id)]
        if base_loc:
            domain.append(('location_id', 'child_of', base_loc.id))
        else:
            # Không có prefix -> trả tổng hệ thống (on-hand) để vẫn có số
            domain.append(('location_id.usage', '=', 'internal'))

        quants = self.sudo().search(domain)

        # LẤY ON-HAND: quantity (KHÔNG trừ reserved)
        qty = sum(quants.mapped('quantity'))

        return {
            "product": product.display_name,
            "barcode": barcode,
            "qty": qty,
            "uom": product.uom_id.name,
            "warehouse_prefix": wh_prefix,
            "base_location": base_loc.complete_name if base_loc else None,
        }
