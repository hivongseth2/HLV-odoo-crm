# models/zalo_stock_notification_config.py
import logging
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloStockNotificationConfig(models.Model):
    """
    Cấu hình Zalo OA để gửi thông báo tới nhân viên nội bộ
    khi có đơn hàng nhập/xuất kho
    
    === HƯỚNG DẪN SỬ DỤNG ===
    
    1. CÀI ĐẶT:
       - Vào Inventory > Configuration > Zalo Stock Notification
       - Tạo bản ghi mới với thông tin:
         + App ID: Lấy từ Zalo Developer Portal
         + Secret Key: Lấy từ Zalo Developer Portal
         + Refresh Token: Lấy từ OAuth flow của Zalo
         + Recipient User IDs (tùy chọn): Nhập các Zalo User ID mặc định (mỗi ID một dòng)
           VD: 1228622149344688972
       - Chọn loại đơn cần gửi (Nhập/Xuất)
       - (Tùy chọn) Thêm cấu hình mapping kho:
         + Warehouse Code: Mã kho (TSN, TSNSR, KBC, ...)
         + Recipient User IDs: Danh sách user_id nhận thông báo cho kho đó
         + Active: Bật/tắt cấu hình
       - Đánh dấu Active
    
    2. ĐIỀU KIỆN GỬI THÔNG BÁO:
       - Đơn hàng đã validate (state = 'done')
       - Loại đơn: incoming (nhập) hoặc outgoing (xuất)
       - Kho phải có cấu hình trong warehouse_recipient_ids hoặc sử dụng danh sách mặc định
       - Chưa gửi thông báo trước đó (zalo_stock_notification_sent = False)
    
    3. LOGIC LẤY RECIPIENTS:
       a) Hệ thống sẽ lấy mã kho từ picking_type_id.warehouse_id.code
       b) Tìm kiếm warehouse mapping có warehouse_code matching và active=True
       c) Nếu tìm thấy → Sử dụng danh sách recipients từ warehouse mapping đó
       d) Nếu không tìm thấy → Sử dụng danh sách recipients mặc định (recipient_ids field)
    
    4. NỘI DUNG THÔNG BÁO:
       - Mã đơn hàng gốc (origin)
       - Trạng thái: Xuất/Nhập toàn bộ hay 1 phần
       - Thời gian xuất/nhập
       - Thông tin đối tác (tên, địa chỉ, SĐT)
       - Danh sách sản phẩm và số lượng
    
    5. TOKEN MANAGEMENT:
       - Access token tự động refresh khi hết hạn
       - Cron job chạy mỗi giờ để refresh token
       - Có thể refresh thủ công bằng button "Refresh Token"
    
    6. TEST:
       - Sau khi cấu hình, click "Test Gửi Tin Nhắn"
       - Kiểm tra Recipient User IDs có nhận được tin không
       - Nếu OK, validate một đơn nhập/xuất kho để test thật
    
    7. DEBUG:
       - Xem logs: grep "Zalo" trong odoo log file
       - Check zalo_stock_notification_sent field trong stock.picking
       - Verify warehouse code: picking_type_id.warehouse_id.code
       - Kiểm tra warehouse mapping: warehouse_recipient_ids
    """
    _name = 'hlv.zalo.stock.notification'
    _description = 'Zalo Stock Notification Config'

    name = fields.Char(default='Zalo Stock Notification', required=True)
    
    # ===== NEW: Option to use Shared Token =====
    use_shared_token = fields.Boolean(
        'Use Shared Token',
        default=True,
        help='Nếu bật, sẽ sử dụng token từ Shared Token Manager thay vì token riêng'
    )
    
    oa_secret_key = fields.Char(
        'OA Secret Key (Webhook)', 
        help='Key dùng để verify webhook. Copy từ màn hình Webhook trên Zalo Developer.'
    )
    
    # ===== OLD: Deprecated token fields (kept for backward compatibility) =====
    app_id = fields.Char('App ID', default='', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    secret_key = fields.Char('Secret Key', default='', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    callback_url = fields.Char('OAuth Callback URL', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    refresh_token = fields.Text('Refresh Token', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    access_token = fields.Text('Access Token', help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    token_expires_at = fields.Datetime('Token Expires At', readonly=True, help='[DEPRECATED] Sử dụng Shared Token Manager thay thế')
    authorize_url = fields.Char('Authorize URL', compute='_compute_authorize_url', readonly=True)
    
    # Danh sách user_id cần gửi thông báo (mỗi dòng một ID)
    recipient_ids = fields.Text(
        'Recipient User IDs',
        default='1228622149344688972',
        help='Danh sách Zalo User ID cần nhận thông báo, mỗi ID một dòng'
    )
    
    # Cấu hình gửi cho loại đơn nào
    send_on_incoming = fields.Boolean('Gửi khi nhập kho', default=True)
    send_on_outgoing = fields.Boolean('Gửi khi xuất kho', default=True)
    
    # Mapping kho với danh sách recipients
    warehouse_recipient_ids = fields.One2many(
        'hlv.zalo.warehouse.recipient',
        'config_id',
        'Warehouse Recipients',
        help='Map kho (TSN, TSNSR, KBC, ...) với danh sách user_id nhận thông báo'
    )
    
    # Mapping mã nhân viên sale với danh sách recipients
    saler_recipient_ids = fields.One2many(
        'hlv.zalo.saler.recipient',
        'config_id',
        'Saler Recipients',
        help='Map mã nhân viên sale (BACHTHIKIMTHUY, ...) với danh sách user_id nhận thông báo'
    )
    
    
        # ===================== Mapping saler_code -> Zalo User IDs =====================
    saler_mapping_text = fields.Text(
        'Mapping MISA saler_code → Zalo User ID',
        help=(
            "Danh sách mapping giữa mã nhân viên sale MISA (x_studio_misa_saler_code) "
            "và Zalo OA user_id.\n"
            "Mỗi dòng 1 cấu hình, dạng: MISA_CODE:ID1,ID2,...\n"
            "Ví dụ:\n"
            "DUONGTHIHA:4954993286556475779\n"
            "NGUYENVANA:1111111111111111111,2222222222222222222"
        ),
    )

    def _parse_saler_mapping_text(self):
        """
        Parse text saler_mapping_text thành dict:
        {
          'DUONGTHIHA': ['4954993286556475779'],
          'NGUYENVANA': ['1111...', '2222...']
        }
        """
        self.ensure_one()
        mapping = {}
        if not self.saler_mapping_text:
            return mapping

        for raw_line in self.saler_mapping_text.splitlines():
            line = (raw_line or '').strip()
            if not line:
                continue

            # Cho phép có dấu phẩy ở cuối dòng
            if line.endswith(','):
                line = line[:-1].strip()

            if ':' not in line:
                _logger.debug("Skip invalid saler mapping line: %s", line)
                continue

            code_part, ids_part = line.split(':', 1)
            code = (code_part or '').strip().upper()
            if not code:
                continue

            # Cho phép phân cách ID bằng ',' hoặc ';'
            ids_raw = (ids_part or '').replace(';', ',')
            user_ids = []
            for chunk in ids_raw.split(','):
                uid = chunk.strip().strip("'").strip('"')
                if uid:
                    user_ids.append(uid)

            if user_ids:
                mapping[code] = user_ids

        return mapping

    def get_saler_user_ids_from_mapping(self, saler_code):
        """
        Lấy danh sách user_id Zalo từ field saler_mapping_text
        theo mã MISA saler_code.
        """
        self.ensure_one()
        if not saler_code:
            return []

        norm_code = str(saler_code).strip().upper()
        mapping = self._parse_saler_mapping_text()
        return mapping.get(norm_code, [])

    
    # ===== NEW: Cơ chế saler online/offline =====
    # Danh sách mã saler online (mỗi dòng một mã)
    online_saler_codes = fields.Text(
        'Mã Nhân Viên Sale Online',
        default='',
        help='Danh sách mã nhân viên sale phụ trách bán online (mỗi mã một dòng). '
             'Ví dụ: SALER_ONLINE_1, SALER_ONLINE_2, ...'
    )
    
    # User ID nhận thông báo cho đơn hàng online
    online_recipient_user_id = fields.Char(
        'User ID Kế Toán Online',
        default='',
        help='Zalo User ID của kế toán xử lý đơn hàng online. '
             'Đơn hàng có saler_code nằm trong danh sách online sẽ gửi tới user_id này'
    )
    
    # User ID nhận thông báo cho đơn hàng offline
    offline_recipient_user_id = fields.Char(
        'User ID Kế Toán Offline',
        default='',
        help='Zalo User ID của kế toán xử lý đơn hàng offline. '
             'Đơn hàng có saler_code KHÔNG nằm trong danh sách online sẽ gửi tới user_id này'
    )
    
    # User ID nhận thông báo cho đơn nhập kho
    incoming_recipient_user_id = fields.Char(
        'User ID Kế Toán Nhập Kho',
        default='',
        help='Zalo User ID của kế toán xử lý TẤT CẢ đơn nhập kho (nếu không cấu hình riêng theo kho). '
             'Phiếu nhập kho sẽ gửi thông báo tới user_id này'
    )
    cancel_so_warehouse_mapping_text = fields.Text(
            'Mapping Kho Hủy SO → Zalo ID',
            help=(
                "Danh sách mapping giữa Mã Kho (Warehouse Code) và Zalo User ID nhận tin khi HỦY SO.\n"
                "Mỗi dòng 1 cấu hình, dạng: WAREHOUSE_CODE:ID1,ID2,...\n"
                "Ví dụ:\n"
                "TSN:1111111111111111111\n"
                "KBC:2222222222222222222"
            ),
        )
    incoming_warehouse_mapping_text = fields.Text(
        'Mapping Kho Nhập → Zalo ID',
        help=(
            "Danh sách mapping giữa Mã Kho (Warehouse Code) và Zalo User ID.\n"
            "Mỗi dòng 1 cấu hình, dạng: WAREHOUSE_CODE:ID1,ID2,...\n"
            "Ví dụ:\n"
            "TSN:1111111111111111111\n"
            "KBC:2222222222222222222,3333333333333333333"
        ),
    )
    
    def _parse_cancel_so_warehouse_mapping(self):
        """Parse text cancel_so_warehouse_mapping_text thành dict"""
        self.ensure_one()
        mapping = {}
        if not self.cancel_so_warehouse_mapping_text:
            return mapping

        for raw_line in self.cancel_so_warehouse_mapping_text.splitlines():
            line = (raw_line or '').strip()
            if not line or line.startswith('#'): continue
            if ':' not in line: continue

            code_part, ids_part = line.split(':', 1)
            code = (code_part or '').strip().upper()
            if not code: continue

            ids_raw = (ids_part or '').replace(';', ',')
            user_ids = [u.strip().strip("'").strip('"') for u in ids_raw.split(',') if u.strip()]

            if user_ids:
                mapping[code] = user_ids
        return mapping

    def send_cancel_so_notification(self, sale_order):
        """
        Gửi thông báo Zalo khi đơn hàng bị hủy.
        Gửi cho:
        1. Thủ kho (dựa trên các kho liên quan).
        2. Nhân viên Sale (dựa trên mapping sale code).
        """
        self.ensure_one()
        if not sale_order:
            return

        # ============================================================
        # PHẦN 1: GỬI CHO THỦ KHO (Logic cũ)
        # ============================================================
        
        # 1. Xác định các kho liên quan
        warehouses = set()
        if sale_order.picking_ids:
            for picking in sale_order.picking_ids:
                if picking.picking_type_id.warehouse_id:
                    warehouses.add(picking.picking_type_id.warehouse_id)
        
        # Fallback: Nếu chưa có picking, lấy kho trên header SO
        if not warehouses and sale_order.warehouse_id:
            warehouses.add(sale_order.warehouse_id)

        # Lấy mapping cấu hình kho
        wh_mapping = self._parse_cancel_so_warehouse_mapping()

        if warehouses and wh_mapping:
            for wh in warehouses:
                wh_code = (wh.code or '').strip().upper()
                wh_recipient_ids = wh_mapping.get(wh_code, [])

                if not wh_recipient_ids:
                    continue
                
                # Nội dung cho kho (nhấn mạnh việc dừng xuất hàng)
                msg_warehouse = (
                    f"❌ ĐƠN HÀNG ĐÃ HỦY\n"
                    f"--------------------\n"
                    f"📦 Mã đơn: {sale_order.name}\n"
                    f"🏭 Kho: {wh.name}\n"
                    f"👤 Khách hàng: {sale_order.partner_id.name}\n"
                    f"--------------------\n"
                    f"⚠️ Vui lòng kiểm tra lại đơn và DỪNG xuất hàng ngay."
                )

                for uid in wh_recipient_ids:
                    try:
                        result = self.send_notification_message(uid, msg_warehouse) or {}
                        if result.get('error') == 0:
                            _logger.info("Sent Cancel SO msg to Warehouse Staff %s (WH: %s)", uid, wh_code)
                        else:
                            _logger.warning(
                                "Failed Cancel SO msg to Warehouse Staff %s (WH: %s): %s",
                                uid, wh_code, result,
                            )
                    except Exception as e:
                        _logger.exception("Error sending to WH staff %s: %s", uid, e)

        # ============================================================
        # PHẦN 2: GỬI CHO SALE (Mới thêm)
        # ============================================================
        
        # Lấy mã nhân viên sale từ SO
        saler_code = getattr(sale_order, 'x_studio_misa_saler_code', False)
        
        if saler_code:
            # Tận dụng hàm có sẵn để lấy list ID từ mapping text
            saler_zalo_ids = self.get_saler_user_ids_from_mapping(saler_code)
            
            if saler_zalo_ids:
                # Nội dung cho Sale (Thông báo trạng thái)
                # Lấy tên kho chính để hiển thị
                main_wh_name = sale_order.warehouse_id.name or "N/A"
                
                msg_sale = (
                    f"ℹ️ THÔNG BÁO HỦY ĐƠN\n"
                    f"--------------------\n"
                    f"📦 Mã đơn: {sale_order.name}\n"
                    f"👤 Mã Sale: {saler_code}\n"
                    f"🏭 Kho: {main_wh_name}\n"
                    f"👤 Khách hàng: {sale_order.partner_id.name}\n"
                    f"--------------------\n"
                    f"Đơn hàng đã được cập nhật trạng thái HỦY trên ODOO."
                )

                for uid in saler_zalo_ids:
                    try:
                        result = self.send_notification_message(uid, msg_sale) or {}
                        if result.get('error') == 0:
                            _logger.info("Sent Cancel SO msg to Salesperson %s (Code: %s)", uid, saler_code)
                        else:
                            _logger.warning(
                                "Failed Cancel SO msg to Salesperson %s (Code: %s): %s",
                                uid, saler_code, result,
                            )
                    except Exception as e:
                        _logger.exception("Error sending to Salesperson %s: %s", uid, e)
            else:
                _logger.info("Cancel SO: No Zalo ID mapping found for saler_code %s", saler_code)

    def send_so_warehouse_notification(self, sale_order, title, detail=None):
        """Gửi thông báo thay đổi SO tới người nhận Zalo của các kho liên quan."""
        self.ensure_one()
        if not sale_order:
            return {'sent': 0, 'failed': 0, 'skipped': 'missing_sale_order'}

        warehouses = sale_order.picking_ids.mapped('picking_type_id.warehouse_id').filtered(bool)
        if not warehouses and sale_order.warehouse_id:
            warehouses = sale_order.warehouse_id

        if not warehouses:
            _logger.warning("SO warehouse notification skipped for %s: no warehouse", sale_order.name)
            return {'sent': 0, 'failed': 0, 'skipped': 'missing_warehouse'}

        text_mapping = self._parse_cancel_so_warehouse_mapping()
        default_recipients = self.get_recipient_list()
        sent = 0
        failed = 0

        for warehouse in warehouses:
            warehouse_code = (warehouse.code or '').strip().upper()
            recipient_ids = list(text_mapping.get(warehouse_code, []))

            if not recipient_ids:
                warehouse_mapping = self.warehouse_recipient_ids.filtered(
                    lambda mapping: mapping.active and mapping.warehouse_id == warehouse
                )[:1]
                if warehouse_mapping:
                    recipient_ids = warehouse_mapping.get_recipient_list()

            if not recipient_ids:
                recipient_ids = list(default_recipients)

            recipient_ids = list(dict.fromkeys(
                str(user_id).strip() for user_id in recipient_ids if user_id
            ))
            if not recipient_ids:
                _logger.warning(
                    "SO warehouse notification skipped for %s (WH: %s): no recipients",
                    sale_order.name, warehouse_code,
                )
                continue

            message_text = (
                f"⚠️ YÊU CẦU THAY ĐỔI ĐƠN HÀNG\n"
                f"--------------------\n"
                f"📦 Mã đơn: {sale_order.name}\n"
                f"🏭 Kho: {warehouse.name}\n"
                f"👤 Khách hàng: {sale_order.partner_id.name}\n"
                f"📣 Nội dung: {title}\n"
            )
            if detail:
                message_text += f"--------------------\n{detail}"

            for user_id in recipient_ids:
                result = self.send_notification_message(user_id, message_text) or {}
                if result.get('error') == 0:
                    sent += 1
                    _logger.info(
                        "Sent SO warehouse change msg to %s for %s (WH: %s)",
                        user_id, sale_order.name, warehouse_code,
                    )
                else:
                    failed += 1
                    _logger.warning(
                        "Failed SO warehouse change msg to %s for %s (WH: %s): %s",
                        user_id, sale_order.name, warehouse_code, result,
                    )

        return {'sent': sent, 'failed': failed}

    def _parse_incoming_warehouse_mapping(self):
        """
        Parse text incoming_warehouse_mapping_text thành dict:
        {
          'TSN': ['1111...'],
          'KBC': ['2222...', '3333...']
        }
        """
        self.ensure_one()
        mapping = {}
        if not self.incoming_warehouse_mapping_text:
            return mapping

        for raw_line in self.incoming_warehouse_mapping_text.splitlines():
            line = (raw_line or '').strip()
            if not line or line.startswith('#'): continue
            if ':' not in line: continue

            code_part, ids_part = line.split(':', 1)
            code = (code_part or '').strip().upper()
            if not code: continue

            ids_raw = (ids_part or '').replace(';', ',')
            user_ids = [u.strip().strip("'").strip('"') for u in ids_raw.split(',') if u.strip()]

            if user_ids:
                mapping[code] = user_ids
        return mapping

    def get_recipients_for_incoming_warehouse(self, warehouse_code):
        """
        Lấy danh sách user_id Zalo từ field incoming_warehouse_mapping_text
        theo mã kho (warehouse_code).
        
        Nếu không tìm thấy mapping riêng cho kho, trả về [] (để fallback về global).
        """
        self.ensure_one()
        if not warehouse_code:
            return []

        norm_code = str(warehouse_code).strip().upper()
        mapping = self._parse_incoming_warehouse_mapping()
        
        # Tìm chính xác theo code
        if norm_code in mapping:
             return mapping[norm_code]
        return []

    # ===================== NEW: Cấu hình gửi tin nhắn khi TẠO ĐƠN MUA HÀNG =====================
    send_on_po_create = fields.Boolean('Gửi khi tạo đơn mua hàng', default=True)

    po_create_recipient_user_id = fields.Char(
        'User ID nhận thông báo PO Mới',
        default='',
        help='Zalo User ID nhận thông báo khi đơn mua hàng MỚI được tạo (trước khi validate)'
    )

    po_create_warehouse_mapping_text = fields.Text(
        'Mapping Kho PO → Zalo ID',
        help=(
            "Danh sách mapping giữa Mã Kho (Warehouse Code) và Zalo User ID cho đơn PO mới.\n"
            "Mỗi dòng 1 cấu hình, dạng: WAREHOUSE_CODE:ID1,ID2,...\n"
            "Nếu kho của PO có trong này, sẽ gửi cho ID tương ứng, ngược lại fallback về global ID."
        ),
    )

    def _parse_po_create_warehouse_mapping(self):
        """Parse text po_create_warehouse_mapping_text thành dict"""
        self.ensure_one()
        mapping = {}
        if not self.po_create_warehouse_mapping_text:
            return mapping

        for raw_line in self.po_create_warehouse_mapping_text.splitlines():
            line = (raw_line or '').strip()
            if not line or line.startswith('#'): continue
            if ':' not in line: continue

            code_part, ids_part = line.split(':', 1)
            code = (code_part or '').strip().upper()
            if not code: continue

            ids_raw = (ids_part or '').replace(';', ',')
            user_ids = [u.strip().strip("'").strip('"') for u in ids_raw.split(',') if u.strip()]

            if user_ids:
                mapping[code] = user_ids
        return mapping

    def get_recipients_for_po_create(self, warehouse_code):
        """Lấy recipients cho PO create theo kho"""
        self.ensure_one()
        if not warehouse_code:
            return []
        norm_code = str(warehouse_code).strip().upper()
        mapping = self._parse_po_create_warehouse_mapping()
        return mapping.get(norm_code, [])



    # ===== Cấu hình gửi tin nhắn nhắc nhở tương tác =====
    enable_interaction_reminder = fields.Boolean(
        'Bật nhắc nhở tương tác',
        default=False,
        help='Bật tính năng gửi tin nhắn nhắc nhở người dùng tương tác với OA '
             'để tránh bị ngừng nhận tin nhắn (do Zalo yêu cầu tương tác trong 7 ngày)'
    )

    reminder_interval_days = fields.Integer(
        'Khoảng cách gửi (ngày)',
        default=5,
        help='Số ngày giữa mỗi lần gửi tin nhắn nhắc nhở. '
             'Khuyến nghị: 5 ngày (để đảm bảo trước thời hạn 7 ngày của Zalo)'
    )

    reminder_message_template = fields.Text(
        'Nội dung tin nhắn nhắc nhở',
        default='''🔔 NHẮC NHỞ TƯƠNG TÁC ZALO OA

Xin chào! Đây là tin nhắn tự động từ hệ thống HLV.

Để tiếp tục nhận thông báo về đơn hàng qua Zalo, vui lòng phản hồi tin nhắn này (có thể gõ bất kỳ nội dung nào, ví dụ: "OK", "Đã nhận"...).

⚠️ Lưu ý: Theo chính sách của Zalo, nếu bạn không tương tác trong 7 ngày, hệ thống sẽ tạm ngừng gửi tin nhắn.

Cảm ơn bạn!''',
        help='Nội dung tin nhắn nhắc nhở. Có thể sử dụng biến: {date} - ngày gửi'
    )

    last_reminder_sent = fields.Datetime(
        'Lần gửi nhắc nhở cuối',
        readonly=True,
        help='Thời điểm gửi tin nhắn nhắc nhở cuối cùng'
    )

    active = fields.Boolean('Active', default=True)

    @api.model
    def _get_active_config(self):
        """Lấy config đang active"""
        return self.search([('active', '=', True)], limit=1)

    # -------------------- OAuth permission URL --------------------
    @api.depends('app_id', 'callback_url')
    def _compute_authorize_url(self):
        """Tính toán URL để authorize với Zalo"""
        for rec in self:
            if rec.app_id and rec.callback_url:
                from urllib.parse import quote
                rec.authorize_url = (
                    "https://oauth.zaloapp.com/v4/oa/permission"
                    f"?app_id={rec.app_id}&redirect_uri={quote(rec.callback_url, safe='')}"
                    "&state=odoo_stock_notification"
                )
            else:
                rec.authorize_url = False

    def action_open_oauth(self):
        """Mở URL để authorize với Zalo"""
        self.ensure_one()
        if not self.authorize_url:
            raise UserError(_("Missing app_id or callback_url"))
        return {"type": "ir.actions.act_url", "target": "new", "url": self.authorize_url}

    def request_access_token_with_code(self, code):
        """Exchange authorization code -> access_token & refresh_token"""
        self.ensure_one()
        endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
        data = {
            'grant_type': 'authorization_code',
            'app_id': self.app_id,
            'code': code,
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'secret_key': self.secret_key,
        }

        try:
            _logger.info("Exchanging authorization code for access token...")
            response = requests.post(endpoint, data=data, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()

            access_token = result.get('access_token')
            refresh_token = result.get('refresh_token')
            
            if not access_token:
                error_msg = result.get('error_description', 'Unknown error')
                _logger.error("Failed to get access token: %s", error_msg)
                raise UserError(_("Không thể lấy access token: %s") % error_msg)

            expires_in = int(result.get('expires_in', 3600))
            self.write({
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
            })
            
            _logger.info("Zalo Stock Notification tokens obtained successfully (expires_in=%s)", expires_in)
            return result
            
        except requests.exceptions.RequestException as e:
            _logger.exception("Failed to request access token: %s", e)
            raise UserError(_("Lỗi kết nối Zalo API: %s") % str(e))
        except Exception as e:
            _logger.exception("Unexpected error requesting access token: %s", e)
            raise UserError(_("Lỗi không mong muốn: %s") % str(e))

    def _is_token_expired(self):
        """Kiểm tra token đã hết hạn chưa"""
        self.ensure_one()
        if not self.token_expires_at:
            return True
        # Thêm buffer 60s để tránh token hết hạn giữa chừng
        return fields.Datetime.now() >= (self.token_expires_at - timedelta(seconds=60))

    def _get_advisory_lock_id(self):
        """
        Tạo advisory lock ID cho bản ghi này.
        Advisory lock dùng để tránh race condition khi multiple workers refresh token cùng lúc.
        
        Sử dụng ID của config record làm lock ID (hash để fit trong int range của PG).
        """
        self.ensure_one()
        # PostgreSQL advisory lock dùng 2 int64, chúng ta chỉ dùng 1 với config.id
        # Để an toàn, dùng hash của 'hlv.zalo.stock.notification' + config.id
        return hash(('hlv.zalo.stock.notification', self.id)) & 0x7FFFFFFF

    def ensure_valid_token(self):
        """
        On-demand token refresh: Kiểm tra token còn hợp lệ không, 
        nếu hết hạn thì refresh ngay với advisory lock.
        
        Quy trình:
        1. Kiểm tra token hết hạn (_is_token_expired())
        2. Nếu hết hạn, cố gắng lấy advisory lock (non-blocking)
        3. Nếu lấy được lock → gọi refresh_access_token() → release lock
        4. Nếu không lấy được lock (có process khác đang refresh) → log warning và tiếp tục
        
        Điều này giúp:
        - Refresh token ngay khi phát hiện hết hạn (không phải chờ cron)
        - Tránh multiple processes refresh cùng lúc
        - Giữ cron 1h làm fallback nếu on-demand fail
        
        :return: True nếu token hợp lệ (hoặc vừa refresh xong), False nếu có lỗi
        """
        self.ensure_one()
        
        if not self._is_token_expired():
            _logger.debug("Zalo Stock Notification config %s: token still valid", self.id)
            return True
        
        _logger.warning("Zalo Stock Notification config %s: token expired, attempting on-demand refresh", self.id)
        
        try:
            # Lấy PostgreSQL advisory lock (non-blocking)
            lock_id = self._get_advisory_lock_id()
            
            # Sử dụng raw SQL để gọi pg_try_advisory_lock
            # Nếu lấy được lock (return true) -> refresh token
            # Nếu không lấy được (return false) -> có process khác đang refresh -> log và skip
            self.env.cr.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (lock_id,)
            )
            lock_acquired = self.env.cr.fetchone()[0]
            
            if not lock_acquired:
                _logger.warning(
                    "Zalo Stock Notification config %s: could not acquire lock "
                    "(another process might be refreshing), skipping on-demand refresh",
                    self.id
                )
                return False
            
            try:
                _logger.info(
                    "Zalo Stock Notification config %s: acquired lock, starting on-demand refresh",
                    self.id
                )
                self.refresh_access_token()
                _logger.info(
                    "Zalo Stock Notification config %s: on-demand refresh completed successfully",
                    self.id
                )
                return True
                
            finally:
                # Luôn release lock dù có lỗi hay không
                self.env.cr.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (lock_id,)
                )
                _logger.debug(
                    "Zalo Stock Notification config %s: lock released",
                    self.id
                )
        
        except Exception as e:
            _logger.exception(
                "Zalo Stock Notification config %s: error during on-demand refresh: %s",
                self.id, e
            )
            return False

    def refresh_access_token(self):
        """Refresh access token using refresh_token (tương tự ZNS)"""
        for rec in self:
            if not rec.refresh_token:
                _logger.warning("No refresh token for config %s", rec.name)
                continue
            try:
                endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
                data = {
                    'grant_type': 'refresh_token',
                    'app_id': rec.app_id,
                    'refresh_token': rec.refresh_token,
                }
                headers = {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'secret_key': rec.secret_key,
                }
                _logger.info("Refreshing access token for config %s...", rec.name)
                response = requests.post(endpoint, data=data, headers=headers, timeout=15)
                response.raise_for_status()
                result = response.json()
                
                access_token = result.get('access_token')
                if not access_token:
                    error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                    _logger.error("Failed to refresh token for %s: %s", rec.name, error_msg)
                    continue
                
                expires_in = int(result.get('expires_in', 3600))
                rec.write({
                    'access_token': access_token,
                    'refresh_token': result.get('refresh_token', rec.refresh_token),
                    'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
                })
                _logger.info("Access token refreshed successfully for %s", rec.name)
            except Exception as e:
                _logger.exception("Failed to refresh access token for %s: %s", rec.name, e)

    def refresh_zalo_access_token(self):
        """
        Deprecated: Use refresh_access_token() instead
        Kept for backward compatibility
        """
        self.refresh_access_token()
        """
        Refresh access token từ Zalo OAuth v4
        Tương đương với refresh_zalo_token_if_needed() trong PHP
        
        === CÁCH LẤY REFRESH TOKEN ===
        
        1. Truy cập Zalo Developer Portal: https://developers.zalo.me/
        2. Chọn ứng dụng (App) của bạn
        3. Vào phần OAuth Settings
        4. Thực hiện OAuth flow để lấy authorization code
        5. Exchange code để lấy access_token và refresh_token
        6. Lưu refresh_token vào config này
        
        === AUTO REFRESH ===
        
        - Hệ thống tự động refresh khi access token hết hạn
        - Cron job chạy mỗi giờ để refresh token
        - Có thể refresh thủ công bằng button "Refresh Token" trên form
        
        === TROUBLESHOOTING ===
        
        Nếu refresh thất bại:
        - Kiểm tra App ID và Secret Key có đúng không
        - Kiểm tra Refresh Token còn hợp lệ không (có thể hết hạn sau 90 ngày)
        - Kiểm tra OA còn active không
        - Xem logs để biết error code cụ thể
        """
        self.ensure_one()
        
        # Validate required fields
        if not self.refresh_token:
            raise UserError(_("Refresh token không được để trống"))
        if not self.app_id:
            raise UserError(_("App ID không được để trống"))
        if not self.secret_key:
            raise UserError(_("Secret Key không được để trống"))

        try:
            endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
            
            headers = {
                'secret_key': self.secret_key,
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            data = {
                'app_id': self.app_id,
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }
            
            _logger.info("Refreshing Zalo Stock Notification access token...")
            response = requests.post(endpoint, headers=headers, data=data, timeout=15)
            
            # Parse response first before checking status
            try:
                result = response.json()
            except ValueError as e:
                _logger.error("Invalid JSON response from Zalo API: %s", response.text[:200])
                raise UserError(_("Zalo API trả về dữ liệu không hợp lệ"))
            
            # Check for HTTP errors
            if response.status_code != 200:
                error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                _logger.error("Zalo API HTTP %s: %s", response.status_code, error_msg)
                raise UserError(_("Lỗi Zalo API (HTTP %s): %s") % (response.status_code, error_msg))
            
            if result.get('access_token'):
                new_access_token = result['access_token']
                new_refresh_token = result.get('refresh_token', self.refresh_token)
                expires_in = int(result.get('expires_in', 3600))
                
                self.write({
                    'access_token': new_access_token,
                    'refresh_token': new_refresh_token,
                    'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in)
                })
                
                _logger.info("Zalo Stock Notification access token refreshed successfully (expires_in=%s)", expires_in)
                return new_access_token
            else:
                error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                _logger.error("Zalo Stock Notification token refresh failed: %s", error_msg)
                raise UserError(_("Không thể refresh Zalo token: %s") % error_msg)
                
        except requests.exceptions.RequestException as e:
            _logger.exception("Zalo Stock Notification token refresh request failed: %s", e)
            raise UserError(_("Lỗi kết nối Zalo API: %s") % str(e))
        except UserError:
            # Re-raise UserError as-is
            raise
        except Exception as e:
            _logger.exception("Unexpected error refreshing Zalo token: %s", e)
            raise UserError(_("Lỗi không mong muốn: %s") % str(e))

    def get_valid_access_token(self):
        """
        Lấy access token hợp lệ - Ưu tiên từ Shared Token Manager
        
        === CẬP NHẬT: Hỗ trợ Shared Token ===
        - Nếu use_shared_token = True: Lấy token từ Shared Token Manager
        - Nếu use_shared_token = False: Sử dụng token riêng (cũ)
        
        :return: access_token (string) hoặc False
        """
        self.ensure_one()
        
        if self.use_shared_token:
            # Sử dụng Shared Token Manager
            _logger.debug("Stock Notification Config: Using Shared Token Manager")
            access_token = self.env['hlv.zalo.shared.token']._get_shared_token()
            if access_token:
                return access_token
            else:
                _logger.warning("Stock Notification Config: Shared Token not available, falling back to own token")
        
        # Fallback: Sử dụng token riêng (backward compatibility)
        if not self.access_token or self._is_token_expired():
            return self.refresh_zalo_access_token()
        
        return self.access_token

    def send_notification_message(self, user_id, message_text):
        """
        Gửi tin nhắn thông báo tới một user_id cụ thể
        
        Bước 1: Gọi ensure_valid_token() (nếu dùng token riêng) hoặc lấy từ Shared Token
        Bước 2: Gửi tin nhắn tới Zalo API
        
        === CẬP NHẬT: Hỗ trợ Shared Token ===
        - Nếu use_shared_token = True: Shared Token tự động refresh
        - Nếu use_shared_token = False: Gọi ensure_valid_token() như cũ
        
        :param user_id: Zalo User ID
        :param message_text: Nội dung tin nhắn
        :return: Response dict từ Zalo API
        """
        self.ensure_one()
        
        # On-demand token refresh (chỉ cho token riêng)
        if not self.use_shared_token:
            if not self.ensure_valid_token():
                _logger.warning("Failed to ensure valid token for user_id=%s, attempting with current token", user_id)
        
        access_token = self.get_valid_access_token()
        
        if not access_token:
            _logger.error("Cannot send notification message: no valid access token")
            return {'error': 'No access token'}
        
        endpoint = 'https://openapi.zalo.me/v3.0/oa/message/cs'
        
        headers = {
            'Content-Type': 'application/json',
            'access_token': access_token
        }
        
        payload = {
            'recipient': {
                'user_id': user_id
            },
            'message': {
                'text': message_text
            }
        }
        
        try:
            _logger.info("Sending Zalo Stock Notification message to user_id=%s", user_id)
            response = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            result = response.json()
            
            if response.status_code == 200 and result.get('error') == 0:
                _logger.info("Zalo Stock Notification message sent successfully to %s", user_id)
            else:
                error_msg = result.get('message', 'Unknown error')
                _logger.warning("Zalo Stock Notification message failed: error=%s, message=%s", 
                              result.get('error'), error_msg)
            
            return result
            
        except Exception as e:
            _logger.exception("Failed to send Zalo Stock Notification message to %s: %s", user_id, e)
            return {'error': str(e)}

    def get_recipient_list(self):
        """
        Lấy danh sách recipient IDs từ text field
        
        === CÁCH LẤY ZALO USER ID ===
        
        User ID là mã định danh của user đã follow Official Account (OA).
        
        Cách 1 - Qua API GetProfile:
        - Sau khi user follow OA, gọi API GetProfile
        - User ID sẽ có trong response
        
        Cách 2 - Qua Webhook:
        - Cấu hình webhook trong Zalo Developer Portal
        - Khi user tương tác (message, follow), webhook sẽ nhận được user_id
        
        Cách 3 - Qua Zalo OA Dashboard:
        - Một số dashboard có hiển thị user_id của followers
        
        Format User ID: 
        - Là chuỗi số, VD: 1228622149344688972
        - Nhập mỗi ID trên một dòng trong field recipient_ids
        
        Lưu ý:
        - User phải đã follow OA mới gửi được tin nhắn
        - Nếu user chưa follow, API sẽ trả về lỗi
        """
        self.ensure_one()
        if not self.recipient_ids:
            return []
        
        # Split by line breaks và lọc các dòng trống
        ids = [line.strip() for line in self.recipient_ids.split('\n') if line.strip()]
        return ids

    def get_online_saler_codes(self):
        """
        Lấy danh sách mã saler online
        
        :return: List of saler codes (strings)
        """
        self.ensure_one()
        if not self.online_saler_codes:
            return []
        
        # Split by line breaks và lọc các dòng trống
        codes = [line.strip() for line in self.online_saler_codes.split('\n') if line.strip()]
        return codes

    def get_recipient_for_saler(self, saler_code):
        """
        Lấy user_id nhận thông báo dựa trên mã saler (online hoặc offline)
        
        Logic:
        - Kiểm tra saler_code có nằm trong danh sách online không
        - Nếu có → Trả về online_recipient_user_id
        - Nếu không → Trả về offline_recipient_user_id
        
        :param saler_code: Mã nhân viên sale (string)
        :return: User ID (string) hoặc rỗng nếu không tìm thấy
        """
        self.ensure_one()
        
        if not saler_code:
            _logger.debug("saler_code is empty, cannot determine recipient")
            return None
        
        online_codes = self.get_online_saler_codes()
        
        if saler_code in online_codes:
            _logger.debug("Saler %s is in online list → using online_recipient_user_id: %s", 
                         saler_code, self.online_recipient_user_id)
            return self.online_recipient_user_id
        else:
            _logger.debug("Saler %s is NOT in online list → using offline_recipient_user_id: %s", 
                         saler_code, self.offline_recipient_user_id)
            return self.offline_recipient_user_id

    # def get_recipients_for_warehouse(self, warehouse_id):
    #     """
    #     Lấy danh sách recipient IDs cho một kho cụ thể
        
    #     Nếu có cấu hình warehouse mapping, sử dụng danh sách recipients từ warehouse đó.
    #     Ngược lại, sử dụng danh sách recipients mặc định (recipient_ids field).
        
    #     :param warehouse_id: ID hoặc object của stock.warehouse
    #     :return: List of user IDs (strings)
    #     """
    #     self.ensure_one()
        
    #     if not warehouse_id:
    #         _logger.warning("warehouse_id is empty, using default recipients")
    #         return self.get_recipient_list()
        
    #     # Tìm warehouse mapping trong list
    #     warehouse_mapping = self.warehouse_recipient_ids.filtered(
    #         lambda x: x.warehouse_id.id == (warehouse_id.id if hasattr(warehouse_id, 'id') else warehouse_id) and x.active
    #     )
        
    #     if warehouse_mapping:
    #         # Sử dụng danh sách recipients từ warehouse mapping
    #         recipients = warehouse_mapping[0].get_recipient_list()
    #         warehouse_name = warehouse_mapping[0].warehouse_id.name
    #         _logger.debug(
    #             "Found warehouse mapping for %s: %s recipients",
    #             warehouse_name, len(recipients)
    #         )
    #         return recipients
    #     else:
    #         # Nếu không tìm thấy warehouse mapping, sử dụng danh sách mặc định
    #         warehouse_name = warehouse_id.name if hasattr(warehouse_id, 'name') else str(warehouse_id)
    #         _logger.debug(
    #             "No warehouse mapping found for %s, using default recipients",
    #             warehouse_name
    #         )
    #         return self.get_recipient_list()

    # def get_recipients_for_saler_old(self, saler_code):
    #     """
    #     [DEPRECATED] Phương pháp cũ: mapping từng saler thành danh sách user_id
        
    #     Lấy danh sách recipient IDs cho một mã nhân viên sale cụ thể
        
    #     Nếu có cấu hình saler mapping, sử dụng danh sách recipients từ mã nhân viên đó.
    #     Ngược lại, trả về danh sách rỗng (không gửi).
        
    #     :param saler_code: Mã nhân viên sale (string)
    #     :return: List of user IDs (strings)
    #     """
    #     self.ensure_one()
        
    #     if not saler_code:
    #         _logger.debug("saler_code is empty, no saler recipients")
    #         return []
        
    #     # Tìm saler mapping trong list
    #     saler_mapping = self.saler_recipient_ids.filtered(
    #         lambda x: x.saler_code == saler_code and x.active
    #     )
        
    #     if saler_mapping:
    #         # Sử dụng danh sách recipients từ saler mapping
    #         recipients = saler_mapping[0].get_recipient_list()
    #         _logger.debug(
    #             "Found saler mapping for %s: %s recipients",
    #             saler_code, len(recipients)
    #         )
    #         return recipients
    #     else:
    #         # Nếu không tìm thấy saler mapping, không gửi (trả về rỗng)
    #         _logger.debug(
    #             "No saler mapping found for %s",
    #             saler_code
    #         )
    #         return []

    def action_test_send_message(self):
        """
        Action button để test gửi tin nhắn với cơ chế mới (online/offline/incoming)
        """
        self.ensure_one()

        now_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        sent_user_ids = set()
        success_count = 0
        attempts = 0

        # Test gửi cho 3 user_id (online, offline, incoming)
        test_recipients = []
        
        if self.online_recipient_user_id:
            test_recipients.append((self.online_recipient_user_id, "Kế toán ONLINE (Xuất)"))
        
        if self.offline_recipient_user_id:
            test_recipients.append((self.offline_recipient_user_id, "Kế toán OFFLINE (Xuất)"))
        
        if self.incoming_recipient_user_id:
            test_recipients.append((self.incoming_recipient_user_id, "Kế toán NHẬP KHO"))
        
        if not test_recipients:
            raise UserError(_("Chưa cấu hình User ID cho kế toán (online/offline/incoming)"))
        
        for user_id, recipient_type in test_recipients:
            if user_id in sent_user_ids:
                continue
            
            test_message = (
                f"🔔 Test tin nhắn từ Odoo HLV\n"
                f"Kiểu nhận thông báo: {recipient_type}\n"
                f"Thời gian: {now_str}\n"
                "Thông điệp thử nghiệm: gửi thử cho cấu hình saler online/offline."
            )
            
            attempts += 1
            result = self.send_notification_message(user_id, test_message)
            if result.get('error') == 0:
                success_count += 1
            sent_user_ids.add(user_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gửi tin nhắn test'),
                'message': _('Đã gửi thành công %s/%s tin nhắn') % (success_count, attempts),
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': False,
            }
        }

    def action_preview_send_message(self):
        """
        Build a preview của cơ chế saler online/offline mới.
        Hiển thị danh sách mã saler online và 2 user_id nhận thông báo.
        """
        self.ensure_one()

        preview_lines = []
        
        # Hiển thị danh sách mã saler online
        online_codes = self.get_online_saler_codes()
        if online_codes:
            preview_lines.append(_('📌 Mã nhân viên sale ONLINE (%s):') % len(online_codes))
            for code in online_codes[:50]:
                preview_lines.append(f"  • {code}")
            if len(online_codes) > 50:
                preview_lines.append(f"  ... ({len(online_codes)-50} mã khác)")
            preview_lines.append('')
        else:
            preview_lines.append(_('📌 Mã nhân viên sale ONLINE: (không cấu hình)'))
            preview_lines.append('')
        
        # Hiển thị thông tin nhận thông báo
        preview_lines.append(_('📨 Cấu hình nhận thông báo:'))
        preview_lines.append('')
        preview_lines.append(_('📤 PHIẾU XUẤT KHO (Outgoing):'))
        
        if self.online_recipient_user_id:
            preview_lines.append(_('  ✓ Kế toán ONLINE: %s') % self.online_recipient_user_id)
        else:
            preview_lines.append(_('  ✗ Kế toán ONLINE: (chưa cấu hình)'))
        
        if self.offline_recipient_user_id:
            preview_lines.append(_('  ✓ Kế toán OFFLINE: %s') % self.offline_recipient_user_id)
        else:
            preview_lines.append(_('  ✗ Kế toán OFFLINE: (chưa cấu hình)'))
        
        preview_lines.append('')
        preview_lines.append(_('� PHIẾU NHẬP KHO (Incoming):'))
        
        if self.incoming_recipient_user_id:
            preview_lines.append(_('  ✓ Kế toán NHẬP KHO: %s') % self.incoming_recipient_user_id)
        else:
            preview_lines.append(_('  ✗ Kế toán NHẬP KHO: (chưa cấu hình)'))
        
        preview_lines.append('')
        preview_lines.append(_('�💡 Cơ chế hoạt động:'))
        preview_lines.append(_('📤 Phiếu XUẤT:'))
        preview_lines.append(_('  • Có saler_code trong danh sách ONLINE'))
        preview_lines.append(_('    → Gửi thông báo tới Kế toán ONLINE'))
        preview_lines.append(_('  • Có saler_code KHÔNG trong danh sách ONLINE'))
        preview_lines.append(_('    → Gửi thông báo tới Kế toán OFFLINE'))
        preview_lines.append(_('  • Không có saler_code'))
        preview_lines.append(_('    → Không gửi thông báo (log warning)'))
        preview_lines.append('')
        preview_lines.append(_('📥 Phiếu NHẬP:'))
        preview_lines.append(_('  • TẤT CẢ phiếu nhập'))
        preview_lines.append(_('    → Gửi thông báo tới Kế toán NHẬP KHO'))

        preview_text = '\n'.join(preview_lines)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Preview cấu hình saler online/offline'),
                'message': preview_text,
                'type': 'info',
                'sticky': True,
            }
        }

    def action_refresh_token(self):
        """
        Action button để manually refresh token
        """
        self.ensure_one()
        try:
            self.refresh_zalo_access_token()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Refresh Token'),
                    'message': _('Đã refresh access token thành công'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Lỗi khi refresh token: %s") % str(e))

    # ===================== Interaction Reminder Methods =====================

    def _get_all_reminder_recipients(self):
        """
        Lấy tất cả các Zalo User IDs cần gửi tin nhắn nhắc nhở.
        Bao gồm:
        - recipient_ids: Danh sách user_id mặc định (dùng cho WordPress webhook)
        - online_recipient_user_id, offline_recipient_user_id, incoming_recipient_user_id: Kế toán
        - saler_mapping_text: Mapping mã sale -> user_id

        :return: Set of unique user IDs
        """
        self.ensure_one()
        recipients = set()

        # Thêm từ recipient_ids (Recipient User IDs - dùng cho WordPress)
        default_recipients = self.get_recipient_list()
        for uid in default_recipients:
            if uid:
                recipients.add(uid.strip())

        if self.online_recipient_user_id:
            recipients.add(self.online_recipient_user_id.strip())

        if self.offline_recipient_user_id:
            recipients.add(self.offline_recipient_user_id.strip())

        if self.incoming_recipient_user_id:
            recipients.add(self.incoming_recipient_user_id.strip())

        # Thêm recipients từ saler_mapping_text nếu có
        saler_mapping = self._parse_saler_mapping_text()
        for user_ids in saler_mapping.values():
            for uid in user_ids:
                if uid:
                    recipients.add(uid.strip())

        return recipients

    def _should_send_reminder(self):
        """
        Kiểm tra có cần gửi tin nhắn nhắc nhở không.

        Điều kiện gửi:
        - enable_interaction_reminder = True
        - active = True
        - Chưa gửi lần nào (last_reminder_sent = False) HOẶC
          đã quá reminder_interval_days ngày kể từ lần gửi cuối

        :return: True nếu cần gửi, False nếu không
        """
        self.ensure_one()

        if not self.enable_interaction_reminder:
            _logger.debug("Config %s: Interaction reminder is disabled", self.id)
            return False

        if not self.active:
            _logger.debug("Config %s: Config is inactive", self.id)
            return False

        if not self.last_reminder_sent:
            _logger.info("Config %s: First time sending reminder (last_reminder_sent is empty)", self.id)
            return True

        # Tính số ngày kể từ lần gửi cuối
        days_since_last = (fields.Datetime.now() - self.last_reminder_sent).days

        if days_since_last >= self.reminder_interval_days:
            _logger.info(
                "Config %s: %d days since last reminder, interval is %d days - should send",
                self.id, days_since_last, self.reminder_interval_days
            )
            return True
        else:
            _logger.debug(
                "Config %s: %d days since last reminder, interval is %d days - not yet",
                self.id, days_since_last, self.reminder_interval_days
            )
            return False

    def send_interaction_reminder(self):
        """
        Gửi tin nhắn nhắc nhở tương tác tới tất cả recipients.

        :return: Dict với kết quả {success_count, total_count, errors}
        """
        self.ensure_one()

        recipients = self._get_all_reminder_recipients()

        if not recipients:
            _logger.warning("Config %s: No recipients configured for reminder", self.id)
            return {'success_count': 0, 'total_count': 0, 'errors': ['No recipients configured']}

        # Format message với biến {date}
        now = fields.Datetime.now()
        date_str = now.strftime('%d/%m/%Y %H:%M')
        message_text = (self.reminder_message_template or '').format(date=date_str)

        success_count = 0
        errors = []

        for user_id in recipients:
            try:
                result = self.send_notification_message(user_id, message_text)
                if result.get('error') == 0:
                    success_count += 1
                    _logger.info("Config %s: Reminder sent to %s", self.id, user_id)
                else:
                    error_msg = result.get('message', 'Unknown error')
                    errors.append(f"User {user_id}: {error_msg}")
                    _logger.warning("Config %s: Failed to send reminder to %s: %s",
                                   self.id, user_id, error_msg)
            except Exception as e:
                errors.append(f"User {user_id}: {str(e)}")
                _logger.exception("Config %s: Error sending reminder to %s: %s",
                                 self.id, user_id, e)

        # Cập nhật last_reminder_sent
        self.write({'last_reminder_sent': now})

        _logger.info(
            "Config %s: Reminder completed - %d/%d sent successfully",
            self.id, success_count, len(recipients)
        )

        return {
            'success_count': success_count,
            'total_count': len(recipients),
            'errors': errors
        }

    @api.model
    def cron_send_interaction_reminder(self):
        """
        Cron job để gửi tin nhắn nhắc nhở tương tác.

        Được gọi bởi scheduled action (ir.cron).
        Chỉ gửi nếu _should_send_reminder() trả về True.
        """
        _logger.info("Starting cron_send_interaction_reminder...")

        configs = self.search([
            ('active', '=', True),
            ('enable_interaction_reminder', '=', True)
        ])

        if not configs:
            _logger.info("No active configs with reminder enabled")
            return

        for config in configs:
            try:
                if config._should_send_reminder():
                    _logger.info("Config %s: Sending interaction reminder...", config.id)
                    result = config.send_interaction_reminder()
                    _logger.info(
                        "Config %s: Reminder result - %d/%d sent, errors: %s",
                        config.id,
                        result['success_count'],
                        result['total_count'],
                        result['errors'] if result['errors'] else 'None'
                    )
                else:
                    _logger.debug("Config %s: Not time to send reminder yet", config.id)
            except Exception as e:
                _logger.exception("Config %s: Error in cron_send_interaction_reminder: %s",
                                 config.id, e)

        _logger.info("Finished cron_send_interaction_reminder")

    def action_send_reminder_now(self):
        """
        Action button để gửi tin nhắn nhắc nhở ngay lập tức (bỏ qua interval check).
        """
        self.ensure_one()

        if not self.enable_interaction_reminder:
            raise UserError(_("Chưa bật tính năng nhắc nhở tương tác!"))

        recipients = self._get_all_reminder_recipients()
        if not recipients:
            raise UserError(_("Chưa cấu hình User ID kế toán nào để nhận thông báo!"))

        result = self.send_interaction_reminder()

        message = _('Đã gửi %d/%d tin nhắn nhắc nhở') % (
            result['success_count'], result['total_count']
        )

        if result['errors']:
            message += _('\n\nLỗi:\n') + '\n'.join(result['errors'][:5])
            if len(result['errors']) > 5:
                message += _('\n... và %d lỗi khác') % (len(result['errors']) - 5)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gửi tin nhắn nhắc nhở'),
                'message': message,
                'type': 'success' if result['success_count'] > 0 else 'warning',
                'sticky': True,
            }
        }
