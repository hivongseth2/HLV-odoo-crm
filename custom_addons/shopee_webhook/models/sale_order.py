# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_order_status = fields.Char(string='Shopee Order Status', help="Status received from Shopee Webhook (e.g. PROCESSED, COMPLETED)")

    def write(self, vals):
        # Notify warehouse TSN if shopee_order_status changes to CANCELLED
        status = vals.get('shopee_order_status')
        if status:
            # Check both mapped and unmapped status
            is_cancelled = False
            if status in ['CANCELLED', 'Đã hủy', 'Đã Hủy']:
                is_cancelled = True
            
            if is_cancelled:
                for order in self:
                    if order.shopee_order_status not in ['CANCELLED', 'Đã hủy', 'Đã Hủy']:
                        try:
                            order._notify_warehouse_tsn()
                        except Exception as e:
                            import logging
                            _logger = logging.getLogger(__name__)
                            _logger.error("Failed to notify TSN warehouse for order %s: %s", order.name, str(e))
        
        return super(SaleOrder, self).write(vals)

    def _notify_warehouse_tsn(self):
        """
        Gửi tin nhắn Zalo cho thủ kho TSN dựa trên cấu hình trong cancellation requests.
        """
        self.ensure_one()
        # 1. Lấy mapping từ config parameter
        Config = self.env['ir.config_parameter'].sudo()
        mapping_str = Config.get_param('hlv_order_cancel_request.warehouse_zalo_mapping', '')
        
        if not mapping_str:
            return

        # 2. Parse mapping string (Format: TSN:123456|KBC:789012,111222|TSNSR:333444)
        tsn_uids = []
        try:
            parts = mapping_str.split('|')
            for part in parts:
                if ':' in part:
                    warehouse_code, uids = part.split(':', 1)
                    if warehouse_code.strip().upper() == 'TSN':
                        tsn_uids = [u.strip() for u in uids.split(',') if u.strip()]
                        break
        except Exception:
            return

        if not tsn_uids:
            return

        # 3. Xây dựng tin nhắn
        msg = f"⚠️ ĐƠN SHOPEE ĐÃ HỦY - TSN NGỪNG ĐÓNG GÓI\n"
        msg += f"• Đơn Odoo: {self.name}\n"
        msg += f"• Shopee Ref: {self.shopee_order_ref or '?'}\n"
        msg += f"• Khách hàng: {self.partner_id.name}\n"
        msg += f"• Trạng thái: {self.shopee_order_status}\n"
        msg += f"• Vui lòng kiểm tra và xử lý."

        # 4. Gửi qua hlv_zalo_zns
        try:
            zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
            if not zalo_config:
                return
            
            for uid in tsn_uids:
                try:
                    zalo_config.send_notification_message(uid, msg)
                except Exception:
                    pass
        except Exception:
            pass
