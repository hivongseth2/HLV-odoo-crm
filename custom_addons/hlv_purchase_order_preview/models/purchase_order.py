from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def _search_by_product(self, operator, value):
        """Search purchase orders containing a specific product"""
        if not value:
            return [('id', 'in', [])]

        # Search for products matching the search term
        products = self.env['product.product'].search([
            '|',
            ('name', 'ilike', value),
            ('default_code', 'ilike', value)
        ])

        # Find purchase orders containing these products
        order_lines = self.env['purchase.order.line'].search([
            ('product_id', 'in', products.ids)
        ])

        order_ids = order_lines.mapped('order_id').ids
        return [('id', 'in', order_ids)]

    product_search = fields.Char(
        string='Tìm theo sản phẩm',
        compute='_compute_product_search',
        search='_search_by_product',
        store=False,
    )

    def _compute_product_search(self):
        for record in self:
            record.product_search = ''
