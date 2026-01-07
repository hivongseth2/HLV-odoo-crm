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
    def get_products_stock(self, product_ids, warehouse_id=None, session_id=None):
        """
        Lấy tồn kho thực tế của danh sách sản phẩm tại địa điểm bán hàng của POS.
        Sử dụng session_id để xác định chính xác cấu hình của quầy đang mở.
        """
        import logging
        import time
        _logger = logging.getLogger(__name__)
        req_id = int(time.time() * 1000) % 10000
        
        user_name = self.env.user.name
        _logger.info(f"[POS-STK-{req_id}] START check products: {product_ids} | User: {user_name} (ID: {self.env.user.id}) | Session Parm: {session_id}")
        
        res = {}
        if not product_ids:
            _logger.warning(f"[POS-STK-{req_id}] No products provided")
            return res

        # Xác định session
        session = False
        if session_id:
            session = self.env['pos.session'].sudo().browse(session_id)
            if not session.exists():
                _logger.warning(f"[POS-STK-{req_id}] Session ID {session_id} provided but DOES NOT EXIST")
                session = False
        
        # Fallback tìm session đang mở của user hiện tại
        if not session:
            _logger.info(f"[POS-STK-{req_id}] Fallback search for opened session of {user_name}")
            session = self.env['pos.session'].search([
                ('state', '=', 'opened'),
                ('user_id', '=', self.env.user.id)
            ], limit=1)
        
        location_id = False
        if session and session.config_id:
            _logger.info(f"[POS-STK-{req_id}] Using Session: {session.name} (Config: {session.config_id.name})")
            if session.config_id.picking_type_id and session.config_id.picking_type_id.default_location_src_id:
                location_id = session.config_id.picking_type_id.default_location_src_id.id
                _logger.info(f"[POS-STK-{req_id}] Identified source location: {session.config_id.picking_type_id.default_location_src_id.complete_name}")
            elif not warehouse_id and session.config_id.picking_type_id:
                warehouse_id = session.config_id.picking_type_id.warehouse_id.id
                _logger.info(f"[POS-STK-{req_id}] No specific location, fallback to warehouse: {session.config_id.picking_type_id.warehouse_id.name}")
        
        domain = [('product_id', 'in', product_ids)]
        
        if location_id:
            domain.append(('location_id', 'child_of', location_id))
        elif warehouse_id:
            domain.append(('location_id.warehouse_id', '=', warehouse_id))
            domain.append(('location_id.usage', '=', 'internal'))
        else:
            _logger.error(f"[POS-STK-{req_id}] CRITICAL: Could not identify warehouse or location")
            return res
            
        quants = self.env['stock.quant'].sudo().search(domain)
        _logger.info(f"[POS-STK-{req_id}] Found {len(quants)} quants in DB")
        
        for product_id in product_ids:
            product_quants = quants.filtered(lambda q: q.product_id.id == product_id)
            qty = sum(product_quants.mapped('quantity'))
            res[product_id] = qty
            # Get product name for log
            p_name = self.env['product.product'].sudo().browse(product_id).display_name
            _logger.info(f"[POS-STK-{req_id}] Product: {p_name} (ID: {product_id}) -> Qty: {qty}")
            
        _logger.info(f"[POS-STK-{req_id}] FINISH check products")
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
