# -*- coding: utf-8 -*-

from odoo import models, fields, api

# Mapping Shopee status → Vietnamese label
SHOPEE_STATUS_MAP = {
    'UNPAID': 'Chờ thanh toán',
    'READY_TO_SHIP': 'Chờ lấy hàng',
    'PROCESSED': 'Đã xử lý',
    'SHIPPED': 'Đang giao hàng',
    'COMPLETED': 'Hoàn thành',
    'IN_CANCEL': 'Chờ hủy',
    'CANCELLED': 'Đã hủy',
    'INVOICE_PENDING': 'Chờ hóa đơn',
    'RETRY_SHIP': 'Giao lại',
    'PENDING': 'Đang chờ xử lý',
}

SHOPEE_STATUS_SELECTION = [(k, v) for k, v in SHOPEE_STATUS_MAP.items()]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_order_status = fields.Char(
        string='Trạng thái đơn hàng Shopee',
        help="Giá trị trạng thái đơn hàng gốc từ Shopee API",
        readonly=True,
        copy=False,
    )
    shopee_order_status_display = fields.Selection(
        selection=SHOPEE_STATUS_SELECTION,
        string='Trạng thái đơn hàng',
        compute='_compute_shopee_order_status_display',
        store=False,
        readonly=True,
    )
    shopee_delivery_status = fields.Char(
        string='Trạng thái vận chuyển Shopee',
        help="Giá trị trạng thái vận chuyển gốc từ Shopee Webhook",
        readonly=True,
        copy=False,
    )
    shopee_delivery_status_display = fields.Selection(
        selection=SHOPEE_STATUS_SELECTION,
        string='Trạng thái vận chuyển',
        compute='_compute_shopee_delivery_status_display',
        store=False,
        readonly=True,
    )

    @api.depends('shopee_order_status')
    def _compute_shopee_order_status_display(self):
        valid_keys = {k for k, _ in SHOPEE_STATUS_SELECTION}
        for order in self:
            raw = order.shopee_order_status or ''
            order.shopee_order_status_display = raw if raw in valid_keys else False

    @api.depends('shopee_delivery_status')
    def _compute_shopee_delivery_status_display(self):
        valid_keys = {k for k, _ in SHOPEE_STATUS_SELECTION}
        for order in self:
            raw = order.shopee_delivery_status or ''
            order.shopee_delivery_status_display = raw if raw in valid_keys else False

    def _shopee_send_zalo_cancel_notification(self):
        """Send Zalo notification to Warehouse Manager when Shopee order is cancelled."""
        self.ensure_one()
        # Get warehouse mapping from config (reusing logic from hlv_order_cancel_request)
        Config = self.env['ir.config_parameter'].sudo()
        warehouse_mapping = Config.get_param('hlv_order_cancel_request.warehouse_zalo_mapping')
        
        if not warehouse_mapping:
            return

        # Build message
        msg = f"⛔ ĐƠN SHOPEE ĐÃ HỦY - NGỪNG ĐÓNG GÓI\n"
        msg += f"• Đơn Odoo: {self.name}\n"
        msg += f"• Shopee SN: {self.shopee_order_ref or 'N/A'}\n"
        msg += f"• Khách hàng: {self.partner_id.name}\n"
        if self.origin:
             msg += f"• Nguồn: {self.origin}\n"
        
        # Get recipients by warehouse code (format: TSN:UID1|KBC:UID2)
        warehouse_code = self.warehouse_id.code if self.warehouse_id else False
        if not warehouse_code:
            return

        # Parse mapping: TSN:UID1,UID2|KBC:UID3
        mapping_dict = {}
        for part in warehouse_mapping.split('|'):
            if ':' in part:
                code, uids = part.split(':', 1)
                mapping_dict[code.strip().upper()] = uids.strip()

        target_uids = mapping_dict.get(warehouse_code.upper())
        if not target_uids:
            return

        # Send via hlv_zalo_zns config
        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            return

        # Clean up UID if comma separated
        uids = [u.strip() for u in target_uids.split(',') if u.strip()]
        for u in uids:
            try:
                zalo_config.send_notification_message(u, msg)
            except Exception:
                pass
