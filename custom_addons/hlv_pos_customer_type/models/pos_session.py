# -*- coding: utf-8 -*-
from odoo import models, api


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        if 'pos.customer.type' not in result:
            result.append('pos.customer.type')
        return result

    @api.model
    def _loader_params_res_partner(self):
        result = super()._loader_params_res_partner()
        # Debug logging
        print("DEBUG: _loader_params_res_partner called")
        print(f"DEBUG: Original domain: {result.get('search_params', {}).get('domain')}")
        
        result['search_params']['domain'].append(('parent_id', '=', False))
        
        print(f"DEBUG: Modified domain: {result['search_params']['domain']}")
        return result
