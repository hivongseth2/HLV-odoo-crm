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
    def get_products_stock(self, product_ids, warehouse_id=None):
        """
        Lấy tồn kho thực tế của danh sách sản phẩm tại địa điểm bán hàng của POS.
        Ưu tiên lấy đúng location (Stock Location) của quầy bán hàng.
        """
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(f"DEBUG: get_products_stock called - products: {product_ids}")
        
        res = {}
        if not product_ids:
            return res

        # Tìm session đang mở của user hiện tại để xác định location
        session = self.env['pos.session'].search([
            ('state', '=', 'opened'),
            ('user_id', '=', self.env.user.id)
        ], limit=1)
        
        location_id = False
        if session and session.config_id:
            # Ưu tiên lấy địa điểm xuất kho mặc định của POS
            if session.config_id.picking_type_id and session.config_id.picking_type_id.default_location_src_id:
                location_id = session.config_id.picking_type_id.default_location_src_id.id
                _logger.info(f"DEBUG: Identified location {location_id} from picking_type")
            # Nếu không có, lấy warehouse_id (giữ logic cũ làm fallback)
            elif not warehouse_id and session.config_id.picking_type_id:
                warehouse_id = session.config_id.picking_type_id.warehouse_id.id
        
        domain = [('product_id', 'in', product_ids)]
        
        if location_id:
            domain.append(('location_id', 'child_of', location_id))
        elif warehouse_id:
            domain.append(('location_id.warehouse_id', '=', warehouse_id))
            domain.append(('location_id.usage', '=', 'internal'))
        else:
            _logger.warning("DEBUG: Could not identify warehouse or location for stock check")
            return res
            
        # Dùng sudo để có quyền truy cập stock.quant
        quants = self.env['stock.quant'].sudo().search(domain)
        _logger.info(f"DEBUG: Found {len(quants)} quants for domain {domain}")
        
        for product_id in product_ids:
            product_quants = quants.filtered(lambda q: q.product_id.id == product_id)
            qty = sum(product_quants.mapped('quantity'))
            res[product_id] = qty
            _logger.info(f"DEBUG: Product ID {product_id} - Total Qty: {qty}")
            
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
