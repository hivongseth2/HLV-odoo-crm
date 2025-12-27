# models/purchase_order_notification.py
import logging
from datetime import timedelta
from odoo import models, api, fields, _

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def create(self, vals):
        # Tạo PO
        po = super(PurchaseOrder, self).create(vals)

        # Kiểm tra context skip_zalo_po_create
        # (Dùng cho MISA sync: tạo PO header trước -> chưa có lines -> skip -> gọi tay sau)
        if not self.env.context.get('skip_zalo_po_create'):
            try:
                po._send_zalo_new_po_notification()
            except Exception as e:
                _logger.exception("Error triggering Zalo new PO notification for %s: %s", po.name, e)
        
        return po

    def _send_zalo_new_po_notification(self):
        """
        Gửi thông báo ZNS khi có đơn hàng mới (Draft/Purchase).
        Được gọi từ create() hoặc gọi thủ công (từ MISA sync).
        """
        for po in self:
            config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
            if not config or not config.send_on_po_create:
                continue

            # 1. Xác định recipients
            # Ưu tiên theo kho
            warehouse_code = ''
            if po.picking_type_id and po.picking_type_id.warehouse_id:
                warehouse_code = po.picking_type_id.warehouse_id.code

            recipients = config.get_recipients_for_po_create(warehouse_code)
            
            # Fallback global
            if not recipients:
                global_uid = config.po_create_recipient_user_id
                if global_uid:
                    recipients = [global_uid]

            if not recipients:
                _logger.info("Zalo PO Notification skip: No recipients configured for PO %s (WH: %s)", po.name, warehouse_code)
                continue

            # 2. Build message
            message_text = po._format_zalo_new_po_message()

            # 3. Send
            # Ensure token valid (shared token handled inside send_notification_message or get_valid_access_token)
            
            any_success = False
            for uid in recipients:
                try:
                    res = config.send_notification_message(uid, message_text)
                    if res and res.get('error') == 0:
                        any_success = True
                except Exception as e:
                    _logger.exception("Failed to send Zalo PO msg to %s: %s", uid, e)
            
            if any_success:
                _logger.info("Zalo New PO Notification sent for %s to %s", po.name, recipients)

    def _format_zalo_new_po_message(self):
        """Format tin nhắn New PO"""
        self.ensure_one()
        
        lines_info = ""
        line_count = 0
        for line in self.order_line:
            line_count += 1
            if line_count > 15:
                lines_info += "  ...\n"
                break
            
            product_name = line.product_id.name or line.name or "Sản phẩm"
            qty = line.product_qty
            uom = line.product_uom.name or ""
            lines_info += f"  • {product_name}: {qty:g} {uom}\n"

        if not lines_info:
            lines_info = "  (Chưa có sản phẩm)\n"

        wh_name = self.picking_type_id.warehouse_id.name if self.picking_type_id else "N/A"
        partner_name = self.partner_id.name if self.partner_id else "N/A"
        
        # Custom fields
        payment_term = self.x_studio_iu_kin_thanh_ton or "N/A"
        delivery_method = self.x_studio_delivery_term or "N/A"
        delivery_address = self.x_studio_ddgh or "N/A"
        expected_date = (self.date_planned + timedelta(hours=7)).strftime('%d/%m/%Y') if self.date_planned else "N/A"

        msg = (
            f"🆕 *ĐƠN MUA HÀNG MỚI*\n"
            f"--------------------\n"
            f"📦 Mã đơn: {self.name}\n"
            f"🏭 Kho: {wh_name}\n"
            f"👤 NCC: {partner_name}\n"
            f"📅 Ngày đặt: {self.date_order.strftime('%d/%m/%Y')}\n"
            f"📅 Ngày về dự kiến: {expected_date}\n"
            f"👤 Số người liên hệ của NCC: {payment_term}\n"
            f"🚚 Phương thức giao hàng: {delivery_method}\n"
            f"📍 Thông tin người nhận: {delivery_address}\n"
            f"--------------------\n"
            f"Danh sách hàng:\n"
            f"{lines_info}"
        )
        return msg
