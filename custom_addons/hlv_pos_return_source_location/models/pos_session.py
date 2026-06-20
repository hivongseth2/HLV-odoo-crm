# -*- coding: utf-8 -*-
from odoo import models, api


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _hlv_get_pos_stock_root_location(self, session_id=None, config_id=None):
        session = self.browse()
        if session_id:
            session = self.sudo().browse(session_id).exists()
        config = session.config_id if session else self.env['pos.config'].browse()
        if not config and config_id:
            config = self.env['pos.config'].sudo().browse(config_id).exists()
        warehouse = config.picking_type_id.warehouse_id if config and config.picking_type_id else False
        if warehouse:
            return warehouse.view_location_id or warehouse.lot_stock_id
        if config and config.picking_type_id:
            return config.picking_type_id.default_location_src_id
        return self.env['stock.location']

    @api.model
    def get_product_source_locations(self, product_id, session_id=None, config_id=None):
        product = self.env['product.product'].sudo().browse(product_id).exists()
        if not product:
            return []

        root_location = self._hlv_get_pos_stock_root_location(session_id=session_id, config_id=config_id)
        domain = [
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]
        scoped_domain = list(domain)
        if root_location:
            scoped_domain.append(('location_id', 'child_of', root_location.id))

        rows = self._hlv_read_product_location_quants(scoped_domain)
        if not rows and root_location:
            rows = self._hlv_read_product_location_quants(domain)
        return rows

    @api.model
    def _hlv_read_product_location_quants(self, domain):
        grouped = self.env['stock.quant'].sudo().read_group(
            domain,
            ['quantity:sum', 'reserved_quantity:sum', 'location_id'],
            ['location_id'],
            orderby='location_id',
        )
        location_ids = [row['location_id'][0] for row in grouped if row.get('location_id')]
        locations = {loc.id: loc for loc in self.env['stock.location'].sudo().browse(location_ids)}
        result = []
        for row in grouped:
            location_value = row.get('location_id')
            if not location_value:
                continue
            location = locations.get(location_value[0])
            if not location:
                continue
            qty = row.get('quantity', 0.0) or 0.0
            reserved = row.get('reserved_quantity', 0.0) or 0.0
            available = qty - reserved
            if available <= 0:
                continue
            result.append({
                'id': location.id,
                'name': location.complete_name,
                'quantity': qty,
                'reserved_quantity': reserved,
                'available_quantity': available,
            })
        return sorted(result, key=lambda item: item['name'])
