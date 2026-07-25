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
        
        Logic:
        - Outgoing: Kiểm tra từ sale.order.delivery_status (nếu có) vì nó chính xác hơn stock.picking
        - Incoming: Kiểm tra từ purchase.order.receipt_status hoặc so sánh qty với purchase.order.line
        
        Lý do: stock.picking có thể bị tách (split), nhưng sale.order.line và purchase.order.line là nguồn gốc
        
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
        
        # Nếu là incoming picking, kiểm tra từ purchase.order
        elif self.picking_type_code == 'incoming':
            _logger.debug("Picking %s: checking from purchase.order (type=%s)", self.name, self.picking_type_code)
            # Lấy purchase.order từ picking (qua origin field)
            purchase_orders = self.env['purchase.order'].search([
                ('name', '=', self.origin)
            ])
            if purchase_orders:
                purchase_order = purchase_orders[0]
                _logger.debug("Picking %s linked to purchase.order %s", self.name, purchase_order.name)
                # Kiểm tra receipt_status nếu có (Odoo 14+)
                if hasattr(purchase_order, 'receipt_status'):
                    # receipt_status: 'pending', 'partial', 'received'
                    if purchase_order.receipt_status in ['pending', 'partial']:
                        _logger.debug(
                            "Picking %s: purchase.order %s has receipt_status=%s",
                            self.name, purchase_order.name, purchase_order.receipt_status
                        )
                        return '1 phần'
                    elif purchase_order.receipt_status == 'received':
                        _logger.debug(
                            "Picking %s: purchase.order %s has receipt_status=received",
                            self.name, purchase_order.name
                        )
                        return 'toàn bộ'
                else:
                    # Fallback: so sánh qty_received với qty
                    _logger.debug("Picking %s: receipt_status not available, comparing quantities", self.name)
                    for line in purchase_order.order_line:
                        if line.product_qty > 0:
                            if line.qty_received < line.product_qty:
                                _logger.debug(
                                    "Picking %s: purchase.order line has partial receipt: product=%s, received=%s, qty=%s",
                                    self.name, line.product_id.name, line.qty_received, line.product_qty
                                )
                                return '1 phần'
                    _logger.debug("Picking %s: purchase.order received completely", self.name)
                    return 'toàn bộ'
        
        # Nếu không phải outgoing hoặc không tìm thấy sale.order/purchase.order, kiểm tra từ stock.picking
        _logger.debug("Picking %s: checking from stock.picking fallback (type=%s)", self.name, self.picking_type_code)
        
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
        
        Cấu trúc khác nhau giữa incoming/outgoing:
        - Outgoing: Lấy dữ liệu từ sale.order, nhân viên từ picking_type hoặc sale.order
        - Incoming: Lấy dữ liệu từ purchase.order (qua move_ids), nhân viên từ picking.user_id
        
        Định dạng tin nhắn:
        - In đậm các trường quan trọng: số đơn hàng, số phiếu, mã nhân viên
        - Sử dụng emoji để dễ phân biệt các section
        
        :return: Message text (có markup Zalo)
        """
        self.ensure_one()
        
        _logger.debug("Formatting Zalo notification message for picking %s (type: %s)", self.name, self.picking_type_code)
        
        # Xác định loại đơn
        if self.picking_type_code == 'outgoing':
            action_type = 'XUẤT KHO GIAO KHÁCH'
            label_type = 'xuất'
        elif self.picking_type_code == 'incoming':
            action_type = 'NHẬP'
            label_type = 'nhập'
        else:
            action_type = self.picking_type_id.name or 'CHUYỂN'
            label_type = action_type.lower()
        
        _logger.debug("Picking %s action_type: %s", self.name, action_type)
        
        # Lấy mã đơn hàng gốc (source.origin)
        order_code = self.origin or self.name
        
        # Trạng thái xuất/nhập (toàn bộ hay 1 phần)
        completion_status = self._get_picking_completion_status()
        
        # Lấy thông tin kho
        warehouse_name = ''
        if self.picking_type_id and self.picking_type_id.warehouse_id:
            warehouse_name = self.picking_type_id.warehouse_id.name or ''
            _logger.debug("Picking %s warehouse: %s", self.name, warehouse_name)
        
        # Build message
        message = f"🔔 ĐƠN HÀNG {action_type}\n"
        message += f"  • Số đơn hàng: {order_code}\n"
        # message += f"  • Số phiếu {label_type} kho Odoo: {self.name}\n"
        message += f"  • Kho {label_type}: {warehouse_name}\n"
        message += f"  • Trạng thái: {label_type} {completion_status}\n"
        
        # lấy thông tin khách
        if self.picking_type_code == 'outgoing' and self.partner_id:
            message += f"  • Khách hàng: {self.partner_id.parent_id.name or self.partner_id.name}\n"
            
        
        # Lấy mã nhân viên sale từ sale.order (chỉ cho outgoing)
        saler_code = None
        if self.picking_type_code == 'outgoing':
            sale_orders = self.env['sale.order'].search([
                ('name', '=', self.origin)
            ])
            if sale_orders:
                sale_order = sale_orders[0]
                if hasattr(sale_order, 'x_studio_misa_saler_code'):
                    saler_code = sale_order.x_studio_misa_saler_code
                    _logger.debug("Picking %s sale.order %s saler_code: %s", self.name, sale_order.name, saler_code)
        
        # Thêm thông tin nhân viên sale nếu có
        if saler_code:
            message += f"  • Mã NV Sale: {saler_code}\n"
            _logger.debug("Picking %s added saler info to message", self.name)
        
        # Thêm thông tin người phụ trách (chỉ cho phiếu nhập)
        # - Incoming: Lấy từ picking.user_id (người phụ trách đơn mua hàng)
        if self.picking_type_code == 'incoming':
            # Cho phiếu nhập: lấy user từ picking.user_id
            if self.user_id:
                message += f"  • Người phụ trách: {self.user_id.name}\n"
                _logger.debug("Picking %s (incoming) responsible user: %s", self.name, self.user_id.name)
        
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
                message += f"    SL: {qty:g} {uom}\n"
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

    # def _send_zalo_stock_notification(self):
    #     """
    #     Gửi thông báo tới nhân viên nội bộ khi đơn hàng được validate
    #     Tương đương với send_zalo_when_order_placed() trong PHP
        
    #     === CƠ CHẾ HOẠT ĐỘNG ===
        
    #     📤 PHIẾU XUẤT (Outgoing):
    #     1. Lấy mã saler_code từ sale.order (qua origin)
    #     2. Kiểm tra saler_code có nằm trong danh sách online không
    #     3. Nếu CÓ → Gửi tới user_id Kế toán ONLINE
    #     4. Nếu KHÔNG → Gửi tới user_id Kế toán OFFLINE
    #     5. Nếu không có saler_code → Log warning, không gửi
        
    #     📥 PHIẾU NHẬP (Incoming):
    #     1. Kiểm tra nguồn gốc phiếu nhập (location_id.usage)
    #     2. Chỉ gửi cho phiếu nhập từ NHÀ CUNG CẤP (location_id.usage = 'supplier')
    #     3. Bỏ qua CHUYỂN KHO NỘI BỘ (location_id.usage = 'internal')
    #     4. (TODO: Có thể mở comment để gửi cho TRẢ HÀNG - location_id.usage = 'customer')
    #     5. Gửi tới user_id Kế toán NHẬP KHO (cố định)
        
    #     Điều kiện gửi:
    #     - Chưa gửi trước đó (zalo_stock_notification_sent = False)
    #     - Có config active
    #     - Loại đơn được bật (incoming/outgoing)
    #     - Với outgoing: Chỉ gửi cho bước xuất cuối cùng tới khách hàng (location_dest_id.usage = 'customer')
    #     - Với incoming: Chỉ gửi cho phiếu nhập từ nhà cung cấp (location_id.usage = 'supplier')
    #     """
    #     self.ensure_one()
        
    #     # Kiểm tra đã gửi chưa
    #     if self.zalo_stock_notification_sent:
    #         _logger.info("Zalo Notification already sent for picking %s", self.name)
    #         return
        
    #     # Với đơn xuất (outgoing): Chỉ gửi thông báo cho bước xuất cuối cùng tới khách hàng
    #     # Kiểm tra location_dest_id.usage = 'customer'
    #     if self.picking_type_code == 'outgoing':
    #         if not self.location_dest_id or self.location_dest_id.usage != 'customer':
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s is outgoing but dest location is not customer (usage: %s)",
    #                 self.name, self.location_dest_id.usage if self.location_dest_id else 'None'
    #             )
    #             return
        
    #     # Lấy config
    #     config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        
    #     if not config:
    #         _logger.info("No active Zalo Stock Notification config found")
    #         return
        
    #     # Kiểm tra config có bật gửi cho loại đơn này không
    #     if self.picking_type_code == 'outgoing' and not config.send_on_outgoing:
    #         _logger.info("Zalo Stock Notification disabled for outgoing pickings")
    #         return
        
    #     if self.picking_type_code == 'incoming' and not config.send_on_incoming:
    #         _logger.info("Zalo Stock Notification disabled for incoming pickings")
    #         return
        
    #     # === CÓ CHẾ MỚI: Xác định user_id dựa trên loại phiếu ===
    #     saler_code = None
    #     recipient_user_id = None
        
    #     if self.picking_type_code == 'outgoing':
    #         # === PHIẾU XUẤT: Dựa vào saler_code (online/offline) ===
    #         sale_orders = self.env['sale.order'].search([
    #             ('name', '=', self.origin)
    #         ])
    #         if sale_orders:
    #             sale_order = sale_orders[0]
    #             if hasattr(sale_order, 'x_studio_misa_saler_code'):
    #                 saler_code = sale_order.x_studio_misa_saler_code
    #                 _logger.debug(
    #                     "Picking %s linked to sale.order %s with saler_code: %s",
    #                     self.name, sale_order.name, saler_code
    #                 )
            
    #         # Nếu không có saler_code, không gửi
    #         if not saler_code:
    #             _logger.warning(
    #                 "Zalo Notification not sent for outgoing picking %s: no saler_code found",
    #                 self.name
    #             )
    #             return
            
    #         # Xác định user_id dựa trên saler_code
    #         recipient_user_id = config.get_recipient_for_saler(saler_code)
            
    #         if not recipient_user_id:
    #             _logger.warning(
    #                 "Zalo Notification not sent for outgoing picking %s: no recipient_user_id determined for saler_code %s",
    #                 self.name, saler_code
    #             )
    #             return
        
    #     elif self.picking_type_code == 'incoming':
    #         # === PHIẾU NHẬP: Chỉ gửi cho phiếu nhập từ đơn mua hàng ===
            
    #         # Kiểm tra nguồn gốc của phiếu nhập qua location_id.usage
    #         if not self.location_id:
    #             _logger.warning(
    #                 "Zalo Notification not sent for incoming picking %s: no location_id",
    #                 self.name
    #             )
    #             return
            
    #         location_usage = self.location_id.usage
            
    #         # Chỉ gửi thông báo cho phiếu nhập từ NHÀ CUNG CẤP (đơn mua hàng)
    #         if location_usage == 'supplier':
    #             _logger.debug(
    #                 "Picking %s (incoming): from supplier - will send notification",
    #                 self.name
    #             )
    #         # # TODO: Có thể bật để gửi thông báo cho phiếu nhập từ TRẢ HÀNG (customer return)
    #         elif location_usage == 'customer':
    #             _logger.debug(
    #                 "Picking %s (incoming): from customer return - will send notification",
    #                 self.name
    #             )
    #         # Bỏ qua chuyển kho nội bộ (internal transfer)
    #         elif location_usage == 'internal':
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s is internal transfer (location_id.usage = 'internal')",
    #                 self.name
    #             )
    #             return
    #         # Bỏ qua các loại khác
    #         else:
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s has unsupported location_id.usage = '%s'",
    #                 self.name, location_usage
    #             )
    #             return
            
    #         # Lấy user_id nhận thông báo
    #         recipient_user_id = config.incoming_recipient_user_id
            
    #         if not recipient_user_id:
    #             _logger.warning(
    #                 "Zalo Notification not sent for incoming picking %s: incoming_recipient_user_id not configured",
    #                 self.name
    #             )
    #             return
            
    #         _logger.debug(
    #             "Picking %s (incoming from %s): will send to incoming_recipient_user_id: %s",
    #             self.name, location_usage, recipient_user_id
    #         )
        
    #     # Log thông tin gửi
    #     if self.picking_type_code == 'outgoing':
    #         _logger.info(
    #             "Zalo Stock Notification: Starting to send for OUTGOING picking %s to user_id %s (saler_code: %s)",
    #             self.name, recipient_user_id, saler_code
    #         )
    #     else:
    #         _logger.info(
    #             "Zalo Stock Notification: Starting to send for INCOMING picking %s to user_id %s",
    #             self.name, recipient_user_id
    #         )
        
    #     # Format message
    #     try:
    #         message_text = self._format_zalo_notification_message()
    #         _logger.debug("Zalo Notification message formatted successfully for %s", self.name)
    #     except Exception as e:
    #         _logger.exception("Error formatting Zalo Notification message for %s: %s", self.name, e)
    #         return
        
    #     # Kiểm tra access token (sử dụng method để hỗ trợ shared token)
    #     try:
    #         access_token = config.get_valid_access_token()
    #         if not access_token:
    #             _logger.error("Zalo Config for picking %s has no valid access_token. Please authorize first.", self.name)
    #             return
    #     except Exception as e:
    #         _logger.exception("Error getting access token for picking %s: %s", self.name, e)
    #         return
        
    #     if config.token_expires_at:
    #         from datetime import datetime
    #         expires_at = config.token_expires_at
    #         if isinstance(expires_at, str):
    #             from dateutil import parser
    #             expires_at = parser.parse(expires_at)
            
    #         if expires_at < datetime.now():
    #             _logger.warning(
    #                 "Zalo access_token expired at %s for picking %s. Token refresh may be needed.",
    #                 config.token_expires_at, self.name
    #             )
        
    #     # Gửi tin nhắn
    #     try:
    #         result = config.send_notification_message(recipient_user_id, message_text)
            
    #         if not result:
    #             _logger.error(
    #                 "Zalo Notification: No response from send_notification_message for user_id %s, picking %s (%s)",
    #                 recipient_user_id, self.name, self.picking_type_code
    #             )
    #             return
            
    #         error_code = result.get('error')
            
    #         if error_code == 0:
    #             if self.picking_type_code == 'outgoing':
    #                 _logger.info(
    #                     "✓ Zalo Notification sent successfully to %s for OUTGOING picking %s (saler_code: %s)",
    #                     recipient_user_id, self.name, saler_code
    #                 )
    #             else:
    #                 _logger.info(
    #                     "✓ Zalo Notification sent successfully to %s for INCOMING picking %s",
    #                     recipient_user_id, self.name
    #                 )
    #             # Đánh dấu đã gửi
    #             self.sudo().write({'zalo_stock_notification_sent': True})
    #         else:
    #             _logger.error(
    #                 "✗ Zalo Notification failed to %s for picking %s (%s). Error code: %s",
    #                 recipient_user_id, self.name, self.picking_type_code, error_code
    #             )
    #     except Exception as e:
    #         _logger.exception(
    #             "✗ Exception sending Zalo Notification to %s for picking %s (%s): %s",
    #             recipient_user_id, self.name, self.picking_type_code, str(e)
    #         )



    # def _send_zalo_stock_notification(self):
    #     """
    #     Gửi thông báo tới nhân viên nội bộ khi đơn hàng được validate.

    #     📤 PHIẾU XUẤT (Outgoing):
    #     - Lấy saler_code từ sale.order (x_studio_misa_saler_code)
    #     - Xác định kế toán nhận: online/offline (get_recipient_for_saler)
    #     - ĐỌC THÊM mapping saler_mapping_text để gửi trực tiếp cho nhân viên sale
    #     - Gửi tin nhắn tới:
    #       + Kế toán ONLINE/OFFLINE (nếu cấu hình)
    #       + Tất cả Zalo User ID map với saler_code trong saler_mapping_text

    #     📥 PHIẾU NHẬP (Incoming):
    #     - Chỉ gửi cho phiếu nhập từ supplier (location_id.usage = 'supplier')
    #     - Gửi tới incoming_recipient_user_id
    #     """
    #     self.ensure_one()

    #     # Đã gửi rồi thì bỏ qua
    #     if self.zalo_stock_notification_sent:
    #         _logger.info("Zalo Notification already sent for picking %s", self.name)
    #         return

    #     # OUTGOING: chỉ gửi cho bước xuất cuối cùng tới KH (location_dest_id.usage = 'customer')
    #     if self.picking_type_code == 'outgoing':
    #         if not self.location_dest_id or self.location_dest_id.usage != 'customer':
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s is outgoing but dest location is not customer (usage: %s)",
    #                 self.name,
    #                 self.location_dest_id.usage if self.location_dest_id else 'None',
    #             )
    #             return

    #     # Lấy config
    #     config = (
    #         self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
    #     )
    #     if not config:
    #         _logger.info("No active Zalo Stock Notification config found")
    #         return

    #     # Kiểm tra bật/tắt theo loại phiếu
    #     if self.picking_type_code == "outgoing" and not config.send_on_outgoing:
    #         _logger.info("Zalo Stock Notification disabled for outgoing pickings")
    #         return

    #     if self.picking_type_code == "incoming" and not config.send_on_incoming:
    #         _logger.info("Zalo Stock Notification disabled for incoming pickings")
    #         return

    #     # ===== Xác định danh sách user_id cần gửi =====
    #     saler_code = None
    #     recipient_user_ids = []

    #     if self.picking_type_code == "outgoing":
    #         # Lấy SO và saler_code
    #         sale_orders = self.env["sale.order"].search(
    #             [("name", "=", self.origin)]
    #         )
    #         if sale_orders:
    #             sale_order = sale_orders[0]
    #             if hasattr(sale_order, "x_studio_misa_saler_code"):
    #                 saler_code = sale_order.x_studio_misa_saler_code
    #                 _logger.debug(
    #                     "Picking %s linked to sale.order %s with saler_code: %s",
    #                     self.name,
    #                     sale_order.name,
    #                     saler_code,
    #                 )

    #         if not saler_code:
    #             _logger.warning(
    #                 "Zalo Notification not sent for outgoing picking %s: no saler_code found",
    #                 self.name,
    #             )
    #             return

    #         # 1) Kế toán ONLINE/OFFLINE (config cũ)
    #         accountant_user_id = config.get_recipient_for_saler(saler_code)

    #         # 2) Danh sách Zalo user ID của chính nhân viên sale
    #         saler_user_ids = config.get_saler_user_ids_from_mapping(saler_code)

    #         if accountant_user_id:
    #             recipient_user_ids.append(accountant_user_id)
    #         if saler_user_ids:
    #             recipient_user_ids.extend(saler_user_ids)

    #         # Loại bỏ trùng + rỗng
    #         recipient_user_ids = [
    #             uid for uid in dict.fromkeys(recipient_user_ids) if uid
    #         ]

    #         if not recipient_user_ids:
    #             _logger.warning(
    #                 "Zalo Notification not sent for outgoing picking %s: no recipient_user_ids for saler_code %s",
    #                 self.name,
    #                 saler_code,
    #             )
    #             return

    #     elif self.picking_type_code == "incoming":
    #         # CHỈ gửi cho phiếu nhập từ supplier
    #         if not self.location_id:
    #             _logger.warning(
    #                 "Zalo Notification not sent for incoming picking %s: no location_id",
    #                 self.name,
    #             )
    #             return

    #         location_usage = self.location_id.usage

    #         if location_usage == "supplier":
    #             _logger.debug(
    #                 "Picking %s (incoming): from supplier - will send notification",
    #                 self.name,
    #             )
    #         elif location_usage == "customer":
    #             _logger.debug(
    #                 "Picking %s (incoming): from customer return - will send notification",
    #                 self.name,
    #             )
    #         elif location_usage == "internal":
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s is internal transfer",
    #                 self.name,
    #             )
    #             return
    #         else:
    #             _logger.info(
    #                 "Zalo Notification skip: picking %s has unsupported location_id.usage = '%s'",
    #                 self.name,
    #                 location_usage,
    #             )
    #             return

    #         accountant_user_id = config.incoming_recipient_user_id
    #         if not accountant_user_id:
    #             _logger.warning(
    #                 "Zalo Notification not sent for incoming picking %s: incoming_recipient_user_id not configured",
    #                 self.name,
    #             )
    #             return

    #         recipient_user_ids = [accountant_user_id]

    #     else:
    #         _logger.info(
    #             "Zalo Notification skip: picking %s has unsupported picking_type_code=%s",
    #             self.name,
    #             self.picking_type_code,
    #         )
    #         return

    #     # Log recap
    #     if self.picking_type_code == "outgoing":
    #         _logger.info(
    #             "Zalo Stock Notification: OUTGOING picking %s, saler_code=%s, recipient_user_ids=%s",
    #             self.name,
    #             saler_code,
    #             recipient_user_ids,
    #         )
    #     else:
    #         _logger.info(
    #             "Zalo Stock Notification: INCOMING picking %s, recipient_user_ids=%s",
    #             self.name,
    #             recipient_user_ids,
    #         )

    #     # Format message
    #     try:
    #         message_text = self._format_zalo_notification_message()
    #         _logger.debug(
    #             "Zalo Notification message formatted successfully for %s",
    #             self.name,
    #         )
    #     except Exception as e:
    #         _logger.exception(
    #             "Error formatting Zalo Notification message for %s: %s",
    #             self.name,
    #             e,
    #         )
    #         return

    #     # Lấy access token (shared token)
    #     try:
    #         access_token = config.get_valid_access_token()
    #         if not access_token:
    #             _logger.error(
    #                 "Zalo Config for picking %s has no valid access_token. Please authorize first.",
    #                 self.name,
    #             )
    #             return
    #     except Exception as e:
    #         _logger.exception(
    #             "Error getting access token for picking %s: %s", self.name, e
    #         )
    #         return

    #     # Cảnh báo nếu token hết hạn (nếu có)
    #     if config.token_expires_at:
    #         from datetime import datetime
    #         from dateutil import parser

    #         expires_at = config.token_expires_at
    #         if isinstance(expires_at, str):
    #             expires_at = parser.parse(expires_at)

    #         if expires_at < datetime.now():
    #             _logger.warning(
    #                 "Zalo access_token expired at %s for picking %s. Token refresh may be needed.",
    #                 config.token_expires_at,
    #                 self.name,
    #             )

    #     # ===== Gửi tin nhắn cho TẤT CẢ recipient_user_ids =====
    #     any_success = False

    #     for uid in recipient_user_ids:
    #         try:
    #             result = config.send_notification_message(uid, message_text)

    #             if not result:
    #                 _logger.error(
    #                     "Zalo Notification: No response from send_notification_message for user_id %s, picking %s (%s)",
    #                     uid,
    #                     self.name,
    #                     self.picking_type_code,
    #                 )
    #                 continue

    #             error_code = result.get("error")

    #             if error_code == 0:
    #                 any_success = True
    #                 if self.picking_type_code == "outgoing":
    #                     _logger.info(
    #                         "✓ Zalo Notification sent successfully to %s for OUTGOING picking %s (saler_code: %s)",
    #                         uid,
    #                         self.name,
    #                         saler_code,
    #                     )
    #                 else:
    #                     _logger.info(
    #                         "✓ Zalo Notification sent successfully to %s for INCOMING picking %s",
    #                         uid,
    #                         self.name,
    #                     )
    #             else:
    #                 _logger.error(
    #                     "✗ Zalo Notification failed to %s for picking %s (%s). Error code: %s",
    #                     uid,
    #                     self.name,
    #                     self.picking_type_code,
    #                     error_code,
    #                 )
    #         except Exception as e:
    #             _logger.exception(
    #                 "✗ Exception sending Zalo Notification to %s for picking %s (%s): %s",
    #                 uid,
    #                 self.name,
    #                 self.picking_type_code,
    #                 str(e),
    #             )

    #     # Nếu gửi được ít nhất 1 người thì mark đã gửi
    #     if any_success:
    #         self.sudo().write({"zalo_stock_notification_sent": True})





    def _send_zalo_stock_notification(self):
        """Gửi thông báo tới nhân viên nội bộ khi đơn hàng được validate."""
        self.ensure_one()

        # ==============================================================================
        # 1. FIX RACE CONDITION: Sử dụng SQL Lock để chặn các request song song
        # ==============================================================================
        try:
            # Khoá dòng này trong DB ngay lập tức. Nếu có request khác đang chạy, nó sẽ phải chờ.
            self.env.cr.execute(
                "SELECT zalo_stock_notification_sent FROM stock_picking WHERE id = %s FOR UPDATE", 
                (self.id,)
            )
            # Kiểm tra trực tiếp từ DB để đảm bảo dữ liệu mới nhất (bỏ qua Cache)
            is_sent_db = self.env.cr.fetchone()
            if is_sent_db and is_sent_db[0]:
                _logger.info("SKIP: Zalo Notification already sent (detected via SQL Lock) for picking %s", self.name)
                return
        except Exception as e:
            # Trường hợp hiếm gặp nếu DB không cho lock, log warning nhưng vẫn chạy tiếp logic ORM
            _logger.warning("Could not acquire SQL lock for picking %s: %s", self.name, e)

        # Kiểm tra lại qua ORM (lớp bảo vệ thứ 2)
        if self.zalo_stock_notification_sent:
            _logger.info("Zalo Notification already sent for picking %s", self.name)
            return

        # ==============================================================================
        # KIỂM TRA ĐIỀU KIỆN GỬI (Logic nghiệp vụ)
        # ==============================================================================
        
        # OUTGOING: chỉ gửi cho bước xuất cuối cùng tới KH
        if self.picking_type_code == 'outgoing':
            if not self.location_dest_id or self.location_dest_id.usage != 'customer':
                _logger.info(
                    "Zalo Notification skip: picking %s is outgoing but dest location is not customer (usage: %s)",
                    self.name,
                    self.location_dest_id.usage if self.location_dest_id else 'None',
                )
                return

        # Lấy config
        config = self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
        if not config:
            _logger.info("No active Zalo Stock Notification config found")
            return

        # Kiểm tra bật/tắt theo loại phiếu
        if self.picking_type_code == "outgoing" and not config.send_on_outgoing:
            _logger.info("Zalo Stock Notification disabled for outgoing pickings")
            return

        if self.picking_type_code == "incoming" and not config.send_on_incoming:
            _logger.info("Zalo Stock Notification disabled for incoming pickings")
            return

        # ==============================================================================
        # XÁC ĐỊNH DANH SÁCH USER ID
        # ==============================================================================
        saler_code = None
        recipient_user_ids = []

        if self.picking_type_code == "outgoing":
            # Lấy SO và saler_code
            sale_orders = self.env["sale.order"].search([("name", "=", self.origin)])
            if sale_orders:
                sale_order = sale_orders[0]
                if hasattr(sale_order, "x_studio_misa_saler_code"):
                    saler_code = sale_order.x_studio_misa_saler_code
                    _logger.debug("Picking %s linked to sale.order %s with saler_code: %s", self.name, sale_order.name, saler_code)

            if not saler_code:
                _logger.warning("Zalo Notification not sent for outgoing picking %s: no saler_code found", self.name)
                return

            # 1) Kế toán ONLINE/OFFLINE
            accountant_user_id = config.get_recipient_for_saler(saler_code)

            # 2) Danh sách Zalo user ID của chính nhân viên sale
            saler_user_ids = config.get_saler_user_ids_from_mapping(saler_code)

            if accountant_user_id:
                recipient_user_ids.append(accountant_user_id)
            if saler_user_ids:
                recipient_user_ids.extend(saler_user_ids)

            if not recipient_user_ids:
                _logger.warning("Zalo Notification not sent: no recipient_user_ids for saler_code %s", saler_code)
                return

        elif self.picking_type_code == "incoming":
            # CHỈ gửi cho phiếu nhập từ supplier
            if not self.location_id:
                _logger.warning("Zalo Notification not sent for incoming picking %s: no location_id", self.name)
                return

            location_usage = self.location_id.usage
            if location_usage in ["supplier", "customer"]:
                _logger.debug("Picking %s (incoming): valid source (%s) - will send notification", self.name, location_usage)
            elif location_usage == "internal":
                _logger.info("Zalo Notification skip: picking %s is internal transfer", self.name)
                return
            else:
                _logger.info("Zalo Notification skip: picking %s has unsupported location_id.usage = '%s'", self.name, location_usage)
                return

            # 1) Kiểm tra cấu hình riêng theo kho
            warehouse_code = self.picking_type_id.warehouse_id.code
            warehouse_recipients = config.get_recipients_for_incoming_warehouse(warehouse_code)
            
            if warehouse_recipients:
                 recipient_user_ids = warehouse_recipients
                 _logger.debug("Using warehouse-specific recipients for %s: %s", warehouse_code, recipient_user_ids)
            else:
                 # 2) Fallback về global config
                 accountant_user_id = config.incoming_recipient_user_id
                 if not accountant_user_id:
                     _logger.warning("Zalo Notification not sent: incoming_recipient_user_id not configured")
                     return
                 recipient_user_ids = [accountant_user_id]

        else:
            _logger.info("Zalo Notification skip: picking %s has unsupported picking_type_code=%s", self.name, self.picking_type_code)
            return

        # ==============================================================================
        # 2. FIX LOGIC: KHỬ TRÙNG LẶP TUYỆT ĐỐI (Normalize String)
        # ==============================================================================
        # Chuyển tất cả về string và xóa khoảng trắng để đảm bảo '123' trùng với 123
        cleaned_recipients = []
        for uid in recipient_user_ids:
            if uid:
                # Ép kiểu string và xóa khoảng trắng thừa
                cleaned_recipients.append(str(uid).strip())
        
        # Dùng dict.fromkeys để loại bỏ trùng lặp (giữ thứ tự)
        recipient_user_ids = list(dict.fromkeys(cleaned_recipients))
        
        # Log recap
        if self.picking_type_code == "outgoing":
            _logger.info("Zalo Stock Notification: OUTGOING picking %s, saler_code=%s, recipients=%s", self.name, saler_code, recipient_user_ids)
        else:
            _logger.info("Zalo Stock Notification: INCOMING picking %s, recipients=%s", self.name, recipient_user_ids)

        # ==============================================================================
        # CHUẨN BỊ NỘI DUNG VÀ GỬI TIN
        # ==============================================================================
        
        # Format message
        try:
            message_text = self._format_zalo_notification_message()
        except Exception as e:
            _logger.exception("Error formatting Zalo Notification message for %s: %s", self.name, e)
            return

        # Lấy access token
        try:
            access_token = config.get_valid_access_token()
            if not access_token:
                _logger.error("Zalo Config for picking %s has no valid access_token.", self.name)
                return
        except Exception as e:
            _logger.exception("Error getting access token for picking %s: %s", self.name, e)
            return

        # Check expire
        if config.token_expires_at:
            from datetime import datetime
            from dateutil import parser
            expires_at = config.token_expires_at
            if isinstance(expires_at, str):
                expires_at = parser.parse(expires_at)
            if expires_at < datetime.now():
                _logger.warning("Zalo access_token expired at %s. Refresh may be needed.", config.token_expires_at)

        # ===== Gửi tin nhắn =====
        any_success = False

        for uid in recipient_user_ids:
            try:
                result = config.send_notification_message(uid, message_text)

                if not result:
                    _logger.error("Zalo Notification: No response for user_id %s", uid)
                    continue

                error_code = result.get("error")

                if error_code == 0:
                    any_success = True
                    _logger.info("✓ Zalo Notification sent successfully to %s for picking %s", uid, self.name)
                else:
                    _logger.error("✗ Zalo Notification failed to %s for picking %s. Error code: %s", uid, self.name, error_code)
            
            except Exception as e:
                _logger.exception("✗ Exception sending Zalo Notification to %s: %s", uid, str(e))

        # Nếu gửi được ít nhất 1 người thì mark đã gửi
        if any_success:
            self.sudo().write({"zalo_stock_notification_sent": True})
            # Lưu ý: Khi hàm kết thúc, Transaction Commit -> SQL Lock tự động được nhả ra.

    def button_validate(self):
        """
        Override button_validate để gửi thông báo Zalo Stock Notification
        khi đơn hàng được validate
        
        === TỰ ĐỘNG GỬI THÔNG BÁO KHI VALIDATE ===
        
        Điều kiện để gửi thông báo:
        1. Đơn hàng đã validate thành công (state = 'done')
        2. Loại đơn phải là incoming (nhập) hoặc outgoing (xuất)
        3. Có config Zalo Stock Notification active
        4. Config đã bật gửi cho loại đơn này (send_on_incoming/send_on_outgoing)
        5. Chưa gửi thông báo trước đó (zalo_stock_notification_sent = False)
        6. Với outgoing: location_dest_id.usage = 'customer' (chỉ gửi xuất cuối cùng tới khách)
        7. Kho phải được cấu hình (warehouse mapping) hoặc có recipients mặc định
        
        Lỗi khi gửi thông báo sẽ được log nhưng KHÔNG block việc validate đơn hàng.
        
        Định dạng tin nhắn khác nhau cho incoming/outgoing:
        - Outgoing: Lấy dữ liệu từ sale.order, nhân viên từ picking_type
        - Incoming: Lấy dữ liệu từ purchase.order, nhân viên từ picking.user_id
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
