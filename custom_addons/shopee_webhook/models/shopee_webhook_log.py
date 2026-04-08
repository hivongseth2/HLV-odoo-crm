# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import json
import logging

_logger = logging.getLogger(__name__)

class ShopeeWebhookLog(models.Model):
    _name = 'shopee.webhook.log'
    _description = 'Shopee Webhook Log and Queue'
    _order = 'create_date desc'

    payload = fields.Text(string='Payload', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('failed', 'Failed')
    ], string='State', default='draft', index=True)
    
    error_message = fields.Text(string='Error Message', readonly=True)
    
    # Rule 2: Whitelist fields from payload
    WHITELIST_KEYS = ['ordersn', 'order_sn', 'status', 'tracking_status', 'logistics_status', 'tracking_no', 'tracking_number', 'shop_id', 'code']

    def cron_process_webhooks(self, batch_size=100):
        """Called by ir.cron to process pending webhooks."""
        pending_logs = self.search([('state', '=', 'draft')], limit=batch_size, order='create_date asc')
        for log in pending_logs:
            log.process_webhook()

    def process_webhook(self):
        """Rule 4: Execute heavy logic in background."""
        self.ensure_one()
        try:
            data = json.loads(self.payload)
            
            # Re-implementing logic from original controller (Rule 4 conversion)
            def find_value(json_obj, key):
                if isinstance(json_obj, dict):
                    if key in json_obj:
                        return json_obj[key]
                    for k, v in json_obj.items():
                        res = find_value(v, key)
                        if res is not None: return res
                elif isinstance(json_obj, list):
                    for item in json_obj:
                        res = find_value(item, key)
                        if res is not None: return res
                return None

            ordersn = find_value(data, 'ordersn') or find_value(data, 'order_sn')
            status = find_value(data, 'status') or find_value(data, 'tracking_status') or find_value(data, 'logistics_status')
            tracking_no = find_value(data, 'tracking_no') or find_value(data, 'tracking_number')

            _logger.info("Shopee Webhook process: ordersn=%s status=%s tracking_no=%s", ordersn, status, tracking_no)

            push_code = data.get('code')
            if str(push_code) == '3' and status:
                status_mapping = {
                    'UNPAID': 'Chưa thanh toán',
                    'READY_TO_SHIP': 'Chờ lấy hàng',
                    'PROCESSED': 'Đã xử lý',
                    'SHIPPED': 'Đang giao',
                    'COMPLETED': 'Hoàn thành',
                    'IN_CANCEL': 'Chờ xác nhận hủy',
                    'CANCELLED': 'Đã hủy',
                    'RETRY_SHIP': 'Giao lại',
                    'TO_CONFIRM_RECEIVE': 'Đã nhận hàng',
                    'TO_RETURN': 'Đang trả hàng'
                }
                status = status_mapping.get(str(status).upper(), status)

            if not ordersn and not tracking_no:
                self.write({'state': 'failed', 'error_message': 'Missing identifier in payload'})
                return

            SaleOrder = self.env['sale.order'].sudo()
            orders = SaleOrder
            if ordersn:
                orders = SaleOrder.search([('shopee_order_ref', '=', ordersn)])
                _logger.info("Shopee Webhook: tìm theo shopee_order_ref=%s → %s đơn", ordersn, len(orders))
            
            if not orders and tracking_no:
                pickings = self.env['stock.picking'].sudo().search([('carrier_tracking_ref', '=', tracking_no)])
                if pickings:
                    orders = pickings.mapped('sale_id')

            # Handle Auto-Fetch (Rule 4: Safe to do complex API calls here)
            if not orders and ordersn:
                shop_id_raw = data.get('shop_id')
                if shop_id_raw:
                    shop = self.env['shopee.shop'].sudo().search([('shop_identifier', '=', str(shop_id_raw))], limit=1)
                    if shop:
                        try:
                            # Re-using services
                            from odoo.addons.shopee_order_fetch.services import shopee_api, shopee_order_builder
                            creds = shopee_api.get_credentials_from_shop(shop)
                            status_code, body, _params = shopee_api.call_order_detail(creds, ordersn)
                            if status_code == 200 and not body.get('error'):
                                order_list = body.get('response', {}).get('order_list', [])
                                if order_list:
                                    order_data = order_list[0]
                                    escrow_data = shopee_api.call_escrow_detail(creds, ordersn)
                                    with self.env.cr.savepoint():
                                        new_so = shopee_order_builder.create_order_from_data(
                                            self.env, order_data, shop, escrow_data=escrow_data
                                        )
                                        orders = new_so
                        except Exception as e:
                            _logger.error("Shopee Auto-fetch background error: %s", str(e))

            if not orders:
                self.write({'state': 'failed', 'error_message': f'Order not found: {ordersn} / {tracking_no}'})
                return

            for order in orders:
                if status:
                    # write() trên sale.order sẽ tự hủy đơn nếu status là CANCELLED
                    order.write({'shopee_order_status': status})

            self.write({'state': 'processed', 'error_message': False})

        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            _logger.exception("Error processing Shopee Webhook Log %s: %s", self.id, e)
