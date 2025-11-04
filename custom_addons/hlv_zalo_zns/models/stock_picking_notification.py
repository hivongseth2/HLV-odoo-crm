# models/stock_picking_notification.py
import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Cờ đánh dấu đã gửi thông báo cho picking này
    zalo_stock_notification_sent = fields.Boolean('Zalo Notification Sent', default=False, copy=False)

    def _get_picking_completion_status(self):
        """
        Xác định đơn hàng được xuất/nhập toàn bộ hay một phần
        
        :return: 'toàn bộ' hoặc '1 phần'
        """
        self.ensure_one()
        
        # Kiểm tra xem có move line nào bị split (done < demand) không
        for move in self.move_ids_without_package:
            if move.product_uom_qty > 0:
                # Nếu quantity_done < quantity demanded => xuất/nhập 1 phần
                if move.quantity_done < move.product_uom_qty:
                    return '1 phần'
        
        # Kiểm tra nếu có backorder => xuất/nhập 1 phần
        if self.backorder_id:
            return '1 phần'
        
        return 'toàn bộ'

    def _format_zalo_notification_message(self):
        """
        Format tin nhắn thông báo theo yêu cầu
        Tương đương với phần build message trong PHP
        
        :return: Message text
        """
        self.ensure_one()
        
        # Xác định loại đơn
        if self.picking_type_code == 'outgoing':
            action_type = 'XUẤT'
        elif self.picking_type_code == 'incoming':
            action_type = 'NHẬP'
        else:
            action_type = self.picking_type_id.name or 'CHUYỂN'
        
        # Lấy mã đơn hàng gốc (source.origin)
        order_code = self.origin or self.name
        
        # Trạng thái xuất/nhập (toàn bộ hay 1 phần)
        completion_status = self._get_picking_completion_status()
        
        # Thời gian xuất/nhập
        done_date = self.date_done or fields.Datetime.now()
        done_date_str = fields.Datetime.context_timestamp(
            self, done_date
        ).strftime('%d/%m/%Y %H:%M:%S')
        
        # Lấy thông tin kho
        warehouse_name = ''
        if self.picking_type_id and self.picking_type_id.warehouse_id:
            warehouse_name = self.picking_type_id.warehouse_id.name or ''
        
        # Build message
        message = f"🔔 Thông báo đơn hàng {action_type}\n"
        message += "=" * 40 + "\n"
        message += f"📋 Mã đơn hàng: {order_code}\n"
        message += f"📦 Phiếu kho: {self.name}\n"
        if warehouse_name:
            message += f"🏭 Kho: {warehouse_name}\n"
        message += f"📊 Trạng thái: {action_type} {completion_status}\n"
        message += f"🕐 Thời gian: {done_date_str}\n"
        
        # Thêm thông tin partner nếu có
        if self.partner_id:
            message += f"👤 Đối tác: {self.partner_id.name}\n"
        
        # Thêm thông tin địa chỉ nếu có
        if self.picking_type_code == 'outgoing' and self.partner_id:
            # Với đơn xuất, hiển thị địa chỉ giao hàng
            partner = self._zns_get_shipping_partner() if hasattr(self, '_zns_get_shipping_partner') else self.partner_id
            if partner:
                address_parts = []
                if partner.street:
                    address_parts.append(partner.street)
                if partner.city:
                    address_parts.append(partner.city)
                if partner.state_id:
                    address_parts.append(partner.state_id.name)
                
                if address_parts:
                    address = ', '.join(address_parts)
                    message += f"🏠 Địa chỉ: {address}\n"
                
                if partner.phone or partner.mobile:
                    phone = partner.phone or partner.mobile
                    message += f"📞 SĐT: {phone}\n"
        
        # Danh sách sản phẩm
        message += "\n📦 Danh sách sản phẩm:\n"
        for move in self.move_ids_without_package:
            if move.quantity_done > 0:
                product_name = move.product_id.display_name
                qty = move.quantity_done
                uom = move.product_uom.name if move.product_uom else ''
                message += f"  • {product_name}\n"
                message += f"    SL: {qty:.0f} {uom}\n"
        
        # Thêm note nếu có
        if self.note:
            message += f"\n📝 Ghi chú: {self.note}\n"
        
        message += "=" * 40
        
        return message

    def _send_zalo_stock_notification(self):
        """
        Gửi thông báo tới nhân viên nội bộ khi đơn hàng được validate
        Tương đương với send_zalo_when_order_placed() trong PHP
        
        Điều kiện gửi:
        - Chưa gửi trước đó (zalo_stock_notification_sent = False)
        - Có config active
        - Loại đơn được bật (incoming/outgoing)
        - Kho phải là TSN hoặc TSNSR (kiểm tra qua picking_type_id.warehouse_id.code)
        """
        self.ensure_one()
        
        # Kiểm tra đã gửi chưa
        if self.zalo_stock_notification_sent:
            _logger.info("Zalo Notification already sent for picking %s", self.name)
            return
        
        # Kiểm tra kho: Chỉ gửi cho kho TSN hoặc TSNSR
        # picking_type_id → warehouse_id → code
        warehouse_code = ''
        if self.picking_type_id and self.picking_type_id.warehouse_id:
            warehouse_code = self.picking_type_id.warehouse_id.code or ''
        
        # Nếu không phải TSN hoặc TSNSR thì bỏ qua
        if warehouse_code not in ['TSN', 'TSNSR']:
            _logger.info(
                "Zalo Notification skip: picking %s warehouse code '%s' is not TSN or TSNSR",
                self.name, warehouse_code
            )
            return
        
        # Lấy config
        config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        
        if not config:
            _logger.info("No active Zalo Stock Notification config found")
            return
        
        # Kiểm tra config có bật gửi cho loại đơn này không
        if self.picking_type_code == 'outgoing' and not config.send_on_outgoing:
            _logger.info("Zalo Stock Notification disabled for outgoing pickings")
            return
        
        if self.picking_type_code == 'incoming' and not config.send_on_incoming:
            _logger.info("Zalo Stock Notification disabled for incoming pickings")
            return
        
        # Lấy danh sách recipients
        recipients = config.get_recipient_list()
        
        if not recipients:
            _logger.warning("No recipients configured for Zalo Stock Notifications")
            return
        
        # Format message
        try:
            message_text = self._format_zalo_notification_message()
        except Exception as e:
            _logger.exception("Error formatting Zalo Notification message for %s: %s", self.name, e)
            return
        
        # Gửi tin nhắn cho từng recipient
        success_count = 0
        for user_id in recipients:
            try:
                result = config.send_notification_message(user_id, message_text)
                if result.get('error') == 0:
                    success_count += 1
                    _logger.info("Zalo Notification sent to %s for picking %s", user_id, self.name)
                else:
                    _logger.warning(
                        "Zalo Notification failed to %s for picking %s: %s",
                        user_id, self.name, result.get('message', 'Unknown error')
                    )
            except Exception as e:
                _logger.exception("Error sending Zalo Notification to %s: %s", user_id, e)
        
        # Đánh dấu đã gửi nếu có ít nhất 1 tin thành công
        if success_count > 0:
            self.sudo().write({'zalo_stock_notification_sent': True})
            _logger.info(
                "Zalo Stock Notification sent successfully for %s (%s/%s recipients)",
                self.name, success_count, len(recipients)
            )

    def button_validate(self):
        """
        Override button_validate để gửi thông báo Zalo Stock Notification
        khi đơn hàng được validate
        
        === TỰ ĐỘNG GỬI THÔNG BÁO KHI VALIDATE ===
        
        Điều kiện để gửi thông báo:
        1. Đơn hàng đã validate thành công (state = 'done')
        2. Loại đơn phải là incoming (nhập) hoặc outgoing (xuất)
        3. Kho phải là TSN hoặc TSNSR (check trong _send_zalo_stock_notification)
        4. Có config Zalo Stock Notification active
        5. Config đã bật gửi cho loại đơn này (send_on_incoming/send_on_outgoing)
        6. Chưa gửi thông báo trước đó (zalo_stock_notification_sent = False)
        
        Lỗi khi gửi thông báo sẽ được log nhưng KHÔNG block việc validate đơn hàng.
        """
        res = super(StockPicking, self).button_validate()
        
        # Gửi thông báo cho các picking đã done
        for picking in self:
            if picking.state == 'done':
                # Chỉ gửi cho incoming và outgoing
                if picking.picking_type_code in ('incoming', 'outgoing'):
                    try:
                        picking._send_zalo_stock_notification()
                    except Exception as e:
                        # Log lỗi nhưng không block việc validate
                        _logger.exception(
                            "Error sending Zalo Stock Notification for %s: %s",
                            picking.name, e
                        )
        
        return res

    def action_send_zalo_notification_now(self):
        """
        Action button để gửi lại thông báo Zalo Stock Notification
        (có thể dùng cho trường hợp gửi lỗi lần đầu)
        """
        self.ensure_one()
        
        if self.state != 'done':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Không thể gửi'),
                    'message': _('Chỉ có thể gửi thông báo cho đơn hàng đã hoàn thành'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Reset cờ để gửi lại
        self.zalo_stock_notification_sent = False
        
        # Gửi thông báo
        self._send_zalo_stock_notification()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gửi thông báo'),
                'message': _('Đã gửi thông báo Zalo cho đơn hàng %s') % self.name,
                'type': 'success',
                'sticky': False,
            }
        }
