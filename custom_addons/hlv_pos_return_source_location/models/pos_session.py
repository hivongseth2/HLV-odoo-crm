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
        if not root_location:
            return []

        domain.append(('location_id', 'child_of', root_location.id))
        return self._hlv_read_product_location_quants(domain)

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


    @api.model
    def get_refund_source_locations(self, refunded_orderline_id, product_id=None):
        orig_line = self.env['pos.order.line'].sudo().browse(refunded_orderline_id).exists()
        if not orig_line:
            return []
        product = self.env['product.product'].sudo().browse(product_id).exists() if product_id else orig_line.product_id
        move_lines = orig_line.order_id.sudo().picking_ids.move_line_ids.filtered(
            lambda ml: ml.product_id == product and ml.quantity > 0
        )
        customer_move_lines = move_lines.filtered(lambda ml: ml.location_dest_id.usage == 'customer')
        if customer_move_lines:
            move_lines = customer_move_lines
        grouped = {}
        for move_line in move_lines:
            location = move_line.location_id
            if not location:
                continue
            grouped.setdefault(location.id, {
                'id': location.id,
                'name': location.complete_name,
                'quantity': 0.0,
            })
            grouped[location.id]['quantity'] += move_line.quantity
        return sorted(grouped.values(), key=lambda item: item['name'])
