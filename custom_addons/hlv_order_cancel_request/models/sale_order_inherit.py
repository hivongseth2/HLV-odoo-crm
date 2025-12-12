from odoo import models, api, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def write(self, vals):
        # Check if state is changing to 'cancel'
        # We need to capture orders that are GOING TO BE cancelled
        # orders_to_notify = self.env['sale.order']
        # if 'state' in vals and vals['state'] == 'cancel':
        #     # Identify orders that are not yet cancelled
        #     orders_to_notify = self.filtered(lambda so: so.state != 'cancel')
            
        res = super(SaleOrder, self).write(vals)

        # if orders_to_notify:
        #     for order in orders_to_notify:
        #         order._send_zalo_cancel_notification()
        
        return res

    def _send_zalo_cancel_notification(self):
        """Send Zalo notification to Warehouse Manager when order is cancelled."""
        Config = self.env['ir.config_parameter'].sudo()
        warehouse_uid = Config.get_param('hlv_order_cancel_request.warehouse_zalo_uid')
        
        if not warehouse_uid:
            return

        # Build message
        msg = f"⛔ ĐƠN HÀNG ĐÃ HỦY TRÊN ODOO - NGỪNG ĐÓNG GÓI\n"
        msg += f"• Đơn Odoo: {self.name}\n"
        msg += f"• Khách hàng: {self.partner_id.name}\n"
        if self.origin:
             msg += f"• Nguồn: {self.origin}\n"
        
        # Send via hlv_zalo_zns config
        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            return

        # Clean up UID if comma separated
        uids = [u.strip() for u in warehouse_uid.split(',') if u.strip()]
        for u in uids:
            try:
                zalo_config.send_notification_message(u, msg)
            except Exception as e:
                # Log error
                pass
