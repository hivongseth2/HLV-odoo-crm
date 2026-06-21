# -*- coding: utf-8 -*-
from odoo import models, api


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _load_pos_data_domain(self, data):
        domain = [('usage', '=', 'internal'), ('active', '=', True)]
        config_data = data.get('pos.config', {}).get('data') or []
        config_id = config_data and config_data[0].get('id')
        if config_id:
            config = self.env['pos.config'].sudo().browse(config_id).exists()
            warehouse = config.picking_type_id.warehouse_id if config and config.picking_type_id else False
            root_location = warehouse and (warehouse.view_location_id or warehouse.lot_stock_id)
            if root_location:
                domain.append(('id', 'child_of', root_location.id))
            else:
                domain.append(('id', '=', 0))
        return domain

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['id', 'name', 'complete_name', 'display_name', 'usage', 'location_id']