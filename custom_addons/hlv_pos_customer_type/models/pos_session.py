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
    def _loader_params_pos_config(self):
        result = super()._loader_params_pos_config()
        result['search_params']['fields'].append('warehouse_id')
        return result

    @api.model
    def get_products_stock(self, product_ids, warehouse_id):
        """
        Lấy tồn kho thực tế của danh sách sản phẩm tại một kho cụ thể.
        Trả về dict {product_id: qty}
        """
        res = {}
        if not product_ids or not warehouse_id:
            return res
            
        # Tìm tất cả quants của các sản phẩm này tại kho (bao gồm các location con)
        domain = [
            ('product_id', 'in', product_ids),
            ('location_id.warehouse_id', '=', warehouse_id),
            ('location_id.usage', '=', 'internal')
        ]
        quants = self.env['stock.quant'].sudo().search(domain)
        
        for product_id in product_ids:
            product_quants = quants.filtered(lambda q: q.product_id.id == product_id)
            res[product_id] = sum(product_quants.mapped('quantity'))
            
        return res

    @api.model
    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        result['search_params']['fields'].extend(['qty_available', 'type', 'detailed_type'])
        return result

    @api.model
    def _loader_params_res_partner(self):
        result = super()._loader_params_res_partner()
        result['search_params']['domain'].append(('parent_id', '=', False))
        return result
