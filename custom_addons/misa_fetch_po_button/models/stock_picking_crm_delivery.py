# -*- coding: utf-8 -*-
"""
Stock Picking CRM Delivery Integration
Khi picking xuất kho (OUT) được validate và có checkbox x_studio_crm_elivery = True,
tự động tạo tuyến vận chuyển trên MISA CRM và cập nhật vào Sale Order MISA.
"""
import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class StockPickingCrmDelivery(models.Model):
    _inherit = 'stock.picking'

    x_misa_shipping_address = fields.Char(
        string='MISA Shipping Address',
        related='sale_id.misa_shipping_address',
        readonly=True,
        store=True,
        index=True,
    )

    def button_validate(self):
        """
        Override button_validate để gọi MISA CRM Delivery sync
        khi picking OUT được hoàn thành và có checkbox x_studio_crm_elivery = True
        """
        res = super().button_validate()
        
        # Sau khi validate, xử lý sync CRM delivery cho các picking đã done
        for picking in self:
            if picking.state == 'done' and picking.picking_type_code == 'outgoing':
                try:
                    picking._sync_crm_delivery_route()
                except Exception as e:
                    # Log lỗi nhưng không block việc validate
                    _logger.exception(
                        "❌ [CRM DELIVERY] Error syncing shipping route for picking %s: %s",
                        picking.name, e
                    )
        
        return res

    def _sync_crm_delivery_route(self):
        """
        Đồng bộ tuyến vận chuyển tới MISA CRM.
        
        Logic:
        1. Tìm sale.order liên kết (qua origin)
        2. Kiểm tra x_studio_crm_elivery == True
        3. Kiểm tra sale_order có misa_id
        4. Gọi create_shipping_route_misa() để tạo tuyến mới
        5. Gọi update_sale_order_shipping_route() để cập nhật SO MISA
        """
        self.ensure_one()
        
        # 1. Tìm sale.order liên kết
        if not self.origin:
            _logger.debug("[CRM DELIVERY] Picking %s: Không có origin, bỏ qua", self.name)
            return
        
        sale_order = self.env['sale.order'].search([
            ('name', '=', self.origin)
        ], limit=1)
        
        if not sale_order:
            _logger.debug("[CRM DELIVERY] Picking %s: Không tìm thấy Sale Order với origin=%s", 
                         self.name, self.origin)
            return
        
        # 2. Kiểm tra checkbox x_studio_crm_elivery
        crm_delivery_enabled = getattr(sale_order, 'x_studio_crm_elivery', False)
        if not crm_delivery_enabled:
            _logger.debug("[CRM DELIVERY] Picking %s: SO %s có x_studio_crm_elivery = False, bỏ qua",
                         self.name, sale_order.name)
            return
        
        # 3. Kiểm tra sale_order có misa_id
        misa_sale_order_id = getattr(sale_order, 'misa_id', None)
        if not misa_sale_order_id:
            _logger.warning(
                "⚠️ [CRM DELIVERY] Picking %s: SO %s có x_studio_crm_elivery=True nhưng không có misa_id",
                self.name, sale_order.name
            )
            return
        
        _logger.info(
            "🚀 [CRM DELIVERY] Bắt đầu sync tuyến vận chuyển cho Picking %s (SO: %s, MISA ID: %s)",
            self.name, sale_order.name, misa_sale_order_id
        )
        
        # 4. Tạo tuyến vận chuyển trên MISA
        MisaApiUtils = self.env['misa.api.utils']
        
        try:
            # ShippingRouteCode = picking.name, ShippingRouteName = sale_order.name
            shipping_route_id = MisaApiUtils.create_shipping_route_misa(
                code=self.name,
                name=sale_order.name
                # owner_id uses default value (59)
            )
            
            if not shipping_route_id:
                _logger.error("❌ [CRM DELIVERY] Không nhận được ShippingRouteID từ MISA")
                return
            
            _logger.info(
                "✅ [CRM DELIVERY] Đã tạo Shipping Route: ID=%s, Code=%s, Name=%s",
                shipping_route_id, self.name, sale_order.name
            )
            
        except Exception as e:
            _logger.error("❌ [CRM DELIVERY] Lỗi tạo Shipping Route: %s", e)
            raise e
        
        # 5. Cập nhật ShippingRouteID vào Sale Order MISA
        try:
            success = MisaApiUtils.update_sale_order_shipping_route(
                misa_sale_order_id=misa_sale_order_id,
                shipping_route_id=shipping_route_id,
                shipping_route_name=sale_order.name  # Tên tuyến = mã đơn hàng
            )
            
            if success:
                _logger.info(
                    "✅ [CRM DELIVERY] Đã cập nhật MISA Sale Order %s với ShippingRouteID=%s",
                    misa_sale_order_id, shipping_route_id
                )
            else:
                _logger.warning(
                    "⚠️ [CRM DELIVERY] Không thể cập nhật MISA Sale Order %s với ShippingRouteID=%s",
                    misa_sale_order_id, shipping_route_id
                )
                
        except Exception as e:
            _logger.error("❌ [CRM DELIVERY] Lỗi cập nhật Sale Order MISA: %s", e)
            # Không raise để không block, đã tạo được ShippingRoute rồi
