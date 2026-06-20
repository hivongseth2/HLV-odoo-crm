# -*- coding: utf-8 -*-
from odoo import models, api


class StockLocation(models.Model):
    _inherit = ['stock.location', 'pos.load.mixin']

    @api.model
    def _load_pos_data_domain(self, data):
        domain = [('usage', '=', 'internal'), ('active', '=', True)]
        config_data = data.get('pos.config', {}).get('data') or []
        config_id = config_data and config_data[0].get('id')
        if config_id:
            config = self.env['pos.config'].sudo().browse(config_id).exists()
            source_location = config.picking_type_id.default_location_src_id if config else False
            if source_location:
                domain.append(('id', 'child_of', source_location.id))
        return domain

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['id', 'name', 'complete_name', 'display_name', 'usage', 'location_id']