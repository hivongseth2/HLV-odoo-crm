# models/stock_picking_notification.py
import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Cờ đánh dấu đã gửi thông báo cho picking này
    zalo_stock_notification_sent = fields.Boolean('Zalo Notification Sent', default=False, copy=False)

    # def _get_zalo_error_detail(self, error_code):
    #     """
    #     Map Zalo error codes to human-readable messages
        
    #     :param error_code: Error code từ Zalo API
    #     :return: Chi tiết lỗi
    #     """
    #     error_map = {
    #         -201: "user_id là invalid",
    #         -1: "Invalid access_token",
    #         -2: "Invalid user_id",
    #         -3: "Rate limit exceeded (gửi quá nhanh)",
    #         400: "Bad request (định dạng request sai)",
    #         401: "Unauthorized (token không còn hiệu lực)",
    #         404: "Not found (endpoint không tồn tại)",
    #         500: "Zalo server error (lỗi phía Zalo)",
    #     }
    #     return error_map.get(error_code, f"Unknown error code {error_code}")

    def _get_picking_completion_status(self):
        """
        Xác định đơn hàng được xuất/nhập toàn bộ hay một phần
        
        Kiểm tra từ sale.order.line (nếu có) vì nó chính xác hơn stock.picking
        Lý do: stock.picking có thể bị tách (split), nhưng sale.order.line là nguồn gốc
        
        :return: 'toàn bộ' hoặc '1 phần'
        """
        self.ensure_one()
        
        # Nếu là outgoing picking, kiểm tra từ sale.order.delivery_status
        if self.picking_type_code == 'outgoing':
            # Lấy sale.order từ picking (qua origin field)
            sale_orders = self.env['sale.order'].search([
                ('name', '=', self.origin)
            ])
            if sale_orders:
                sale_order = sale_orders[0]
                _logger.debug("Picking %s linked to sale.order %s", self.name, sale_order.name)
                # delivery_status: 'pending', 'started', 'partial', 'full'
                if sale_order.delivery_status in ['pending', 'started', 'partial']:
                    _logger.debug(
                        "Picking %s: sale.order %s has delivery_status=%s",
                        self.name, sale_order.name, sale_order.delivery_status
                    )
                    return '1 phần'
                elif sale_order.delivery_status == 'full':
                    _logger.debug(
                        "Picking %s: sale.order %s has delivery_status=full",
                        self.name, sale_order.name
                    )
                    return 'toàn bộ'
        
        # Nếu không phải outgoing hoặc không tìm thấy sale.order, kiểm tra từ stock.picking
        _logger.debug("Picking %s: checking from stock.picking (no sale.order linked or not outgoing)", self.name)
        
        # Kiểm tra xem có move line nào bị split (done < demand) không
        for move in self.move_ids_without_package:
            if move.product_uom_qty > 0:
                # Tính tổng qty_done từ move_line_ids
                qty_done = sum(move.move_line_ids.mapped('qty_done'))
                # Nếu qty_done < quantity demanded => xuất/nhập 1 phần
                if qty_done < move.product_uom_qty:
                    _logger.debug(
                        "Picking %s has partial delivery: product=%s, done=%s, demand=%s",
                        self.name, move.product_id.name, qty_done, move.product_uom_qty
                    )
                    return '1 phần'
        
        # Kiểm tra nếu có backorder => xuất/nhập 1 phần
        if self.backorder_id:
            _logger.debug("Picking %s has backorder: %s", self.name, self.backorder_id.name)
            return '1 phần'
        
        _logger.debug("Picking %s delivered completely", self.name)
        return 'toàn bộ'

    def _format_zalo_notification_message(self):
        """
        Format tin nhắn thông báo theo yêu cầu
        Tương đương với phần build message trong PHP
        
        :return: Message text
        """
        self.ensure_one()
        
        _logger.debug("Formatting Zalo notification message for picking %s", self.name)
        
        # Xác định loại đơn
        if self.picking_type_code == 'outgoing':
            action_type = 'XUẤT'
        elif self.picking_type_code == 'incoming':
            action_type = 'NHẬP'
        else:
            action_type = self.picking_type_id.name or 'CHUYỂN'
        
        _logger.debug("Picking %s action_type: %s", self.name, action_type)
        
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
            _logger.debug("Picking %s warehouse: %s", self.name, warehouse_name)
        
        # Build message
        message = f"🔔 Thông báo đơn hàng {action_type}\n"
        message += f"📋 Mã đơn hàng: {order_code}\n"
        message += f"📦 Mã phiếu xuất kho odoo: {self.name}\n"
        message += f"📊 Trạng thái: {action_type} {completion_status}\n"
        # message += f"🕐 Thời gian: {done_date_str}\n"
        
        # # Thêm thông tin partner nếu có
        # if self.partner_id:
        #     message += f"👤 Đối tác: {self.partner_id.name}\n"
        #     _logger.debug("Picking %s partner: %s", self.name, self.partner_id.name)
        # else:
        #     _logger.debug("Picking %s has no partner", self.name)
        
        # Thêm thông tin địa chỉ nếu có
        # if self.picking_type_code == 'outgoing' and self.partner_id:
        #     # Với đơn xuất, hiển thị địa chỉ giao hàng
        #     partner = self._zns_get_shipping_partner() if hasattr(self, '_zns_get_shipping_partner') else self.partner_id
        #     if partner:
        #         address_parts = []
        #         if partner.street:
        #             address_parts.append(partner.street)
        #         if partner.city:
        #             address_parts.append(partner.city)
        #         if partner.state_id:
        #             address_parts.append(partner.state_id.name)
                
        #         if address_parts:
        #             address = ', '.join(address_parts)
        #             message += f"🏠 Địa chỉ: {address}\n"
        #             _logger.debug("Picking %s address: %s", self.name, address)
                
        #         if partner.phone or partner.mobile:
        #             phone = partner.phone or partner.mobile
        #             message += f"📞 SĐT: {phone}\n"
        #             _logger.debug("Picking %s phone: %s", self.name, phone)
        
        # Danh sách sản phẩm
        message += "\n📦 Danh sách sản phẩm:\n"
        product_count = 0
        for move in self.move_ids_without_package:
            # Tính tổng qty_done từ move_line_ids
            qty_done = sum(move.move_line_ids.mapped('qty_done'))
            if qty_done > 0:
                product_count += 1
                product_name = move.product_id.display_name
                qty = qty_done
                uom = move.product_uom.name if move.product_uom else ''
                message += f"  • {product_name}\n"
                message += f"    SL: {qty:.0f} {uom}\n"
                _logger.debug(
                    "Picking %s product: %s, qty_done=%s, uom=%s",
                    self.name, product_name, qty_done, uom
                )
        
        if product_count == 0:
            _logger.warning("Picking %s has no products with qty_done > 0", self.name)
        
        # Thêm note nếu có
        if self.note:
            message += f"\n📝 Ghi chú: {self.note}\n"
        
        
        return message

    def _send_zalo_stock_notification(self):
        """
        Gửi thông báo tới nhân viên nội bộ khi đơn hàng được validate
        Tương đương với send_zalo_when_order_placed() trong PHP
        
        Điều kiện gửi:
        - Chưa gửi trước đó (zalo_stock_notification_sent = False)
        - Có config active
        - Loại đơn được bật (incoming/outgoing)
        - Kho phải được cấu hình hoặc sử dụng danh sách mặc định
        - Với outgoing: Chỉ gửi cho bước xuất cuối cùng tới khách hàng (location_dest_id.usage = 'customer')
        
        Logic lấy recipients:
        - Lấy warehouse code từ picking_type_id.warehouse_id.code
        - Tìm warehouse mapping tương ứng trong config.warehouse_recipient_ids
        - Nếu tìm thấy → Sử dụng danh sách recipients từ warehouse mapping
        - Nếu không tìm thấy → Sử dụng danh sách recipients mặc định
        """
        self.ensure_one()
        
        # Kiểm tra đã gửi chưa
        if self.zalo_stock_notification_sent:
            _logger.info("Zalo Notification already sent for picking %s", self.name)
            return
        
        # Lấy warehouse code
        # picking_type_id → warehouse_id → code
        warehouse_code = ''
        if self.picking_type_id and self.picking_type_id.warehouse_id:
            warehouse_code = self.picking_type_id.warehouse_id.code or ''
        
        # Với đơn xuất (outgoing): Chỉ gửi thông báo cho bước xuất cuối cùng tới khách hàng
        # Kiểm tra location_dest_id.usage = 'customer'
        if self.picking_type_code == 'outgoing':
            if not self.location_dest_id or self.location_dest_id.usage != 'customer':
                _logger.info(
                    "Zalo Notification skip: picking %s is outgoing but dest location is not customer (usage: %s)",
                    self.name, self.location_dest_id.usage if self.location_dest_id else 'None'
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
        
        # Lấy danh sách recipients dựa vào warehouse code
        recipients = config.get_recipients_for_warehouse(warehouse_code)
        
        if not recipients:
            _logger.warning(
                "No recipients configured for warehouse %s in Zalo Stock Notifications",
                warehouse_code
            )
            return
        
        _logger.info(
            "Zalo Stock Notification: Starting to send for picking %s to %s recipients (user_ids: %s)",
            self.name, len(recipients), ", ".join(str(r) for r in recipients)
        )
        
        # Format message
        try:
            message_text = self._format_zalo_notification_message()
            _logger.debug("Zalo Notification message formatted successfully for %s", self.name)
        except Exception as e:
            _logger.exception("Error formatting Zalo Notification message for %s: %s", self.name, e)
            return
        
        # Kiểm tra access token
        if not config.access_token:
            _logger.error("Zalo Config for picking %s has no access_token. Please authorize first.", self.name)
            return
        
        if config.token_expires_at:
            from datetime import datetime
            expires_at = config.token_expires_at
            if isinstance(expires_at, str):
                from dateutil import parser
                expires_at = parser.parse(expires_at)
            
            if expires_at < datetime.now():
                _logger.warning(
                    "Zalo access_token expired at %s for picking %s. Token refresh may be needed.",
                    config.token_expires_at, self.name
                )
        
        # Gửi tin nhắn cho từng recipient
        success_count = 0
        fail_count = 0
        for i, user_id in enumerate(recipients, 1):
            _logger.info(
                "Zalo Notification: Sending to recipient %s/%s (user_id: %s) for picking %s",
                i, len(recipients), user_id, self.name
            )
            try:
                result = config.send_notification_message(user_id, message_text)
                
                if not result:
                    _logger.error(
                        "Zalo Notification: No response from send_notification_message for user_id %s, picking %s",
                        user_id, self.name
                    )
                    fail_count += 1
                    continue
                
                error_code = result.get('error')
                error_msg = result.get('message', 'No message in response')
                
                if error_code == 0:
                    success_count += 1
                    _logger.info(
                        "✓ Zalo Notification sent successfully to %s for picking %s",
                        user_id, self.name
                    )
                else:
                    fail_count += 1
                    # Log chi tiết error với error code mapping
                    # error_detail = self._get_zalo_error_detail(error_code)
                    # _logger.warning(
                    #     "✗ Zalo Notification failed to %s for picking %s. Error code: %s (%s), Message: %s",
                    #     user_id, self.name, error_code, error_detail, error_msg
                    # )
            except Exception as e:
                fail_count += 1
                _logger.exception(
                    "✗ Exception sending Zalo Notification to %s for picking %s: %s",
                    user_id, self.name, str(e)
                )
        
        # Log tóm tắt kết quả
        _logger.info(
            "Zalo Stock Notification Summary for %s: Success=%s, Failed=%s, Total=%s",
            self.name, success_count, fail_count, len(recipients)
        )
        
        # Đánh dấu đã gửi nếu có ít nhất 1 tin thành công
        if success_count > 0:
            self.sudo().write({'zalo_stock_notification_sent': True})
            _logger.info(
                "Zalo Stock Notification marked as sent for picking %s",
                self.name
            )
        elif fail_count > 0:
            _logger.error(
                "Zalo Stock Notification: All attempts failed for picking %s. "
                "Please check: 1) user_ids are valid, 2) access_token is not expired, 3) account Zalo is active",
                self.name
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
