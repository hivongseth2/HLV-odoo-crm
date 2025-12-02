from odoo import models, fields, api
import unicodedata


def normalize_vietnamese(text):
    """Normalize Vietnamese text for exact comparison including diacritics"""
    if not text:
        return ''
    # Normalize to NFC form (composed characters)
    return unicodedata.normalize('NFC', text.lower())


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

    @api.model
    def search_supplier_exact(self, search_term, additional_domain=None):
        """
        Search purchase orders by supplier name with exact Vietnamese diacritic matching.
        Returns list of order IDs that match the search term exactly (including diacritics).
        """
        if not search_term:
            return []

        search_normalized = normalize_vietnamese(search_term)

        # First get candidates using ilike (faster DB query)
        base_domain = [('partner_id.name', 'ilike', search_term)]
        if additional_domain:
            base_domain = base_domain + additional_domain

        candidates = self.search(base_domain)

        # Filter in Python for exact diacritic match
        matching_ids = []
        for order in candidates:
            partner_name = order.partner_id.name or ''
            partner_normalized = normalize_vietnamese(partner_name)
            if search_normalized in partner_normalized:
                matching_ids.append(order.id)

        return matching_ids
