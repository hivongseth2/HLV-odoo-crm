# -*- coding: utf-8 -*-
from odoo import models, api


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _load_pos_data_models(self, config_id):
        result = super()._load_pos_data_models(config_id)
        if 'pos.customer.type' not in result:
            result.append('pos.customer.type')
        return result

    @api.model
    def _loader_params_pos_config(self):
        result = super()._loader_params_pos_config()
        result['search_params']['fields'].append('warehouse_id')
        return result

    @api.model
    def get_products_stock(self, product_ids, warehouse_id=None, session_id=None, config_id=None):
        """
        Lấy tồn kho thực tế của danh sách sản phẩm tại địa điểm bán hàng của POS.
        Sử dụng session_id hoặc config_id để xác định chính xác cấu hình của quầy đang mở.
        """
        import logging
        import time
        _logger = logging.getLogger(__name__)
        req_id = int(time.time() * 1000) % 10000
        
        user_name = self.env.user.name
        _logger.info(f"[POS-STK-{req_id}] START check | Prod: {product_ids} | Session: {session_id} | Config: {config_id} | User ID: {self.env.user.id}")
        
        res = {}
        if not product_ids:
            return res

        # 1. Xác định session bằng session_id hoặc config_id
        session = False
        if session_id:
            session = self.env['pos.session'].sudo().browse(session_id).exists()
            if session:
                session = self.env['pos.session'].sudo().browse(session_id)
        
        if not session and config_id:
            # Tìm session đang mở gắn với config_id này
            session = self.env['pos.session'].sudo().search([
                ('config_id', '=', config_id),
                ('state', '=', 'opened')
            ], limit=1)
            if session:
                _logger.info(f"[POS-STK-{req_id}] Found session {session.name} from config_id {config_id}")
        
        # 2. Fallback cuối cùng nếu vẫn không thấy session (không khuyến khích)
        if not session:
            _logger.warning(f"[POS-STK-{req_id}] No explicit session/config found, using last opened session for user {user_name}")
            session = self.env['pos.session'].search([
                ('state', '=', 'opened'),
                ('user_id', '=', self.env.user.id)
            ], limit=1)
        
        # 3. Xác định Location từ session
        location_id = False
        if session and session.config_id:
            _logger.info(f"[POS-STK-{req_id}] Using Session Context: {session.name} (Config: {session.config_id.name})")
            if session.config_id.picking_type_id and session.config_id.picking_type_id.default_location_src_id:
                location_id = session.config_id.picking_type_id.default_location_src_id.id
                _logger.info(f"[POS-STK-{req_id}] Target Location: {session.config_id.picking_type_id.default_location_src_id.complete_name}")
            elif not warehouse_id and session.config_id.picking_type_id:
                warehouse_id = session.config_id.picking_type_id.warehouse_id.id
        
        # 4. Truy vấn tồn kho
        domain = [('product_id', 'in', product_ids)]
        if location_id:
            domain.append(('location_id', 'child_of', location_id))
        elif warehouse_id:
            domain.append(('location_id.warehouse_id', '=', warehouse_id))
            domain.append(('location_id.usage', '=', 'internal'))
        else:
            _logger.error(f"[POS-STK-{req_id}] FAIL: Warehouse/Location not identified")
            return res
            
        quants = self.env['stock.quant'].sudo().search(domain)
        
        for product_id in product_ids:
            product_quants = quants.filtered(lambda q: q.product_id.id == product_id)
            qty = sum(product_quants.mapped('quantity'))
            res[product_id] = qty
            
            # Log kết quả để kiểm tra
            p = self.env['product.product'].sudo().browse(product_id)
            _logger.info(f"[POS-STK-{req_id}] ID: {product_id} | Name: {p.display_name} | Qty: {qty}")
            
        _logger.info(f"[POS-STK-{req_id}] FINISH check")
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
