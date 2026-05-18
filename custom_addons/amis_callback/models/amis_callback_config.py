# -*- coding: utf-8 -*-
import json
import logging
import time

import requests
from requests.exceptions import HTTPError

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Module-level cache: {(db_name, data_type): (timestamp, [items])}
# Tồn tại trong suốt vòng đời worker process — tránh 429 khi cron xử lý nhiều picking
_DICT_CACHE_TTL = 300  # seconds (5 phút)
_DICT_CACHE: dict = {}


class AmisCallbackConfig(models.Model):
    _name = 'amis.callback.config'
    _description = 'Cấu hình AMIS Callback'

    name = fields.Char(string='Tên cấu hình', default='AMIS Callback', required=True)
    app_id = fields.Char(
        string='Mã ứng dụng (App ID)',
        help='MISA app_id dùng làm key để xác thực signature HMAC SHA256.',
        required=True,
        default='cfd435c9-b5c9-484f-b86d-ddbba36dc0f4',
    )
    callback_route = fields.Char(
        string='Đường dẫn callback',
        default='/api/oauth/actopensupport/call_back_data',
        readonly=True,
    )
    active = fields.Boolean(string='Kích hoạt', default=True)
    note = fields.Text(
        string='Ghi chú',
        default='Hàm kết nối token: https://actapp.misa.vn/api/oauth/actopen/connect. Cập nhật app_id và access_code đúng với giá trị MISA cấp cho hệ thống của bạn.',
    )
    api_url = fields.Char(
        string='API URL',
        required=True,
        default='https://actapp.misa.vn',
        help='URL gốc API ACT OpenAPI, ví dụ: https://actapp.misa.vn',
    )
    org_company_code = fields.Char(
        string='Mã miền công ty (org_company_code)',
        default='',
        help='Domain đơn vị đối tác trên AMIS Kế toán.',
    )
    access_code = fields.Char(
        string='Mã kết nối (access_code)',
        help='Mã kết nối lấy từ màn hình thiết lập API kết nối của AMIS Kế toán.',
    )
    access_token = fields.Text(
        string='Access Token',
        readonly=True,
        copy=False,
    )
    token_expired_time = fields.Char(
        string='Hạn token',
        readonly=True,
        copy=False,
    )
    sync_incoming_po_enabled = fields.Boolean(
        string='Đồng bộ phiếu nhập từ PO',
        default=False,
        help='Bật để tự động đẩy phiếu nhập kho (incoming) có nguồn từ đơn mua hàng lên MISA.',
    )
    sync_outgoing_so_enabled = fields.Boolean(
        string='Đồng bộ phiếu xuất kho từ SO',
        default=False,
        help='Bật để tự động đẩy phiếu xuất kho (outgoing) có nguồn từ đơn hàng bán lên MISA.',
    )
    sync_shopee_only = fields.Boolean(
        string='Chỉ sync đơn Shopee',
        default=True,
        help='Bật: chỉ sync các đơn có shopee_order_ref (đơn Shopee). Tắt: sync tất cả đơn bán.',
    )
    misa_branch_id = fields.Char(
        string='MISA Branch ID',
        default='53a073a0-5381-4493-820f-51ea32ebe990',
        help='Branch ID thật trên MISA dùng cho chứng từ nhập kho.',
    )
    misa_stock_id = fields.Char(
        string='MISA Stock ID',
        default='de167b2d-ec5f-404a-8532-08257193bc91',
        help='Stock ID thật trên MISA (kho HLV).',
    )

    # ── Mapping khách hàng Shopee → Account Object MISA ───────────────────────
    misa_shopee_milwaukee_account_object_id = fields.Char(
        string='MISA Account Object - Shopee Milwaukee (796817584)',
        help='account_object_id MISA cho kênh Shopee Milwaukee (identifier=796817584). '
             'Tên MISA: KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE',
    )
    misa_shopee_hlv_account_object_id = fields.Char(
        string='MISA Account Object - Shopee HLV (326259406)',
        help='account_object_id MISA cho kênh Shopee HLV (identifier=326259406). '
             'Tên MISA: KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE HLV',
    )
    misa_shopee_dewalt_account_object_id = fields.Char(
        string='MISA Account Object - Shopee Dewalt (1357810112)',
        help='account_object_id MISA cho kênh Shopee Dewalt (identifier=1357810112). '
             'Tên MISA: KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT',
    )
    # Fallback dùng khi test (môi trường không có cấu hình Shopee)
    misa_fallback_account_object_id = fields.Char(
        string='MISA Account Object - Fallback (Test)',
        help='account_object_id MISA dùng làm fallback khi không xác định được kênh Shopee. '
             'Chỉ dùng cho môi trường test.',
    )
    misa_fallback_account_object_code = fields.Char(
        string='MISA Account Object Code - Fallback (Test)',
    )
    misa_fallback_account_object_name = fields.Char(
        string='MISA Account Object Name - Fallback (Test)',
    )

    # ── Map Shop Shopee → Tên khách hàng MISA (dùng khi xuất Phiếu Bán Hàng) ──
    shopee_customer_map_ids = fields.One2many(
        'amis.shopee.customer.map',
        'config_id',
        string='Map khách hàng Shopee',
        help='Ánh xạ shop_identifier → tên/mã khách hàng MISA dùng cho xuất Phiếu Bán Hàng.',
    )

    # ── Cấu hình sinh hóa đơn VAT kèm SAInvoice ─────────────────────────────────
    sa_invoice_include_vat = fields.Boolean(
        string='Sinh hóa đơn VAT kèm SAInvoice',
        default=False,
        help='Bật để tự động xuất hóa đơn điện tử (include_invoice=1) khi đẩy SAInvoice. '
             'Cần điền đầy đủ thông tin mẫu hóa đơn phía dưới.',
    )
    misa_inv_template_id = fields.Char(
        string='Mẫu hóa đơn (Invoice Template ID)',
        help='UUID của mẫu hóa đơn điện tử trên MISA (invoice_template_id).',
    )
    misa_inv_series = fields.Char(
        string='Ký hiệu hóa đơn (Series)',
        help='Ký hiệu hóa đơn (inv_series), ví dụ: 1C25TAA, C25TAA...',
    )

    # ── meInvoice API (Hóa đơn điện tử đầu ra) ─────────────────────────────────
    meinvoice_enabled = fields.Boolean(
        string='Phát hành HĐĐT qua meInvoice',
        default=False,
        help='Bật để dùng MISA meInvoice API phát hành hóa đơn điện tử đầu ra thay vì SAInvoice ACT.',
    )
    meinvoice_inbot_client_id = fields.Char(
        string='meInvoice Inbot Client ID',
        help='ClientID dùng cho meInvoice Inbot API (/api2) — lấy danh sách hóa đơn đầu ra.\n'
             'Khác với App ID dùng cho /api/integration. Do MISA cấp khi đăng ký Inbot.',
    )
    meinvoice_api_url = fields.Char(
        string='meInvoice API URL',
        default='https://api.meinvoice.vn/api/integration',
        help='URL gốc meInvoice API.\nProduction: https://api.meinvoice.vn/api/integration\nTest: https://testapi.meinvoice.vn/api/integration',
    )
    meinvoice_app_id = fields.Char(
        string='meInvoice App ID',
        help='app_id do MISA cấp khi đăng ký tích hợp meInvoice.',
    )
    meinvoice_taxcode = fields.Char(
        string='Mã số thuế (meInvoice)',
        help='Mã số thuế doanh nghiệp dùng để xác thực meInvoice.',
    )
    meinvoice_username = fields.Char(
        string='Tài khoản meInvoice',
        help='Tài khoản đăng nhập trên app.meinvoice.vn.',
    )
    meinvoice_password = fields.Char(
        string='Mật khẩu meInvoice',
        help='Mật khẩu đăng nhập meInvoice (lưu mã hoá).',
    )
    meinvoice_token = fields.Text(
        string='meInvoice Token',
        readonly=True,
        copy=False,
    )
    meinvoice_token_acquired = fields.Datetime(
        string='Thời điểm lấy token meInvoice',
        readonly=True,
        copy=False,
        help='Token meInvoice có hiệu lực 14 ngày kể từ thời điểm này.',
    )
    meinvoice_inv_series = fields.Char(
        string='Ký hiệu hóa đơn (meInvoice)',
        help='Ký hiệu hóa đơn điện tử, ví dụ: 1C25MLT (MTT có mã), 1C25TYY (thường).',
    )
    meinvoice_sign_type = fields.Integer(
        string='SignType (meInvoice)',
        default=1,
        help='1: USB token (ký bằng USB token qua meInvoice agent — dùng cho hóa đơn thường).\n'
             '2: HSM server-side (cần cấu hình HSM trên hệ thống meInvoice).\n'
             '5: Không hiển thị CKS — chỉ dùng cho hóa đơn MTT (máy tính tiền, series char[4]=M).',
    )
    meinvoice_stock_out_address = fields.Char(
        string='Địa chỉ kho xuất hàng (meInvoice)',
        help='Địa chỉ kho xuất hàng điền vào hóa đơn điện tử. Ví dụ: Tổ 2, Ấp Hiền Đức, Đồng Nai.',
    )
    meinvoice_stock_in_address = fields.Char(
        string='Địa chỉ kho nhận hàng (meInvoice)',
        default='Khách hàng không cung cấp thông tin',
        help='Địa chỉ kho nhận hàng điền vào hóa đơn điện tử. Mặc định: Khách hàng không cung cấp thông tin.',
    )
    meinvoice_is_pxk = fields.Boolean(
        string='Xuất kèm Phiếu Xuất Kho (PXK)',
        default=False,
        help='Bật khi ký hiệu hóa đơn là loại PXK (phiếu xuất kho kiêm vận chuyển nội bộ). '
             'Khi bật, trường Phương tiện vận chuyển sẽ được gửi lên meInvoice.',
    )
    meinvoice_transport_means = fields.Char(
        string='Phương tiện vận chuyển (PXK)',
        help='Điền phương tiện vận chuyển khi hóa đơn là loại PXK. Ví dụ: Xe ô tô, Giao hàng nhanh.',
    )

    # ── meInvoice: Tên người mua mặc định theo kênh Shopee ──────────────────────
    meinvoice_shopee_milwaukee_buyer_name = fields.Char(
        string='Tên người mua - Shopee Milwaukee (meInvoice)',
        default='KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE',
        help='Tên BuyerLegalName/BuyerFullName gửi lên meInvoice cho đơn Shopee Milwaukee.',
    )
    meinvoice_shopee_hlv_buyer_name = fields.Char(
        string='Tên người mua - Shopee HLV (meInvoice)',
        default='KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE HLV',
        help='Tên BuyerLegalName/BuyerFullName gửi lên meInvoice cho đơn Shopee HLV.',
    )
    meinvoice_shopee_dewalt_buyer_name = fields.Char(
        string='Tên người mua - Shopee Dewalt (meInvoice)',
        default='KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT',
        help='Tên BuyerLegalName/BuyerFullName gửi lên meInvoice cho đơn Shopee Dewalt.',
    )
    meinvoice_default_buyer_name = fields.Char(
        string='Tên người mua mặc định (meInvoice)',
        help='Tên BuyerLegalName/BuyerFullName fallback khi không xác định được kênh Shopee.',
    )
    meinvoice_shopee_default_address = fields.Char(
        string='Địa chỉ người mua mặc định - Shopee (meInvoice)',
        default='Khách hàng không cung cấp thông tin',
        help='Địa chỉ BuyerAddress ghi vào hóa đơn nháp tự động tạo cho đơn Shopee.',
    )
    meinvoice_auto_draft_on_confirm = fields.Boolean(
        string='Tự động tạo HĐĐT nháp khi xác nhận đơn Shopee',
        default=False,
        help='(Cũ) Tạo hóa đơn nháp ngay khi xác nhận SO. '
             'Khuyến nghị: dùng "Bước phiếu kho kích hoạt" thay thế.',
    )
    meinvoice_draft_trigger_step = fields.Selection(
        [
            ('confirm', 'Khi xác nhận SO'),
            ('pick', 'Khi hoàn thành bước Pick'),
            ('pack', 'Khi hoàn thành bước Pack'),
            ('out', 'Khi hoàn thành bước Out (xuất kho)'),
        ],
        string='Bước tạo HĐĐT nháp tự động',
        default='out',
        help='Chọn bước nào trong quy trình kho sẽ kích hoạt tạo hóa đơn nháp meInvoice.\n'
             '• Xác nhận SO: tạo ngay sau khi bấm Xác nhận (hành vi cũ).\n'
             '• Pick: khi phiếu PICK được validate.\n'
             '• Pack: khi phiếu PACK được validate.\n'
             '• Out (xuất kho): khi phiếu OUT/WH/OUT được validate — khuyến nghị.',
    )
    meinvoice_auto_check_status = fields.Boolean(
        string='Tự động kiểm tra trạng thái CQT (meInvoice)',
        default=True,
        help='Bật: cron tự động gọi /invoice/status để cập nhật trạng thái CQT '
             'cho hóa đơn đã phát hành chưa được xác nhận.',
    )
    meinvoice_status_check_interval = fields.Integer(
        string='Tần suất kiểm tra CQT (giờ)',
        default=2,
        help='Sau bao nhiêu giờ kể từ lần check cuối thì check lại trạng thái CQT. '
             'Mặc định 2 giờ.',
    )
    meinvoice_shopee_only = fields.Boolean(
        string='Chỉ phát hành HĐĐT cho đơn Shopee (meInvoice)',
        default=True,
        help='Bật: chỉ phát hành hóa đơn meInvoice cho đơn có shopee_order_ref. '
             'Tắt: phát hành cho tất cả đơn hàng.',
    )
    meinvoice_skip_api = fields.Boolean(
        string='Bỏ qua gọi API meInvoice (Dry-run)',
        default=False,
        help='Bật khi test: hệ thống sẽ giả lập thành công mà KHÔNG gọi API meInvoice thật.\n'
             'Dữ liệu sẽ KHÔNG được gửi tới Cơ quan Thuế.\n'
             'Tắt khi chạy thực tế.',
    )

    # ── Webhook → meInvoice auto-publish ─────────────────────────────────────
    webhook_auto_publish_enabled = fields.Boolean(
        string='Tự động phát hành HĐĐT khi nhận webhook Shopee',
        default=False,
        help='Bật: khi webhook Shopee cập nhật trạng thái đơn hàng vào một trong các '
             'trạng thái cấu hình bên dưới, hệ thống tự động enqueue job phát hành '
             'HĐĐT meInvoice cho đơn đó.\nTắt: không làm gì khi nhận webhook.',
    )
    webhook_trigger_status_ids = fields.Many2many(
        'amis.shopee.webhook.status',
        'amis_config_webhook_status_rel',
        'config_id', 'status_id',
        string='Trạng thái kích hoạt',
        help='Chọn các trạng thái Shopee sẽ kích hoạt phát hành HĐĐT tự động.'
             ' Thường chọn: Hoàn thành, Đã nhận hàng.',
    )

    # ── Khung giờ phát hành HĐĐT ─────────────────────────────────────────────
    webhook_publish_time_restrict = fields.Boolean(
        string='Giới hạn khung giờ phát hành HĐĐT',
        default=False,
        help='Bật để chỉ phát hành HĐĐT tự động trong khung giờ quy định.\n'
             'Các đơn nhận ngoài khung giờ sẽ được gom lại theo cấu hình bên dưới.',
    )
    webhook_publish_time_from = fields.Float(
        string='Từ giờ',
        default=7.0,
        help='Giờ bắt đầu cho phép phát hành HĐĐT tự động. Ví dụ: 7.0 = 07:00, 7.5 = 07:30.',
    )
    webhook_publish_time_to = fields.Float(
        string='Đến giờ',
        default=16.5,
        help='Giờ kết thúc cho phép phát hành HĐĐT tự động. Ví dụ: 16.5 = 16:30, 17.0 = 17:00.',
    )
    webhook_publish_deferred_action = fields.Selection(
        [
            ('notify', 'Gom lại — người dùng gửi thủ công'),
            ('auto', 'Tự động gửi khi vào khung giờ hôm sau'),
        ],
        string='Xử lý đơn ngoài khung giờ',
        default='auto',
        help='• Gom lại: đơn ngoài giờ được đánh dấu "Ngoài khung giờ", không tự xử lý.\n'
             '  Người dùng vào hàng đợi bấm "Thử lại" khi cần.\n'
             '• Tự động gửi: khi cron chạy trong khung giờ, tự reset và gửi những đơn đang chờ.',
    )

    def get_webhook_trigger_statuses(self):
        """Trả về set tên trạng thái kích hoạt."""
        return set(self.webhook_trigger_status_ids.mapped('name'))

    # Mapping cứng: shopee.shop.identifier → account_object_name MISA
    SHOPEE_SHOP_ACCOUNT_MAP = {
        '796817584': 'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE',
        '326259406': 'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE HLV',
        '1357810112': 'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT',
    }

    def resolve_misa_account_object(self, partner, sale_order=None):
        """Giải quyết account_object_id/code/name từ MISA theo thứ tự ưu tiên.

        Dùng chung cho cả SAVoucher (stock.picking) và SAInvoice (sale.order).

        Returns:
            (account_object_id, account_object_code, account_object_name)
        Raises:
            UserError nếu không tìm được account_object_id.
        """
        from odoo.exceptions import UserError
        import re
        _uuid_re = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

        def _is_uuid(s):
            return bool(_uuid_re.match(s or ''))

        account_object_id = (partner.misa_account_object_id or '').strip() if partner else ''
        account_object_code = (partner.ref or (partner.name if partner else '')) if partner else ''
        account_object_name = partner.display_name if partner else ''

        # 1. Lookup MISA theo tên partner nếu chưa có ID
        # Bỏ qua cho đơn Shopee — sẽ resolve ở bước 2 theo shopee_shop_id (tránh gọi get_dictionary)
        has_shopee_shop = sale_order and getattr(sale_order, 'shopee_shop_id', None)
        if not account_object_id and partner and not has_shopee_shop:
            search_name = (partner.name or '').upper()
            for a in self._get_all_dictionary(1):
                aname = (a.get('account_object_name') or '').upper()
                acode = (a.get('account_object_code') or '').upper()
                if search_name and (search_name in aname or search_name in acode):
                    misa_id = a.get('account_object_id') or ''
                    if misa_id:
                        partner.sudo().write({'misa_account_object_id': misa_id})
                        account_object_id = misa_id
                        account_object_code = a.get('account_object_code') or account_object_code
                        account_object_name = a.get('account_object_name') or account_object_name
                        _logger.info('Resolved partner %s → account_object_id=%s', partner.name, misa_id)
                    break

        # 2. Fallback theo shopee_shop_id.shop_identifier
        if not account_object_id and sale_order:
            shop = getattr(sale_order, 'shopee_shop_id', None)
            shop_identifier = str(getattr(shop, 'shop_identifier', '') or '').strip() if shop else ''
            if shop_identifier:
                misa_id, misa_code, misa_name = self.get_shopee_account_object_id(shop_identifier)
                if misa_id:
                    account_object_id = misa_id
                    account_object_code = misa_code or misa_name
                    account_object_name = misa_name

        # 3. Fallback config (môi trường test)
        if not account_object_id:
            fallback_id = (self.misa_fallback_account_object_id or '').strip()
            if fallback_id:
                account_object_id = fallback_id
                account_object_code = (self.misa_fallback_account_object_code or '').strip()
                account_object_name = (self.misa_fallback_account_object_name or '').strip()
                _logger.warning('SAVoucher/SAInvoice: dùng fallback account_object_id=%s', fallback_id)

        if not account_object_id:
            raise UserError(
                'Không tìm được MISA Account Object ID cho khách hàng: %s. '
                'Vui lòng điền MISA Account Object - Fallback (Test) trong cấu hình để test.' % (
                    partner.name if partner else '?'
                )
            )

        # 4. Nếu code/name trống hoặc là UUID → lookup MISA lấy tên thật rồi cache
        if not account_object_code or not account_object_name or _is_uuid(account_object_code) or _is_uuid(account_object_name):
            uid_lower = account_object_id.lower()
            resolved = next(
                (a for a in self._get_all_dictionary(1)
                 if (a.get('account_object_id') or '').lower() == uid_lower),
                None
            )
            if resolved:
                real_code = resolved.get('account_object_code') or ''
                real_name = resolved.get('account_object_name') or ''
                if real_code and not _is_uuid(real_code):
                    account_object_code = real_code
                if real_name and not _is_uuid(real_name):
                    account_object_name = real_name
                # Cập nhật cache fallback nếu đang chứa UUID
                update = {}
                fb_id = (self.misa_fallback_account_object_id or '').strip()
                if fb_id == account_object_id:
                    if real_code and not _is_uuid(real_code) and _is_uuid(self.misa_fallback_account_object_code or ''):
                        update['misa_fallback_account_object_code'] = real_code
                    if real_name and not _is_uuid(real_name) and _is_uuid(self.misa_fallback_account_object_name or ''):
                        update['misa_fallback_account_object_name'] = real_name
                if update:
                    self.sudo().write(update)
                _logger.info('Resolved account_object name=%s code=%s', account_object_name, account_object_code)
            else:
                if not account_object_name or _is_uuid(account_object_name):
                    account_object_name = partner.display_name if partner else account_object_id
                if not account_object_code or _is_uuid(account_object_code):
                    account_object_code = partner.ref or (partner.name if partner else account_object_id)

        return account_object_id, account_object_code, account_object_name

    def get_meinvoice_buyer_name(self, sale_order):
        """Trả về tên người mua cho meInvoice dựa theo kênh Shopee của đơn hàng.

        Thứ tự ưu tiên:
        1. Tên theo shop identifier (Milwaukee / HLV / Dewalt) từ config
        2. Tên mặc định fallback từ config
        3. Tên partner trên đơn hàng
        """
        self.ensure_one()
        shop = getattr(sale_order, 'shopee_shop_id', None) if sale_order else None
        shop_identifier = str(getattr(shop, 'shop_identifier', '') or '').strip() if shop else ''

        field_map = {
            '796817584': 'meinvoice_shopee_milwaukee_buyer_name',
            '326259406': 'meinvoice_shopee_hlv_buyer_name',
            '1357810112': 'meinvoice_shopee_dewalt_buyer_name',
        }
        if shop_identifier and shop_identifier in field_map:
            name = (getattr(self, field_map[shop_identifier]) or '').strip()
            if name:
                return name

        fallback = (self.meinvoice_default_buyer_name or '').strip()
        if fallback:
            return fallback

        # Không dùng tên partner Shopee (buyer_username) — trả về chuỗi rỗng để form để trống
        return ''

    def get_shopee_account_object_id(self, shop_identifier):
        """Lấy account_object_id MISA cho kênh Shopee dựa vào shop identifier.

        Ưu tiên lấy từ field config (đã cache), nếu chưa có thì lookup MISA theo tên.
        """
        self.ensure_one()
        identifier = str(shop_identifier or '').strip()
        if not identifier:
            return '', '', ''

        field_map = {
            '796817584': ('misa_shopee_milwaukee_account_object_id',
                          'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE'),
            '326259406': ('misa_shopee_hlv_account_object_id',
                          'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE HLV'),
            '1357810112': ('misa_shopee_dewalt_account_object_id',
                           'KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT'),
        }
        entry = field_map.get(identifier)
        if not entry:
            _logger.warning('MISA: không có mapping cho shopee identifier %s', identifier)
            return '', '', ''

        field_name, expected_name = entry
        cached_id = (getattr(self, field_name) or '').strip()
        if cached_id:
            return cached_id, '', expected_name

        # Chưa cache → lookup MISA dictionary (dùng cache trong transaction này)
        search_name = expected_name.upper()
        for a in self._get_all_dictionary(1):
            aname = (a.get('account_object_name') or '').upper()
            if search_name == aname:
                misa_id = a.get('account_object_id') or ''
                acode = a.get('account_object_code') or ''
                if misa_id:
                    self.sudo().write({field_name: misa_id})
                    _logger.info('Auto-cached shopee shop %s → %s = %s', identifier, field_name, misa_id)
                return misa_id, acode, expected_name
        _logger.warning('MISA: không tìm được account_object cho shopee shop %s (%s)', identifier, expected_name)
        return '', '', expected_name

    def ensure_singleton(self):
        record = self.search([], limit=1)
        if record:
            return record
        return self.create({
            'name': 'AMIS Callback',
        })

    def action_connect_misa(self):
        self.ensure_one()
        if not self.access_code:
            raise UserError('Vui lòng nhập Access Code trước khi kết nối.')
        payload = {
            'app_id': self.app_id,
            'access_code': self.access_code,
            'org_company_code': self.org_company_code,
        }
        response = self._post_actopen('/api/oauth/actopen/connect', payload, include_token=False)
        data_raw = response.get('Data')
        data_obj = {}
        if isinstance(data_raw, str):
            try:
                data_obj = json.loads(data_raw)
            except Exception:
                data_obj = {}
        elif isinstance(data_raw, dict):
            data_obj = data_raw

        token = data_obj.get('access_token')
        expired = data_obj.get('expired_time')
        if not token:
            raise UserError('Không lấy được access_token từ hàm connect.')

        self.sudo().write({
            'access_token': token,
            'token_expired_time': expired or '',
        })
        return True

    def _build_headers(self, include_token=True):
        self.ensure_one()
        headers = {
            'Content-Type': 'application/json',
        }
        if include_token:
            if not self.access_token:
                raise UserError('Chưa có access_token. Vui lòng bấm "Kết nối MISA" trước.')
            headers['X-MISA-AccessToken'] = self.access_token
        return headers

    def _post_actopen(self, path, payload, include_token=True, timeout=15):
        self.ensure_one()
        api_url = (self.api_url or '').rstrip('/')
        if not api_url:
            raise UserError('Thiếu API URL.')
        url = f'{api_url}{path}'
        headers = self._build_headers(include_token=include_token)
        max_retries = 3
        delay = 5  # seconds
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                if response.status_code == 429:
                    wait = delay * (2 ** attempt)  # 5s, 10s, 20s
                    _logger.warning('AMIS 429 Too Many Requests: %s (attempt %d/%d) — waiting %ds', path, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    last_exc = HTTPError(f'429 Client Error: Too Many Requests for url: {url}', response=response)
                    continue
                response.raise_for_status()
                body = response.json()
            except HTTPError:
                raise
            except Exception as exc:
                _logger.exception('AMIS call failed: %s %s', path, exc)
                raise UserError(f'Gọi API MISA thất bại: {exc}')

            if not body.get('Success'):
                err = body.get('ErrorMessage') or body.get('ErrorCode') or 'Không rõ lỗi'
                raise UserError(f'MISA trả về lỗi: {err}')
            return body

        _logger.error('AMIS call failed after %d retries (429): %s', max_retries, path)
        raise UserError(f'Gọi API MISA thất bại sau {max_retries} lần thử: 429 Too Many Requests ({path})')

    def push_dictionary(self, dictionary_items):
        self.ensure_one()
        if not dictionary_items:
            return {'Success': True}
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'dictionary': dictionary_items,
        }
        return self._post_actopen('/apir/sync/actopen/save_dictionary', payload, include_token=True)

    def _get_all_dictionary(self, data_type):
        """Tải toàn bộ 1 loại danh mục MISA và cache trong memory cho transaction này.

        Thay vì gọi get_dictionary nhiều lần (N page × M lần lookup),
        chỉ gọi 1 lần rồi cache trên cursor. Cache tự xóa khi transaction/cursor kết thúc.
        """
        self.ensure_one()
        # Thử module-level cache trước (tồn tại qua nhiều transaction, TTL 5 phút)
        db_name = self.env.cr.dbname
        cache_key = (db_name, int(data_type))
        now = time.monotonic()
        cached = _DICT_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _DICT_CACHE_TTL:
            return cached[1]

        # Fallback: cursor-level cache (transaction scope)
        cr = self.env.cr
        if not hasattr(cr, '_amis_dict_cache'):
            cr._amis_dict_cache = {}
        tx_cache = cr._amis_dict_cache
        key = int(data_type)
        if key in tx_cache:
            return tx_cache[key]

        all_items = []
        skip = 0
        while True:
            r = self.get_dictionary(data_type=data_type, skip=skip, take=100)
            items = r.get('items') or []
            all_items.extend(items)
            if len(items) < 100:
                break
            skip += 100

        # Lưu cả hai cache
        _DICT_CACHE[cache_key] = (now, all_items)
        tx_cache[key] = all_items
        _logger.info('MISA dictionary type=%d: fetched %d items (cached for this transaction)', data_type, len(all_items))
        return all_items

    def get_dictionary(self, data_type, branch_id=None, skip=0, take=100, last_sync_time=None):
        """Lay danh muc tu AMIS ke toan theo endpoint get_dictionary.

        Returns:
            dict: {
                'raw': body goc,
                'items': danh sach item da parse tu Data,
                'custom_data': dict parse tu CustomData,
                'last_sync_time': gia tri LastSyncTime neu co,
            }
        """
        self.ensure_one()

        take = int(take or 0)
        if take <= 0:
            take = 100
        if take > 100:
            take = 100

        payload = {
            'data_type': int(data_type),
            'branch_id': branch_id or None,
            'skip': int(skip or 0),
            'take': take,
            'app_id': self.app_id,
            'last_sync_time': last_sync_time or None,
        }
        body = self._post_actopen('/apir/sync/actopen/get_dictionary', payload, include_token=True)

        data_raw = body.get('Data')
        items = []
        if isinstance(data_raw, str):
            try:
                parsed = json.loads(data_raw)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                items = []
        elif isinstance(data_raw, list):
            items = data_raw

        custom_raw = body.get('CustomData')
        custom_data = {}
        if isinstance(custom_raw, str):
            try:
                custom_data = json.loads(custom_raw) or {}
            except Exception:
                custom_data = {}
        elif isinstance(custom_raw, dict):
            custom_data = custom_raw

        return {
            'raw': body,
            'items': items,
            'custom_data': custom_data,
            'last_sync_time': custom_data.get('LastSyncTime'),
        }

    def find_dictionary_item_by_code(self, data_type, code_field, code_value, branch_id=None, take=100, max_pages=30):
        """Tim 1 item danh muc theo code voi phan trang get_dictionary."""
        self.ensure_one()
        if not code_value:
            return False

        skip = 0
        take = min(max(int(take or 100), 1), 100)
        for _page in range(max(1, int(max_pages or 1))):
            result = self.get_dictionary(
                data_type=data_type,
                branch_id=branch_id,
                skip=skip,
                take=take,
                last_sync_time=None,
            )
            items = result.get('items') or []
            for item in items:
                if str(item.get(code_field) or '').strip() == str(code_value).strip():
                    return item
            if len(items) < take:
                break
            skip += take
        return False

    def push_inward_voucher(self, voucher_payload, dictionary_items=None):
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_outgoing_voucher(self, voucher_payload, dictionary_items=None):
        """Dua phieu xuat kho sang MISA.
        
        Tuong tu push_inward_voucher, dung de dua chung tu xuat kho (outgoing) len MISA.
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_sa_voucher(self, voucher_payload):
        """Push SAVoucher (ban hang kiem xuat kho, voucher_type=13) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_sa_invoice(self, voucher_payload):
        """Push SAInvoice (hoa don ban hang, voucher_type=11) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    # ── meInvoice API methods ─────────────────────────────────────────────────

    def action_connect_meinvoice(self):
        """Lấy token từ MISA meInvoice API và lưu vào cấu hình."""
        self.ensure_one()
        if not self.meinvoice_app_id:
            raise UserError('Vui lòng điền meInvoice App ID trước khi kết nối.')
        if not self.meinvoice_taxcode:
            raise UserError('Vui lòng điền Mã số thuế (meInvoice) trước khi kết nối.')
        if not self.meinvoice_username:
            raise UserError('Vui lòng điền Tài khoản meInvoice trước khi kết nối.')
        if not self.meinvoice_password:
            raise UserError('Vui lòng điền Mật khẩu meInvoice trước khi kết nối.')

        payload = {
            'appid': self.meinvoice_app_id,
            'taxcode': self.meinvoice_taxcode,
            'username': self.meinvoice_username,
            'password': self.meinvoice_password,
        }
        result = self._post_meinvoice('/auth/token', payload)
        token = result.get('Data') or result.get('data') or ''
        if not token:
            raise UserError('Không lấy được token từ meInvoice. Kiểm tra lại thông tin đăng nhập.')

        from datetime import datetime as _dt
        self.sudo().write({
            'meinvoice_token': token,
            'meinvoice_token_acquired': _dt.utcnow(),
        })
        _logger.info('meInvoice token acquired successfully.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Kết nối meInvoice thành công',
                'message': 'Token đã được lưu, có hiệu lực 14 ngày.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _ensure_meinvoice_token(self):
        """Tự động refresh token meInvoice nếu đã quá 13 ngày."""
        self.ensure_one()
        if not self.meinvoice_enabled:
            return
        if not self.meinvoice_token or not self.meinvoice_token_acquired:
            if self.meinvoice_username and self.meinvoice_password:
                _logger.info('meInvoice: token chưa có, tự động lấy mới...')
                self.action_connect_meinvoice()
            return
        from datetime import datetime as _dt, timedelta as _td
        acquired = self.meinvoice_token_acquired
        if isinstance(acquired, str):
            try:
                acquired = _dt.fromisoformat(acquired[:19])
            except Exception:
                return
        if (_dt.utcnow() - acquired) >= _td(days=13):
            _logger.info('meInvoice: token hết hạn (>13 ngày), tự động refresh...')
            self.action_connect_meinvoice()

    def _get_meinvoice_headers(self):
        """Build Authorization header cho meInvoice API."""
        self.ensure_one()
        self._ensure_meinvoice_token()
        if not self.meinvoice_token:
            raise UserError('Chưa có token meInvoice. Vui lòng bấm "Kết nối meInvoice" trước.')
        return {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % self.meinvoice_token,
        }

    def _get_meinvoice(self, path, params=None, timeout=30):
        """Gọi meInvoice API bằng GET và trả về response body (dict)."""
        self.ensure_one()
        api_url = (self.meinvoice_api_url or '').rstrip('/')
        if not api_url:
            raise UserError('Thiếu meInvoice API URL trong cấu hình.')
        url = '%s%s' % (api_url, path)
        headers = self._get_meinvoice_headers()
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            _logger.info('meInvoice GET %s → HTTP %s', path, resp.status_code)
            try:
                body = resp.json()
            except Exception:
                body = {}
            _logger.info('meInvoice GET %s response body: %s', path, json.dumps(body, ensure_ascii=False, default=str))
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else '?'
            raise UserError('meInvoice API lỗi HTTP %s: %s' % (status, exc))
        except Exception as exc:
            _logger.exception('meInvoice GET API call failed: %s', path)
            raise UserError('Gọi meInvoice API thất bại: %s' % exc)

        success = body.get('Success') if body.get('Success') is not None else body.get('success')
        if not success:
            err = (body.get('ErrorCode') or body.get('errorCode') or
                   body.get('descriptionErrorCode') or body.get('Errors') or
                   body.get('errors') or str(body) or 'Không rõ lỗi')
            raise UserError('meInvoice trả về lỗi: %s' % err)
        return body

    def _post_meinvoice(self, path, payload=None, params=None, timeout=30):
        """Gọi meInvoice API và trả về response body (dict).

        Gọi trực tiếp (không dùng ACT token), dùng riêng cho meInvoice.
        """
        self.ensure_one()
        api_url = (self.meinvoice_api_url or '').rstrip('/')
        if not api_url:
            raise UserError('Thiếu meInvoice API URL trong cấu hình.')
        url = '%s%s' % (api_url, path)

        # Auth token header — chỉ dùng cho các endpoint trừ /auth/token
        if path == '/auth/token':
            headers = {'Content-Type': 'application/json'}
        else:
            headers = self._get_meinvoice_headers()

        try:
            resp = requests.post(url, json=payload or {}, headers=headers, params=params, timeout=timeout)
            _logger.info('meInvoice %s → HTTP %s', path, resp.status_code)
            try:
                body = resp.json()
            except Exception:
                body = {}
            _logger.info('meInvoice %s response body: %s', path, json.dumps(body, ensure_ascii=False, default=str))
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else '?'
            raise UserError('meInvoice API lỗi HTTP %s: %s' % (status, exc))
        except Exception as exc:
            _logger.exception('meInvoice API call failed: %s', path)
            raise UserError('Gọi meInvoice API thất bại: %s' % exc)

        # meInvoice dùng 'Success' (capitalized) cho auth, 'success' (lowercase) cho các endpoint khác
        success = body.get('Success') if body.get('Success') is not None else body.get('success')
        if not success:
            err = (body.get('ErrorCode') or body.get('errorCode') or
                   body.get('descriptionErrorCode') or body.get('Errors') or
                   body.get('errors') or str(body) or 'Không rõ lỗi')
            raise UserError('meInvoice trả về lỗi: %s' % err)
        return body

    def push_meinvoice_invoice(self, invoice_data_list):
        """Phát hành hóa đơn qua MISA meInvoice API (SignType HSM).

        Args:
            invoice_data_list: list[dict] — danh sách InvoiceData theo spec meInvoice.

        Returns:
            list[dict] — publishInvoiceResult từ meInvoice.
        """
        self.ensure_one()
        if not self.meinvoice_enabled:
            raise UserError('Tính năng phát hành HĐĐT meInvoice chưa được bật trong cấu hình.')
        if not invoice_data_list:
            raise UserError('Không có dữ liệu hóa đơn để phát hành.')

        # SignType: luôn dùng giá trị cấu hình, ngoại trừ series MTT (char[4]='M') → buộc SignType=5
        configured_sign_type = int(self.meinvoice_sign_type or 2)
        first_series = (invoice_data_list[0].get('InvSeries') or '').strip() if invoice_data_list else ''
        is_mtt_series = len(first_series) >= 5 and first_series[4].upper() == 'M'
        if is_mtt_series and configured_sign_type != 5:
            sign_type = 5
            _logger.info(
                'meInvoice: auto-corrected SignType from %d to 5 (MTT) based on InvSeries "%s"',
                configured_sign_type, first_series,
            )
        else:
            sign_type = configured_sign_type
        payload = {
            'SignType': sign_type,
            'InvoiceData': invoice_data_list,
            'PublishInvoiceData': None,
        }
        _logger.info('meInvoice push_invoice: SignType=%d, count=%d', sign_type, len(invoice_data_list))

        # Dry-run mode: bỏ qua gọi API thật, trả về kết quả giả lập
        if self.meinvoice_skip_api:
            _logger.warning(
                'meInvoice DRY-RUN: bỏ qua gọi API thật (meinvoice_skip_api=True). '
                'Dữ liệu KHÔNG được gửi tới CQT.'
            )
            fake_results = []
            for inv in invoice_data_list:
                fake_results.append({
                    'RefID': inv.get('RefID', ''),
                    'TransactionID': 'DRY-RUN-%s' % inv.get('RefID', '')[:8],
                    'InvTemplateNo': '1',
                    'InvSeries': inv.get('InvSeries', ''),
                    'InvNo': '00000000',
                    'InvCode': 'DRY-RUN',
                    'InvDate': inv.get('InvDate', ''),
                    'ErrorCode': '',
                    'DescriptionErrorCode': '',
                })
            return fake_results

        body = self._post_meinvoice('/invoice', payload)

        def _parse_result_field(raw):
            """publishInvoiceResult / createInvoiceResult là JSON string hoặc list."""
            if not raw:
                return []
            if isinstance(raw, list):
                return raw
            try:
                parsed = __import__('json').loads(raw)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []

        publish_results = _parse_result_field(body.get('publishInvoiceResult'))
        if not publish_results:
            # SignType=1 (USB token): invoice tạo xong chờ agent ký,
            # API trả createInvoiceResult thay vì publishInvoiceResult
            create_results = _parse_result_field(body.get('createInvoiceResult'))
            if create_results:
                _logger.info(
                    'meInvoice: publishInvoiceResult rỗng, dùng createInvoiceResult làm fallback '
                    '(USB token — invoice đã tạo, chờ ký).'
                )
                publish_results = create_results

        _logger.info('meInvoice publishInvoiceResult: %s', publish_results)
        return publish_results

    def get_meinvoice_publishview_url(self, transaction_ids):
        """Lấy link xem hóa đơn đã phát hành từ meInvoice (tồn tại 5 phút).

        Args:
            transaction_ids: list[str] — danh sách TransactionID.

        Returns:
            str — URL xem hóa đơn, hoặc '' nếu không lấy được.
        """
        self.ensure_one()
        if not transaction_ids:
            raise UserError('Không có TransactionID để tra cứu hóa đơn.')
        body = self._post_meinvoice('/invoice/publishview', payload=transaction_ids)
        url = body.get('data') or body.get('Data') or ''
        _logger.info('meInvoice publishview URL: %s', url)
        return url

    def get_meinvoice_invoice_status(self, transaction_ids):
        """Tra cứu trạng thái hóa đơn từ CQT qua meInvoice /invoice/status.

        Args:
            transaction_ids: list[str] — danh sách TransactionID.

        Returns:
            list[dict] — danh sách {TransactionID, InvStatus, Description, ...}
        """
        self.ensure_one()
        if not transaction_ids:
            return []
        body = self._post_meinvoice('/invoice/status', payload=transaction_ids)
        data = body.get('data') or body.get('Data') or []
        if isinstance(data, dict):
            data = [data]
        _logger.info('meInvoice invoice status: %s', data)
        return data

    def get_meinvoice_download_url(self, transaction_id, file_type='PDF'):
        """Lấy link tải hóa đơn (PDF hoặc XML) qua meInvoice /invoice/download.

        Args:
            transaction_id: str — TransactionID hóa đơn đã phát hành.
            file_type: str — 'PDF' hoặc 'XML'.

        Returns:
            str — download URL, hoặc '' nếu không lấy được.
        """
        self.ensure_one()
        if not transaction_id:
            raise UserError('Thiếu TransactionID để tải hóa đơn.')
        # /invoice/download dùng GET với query params
        params = {'transactionId': transaction_id, 'fileType': file_type.upper()}
        body = self._get_meinvoice('/invoice/download', params=params)
        url = body.get('data') or body.get('Data') or ''
        _logger.info('meInvoice download URL (%s): %s', file_type, url)
        return url

    def get_meinvoice_templates(self):
        """Lấy danh sách mẫu hóa đơn từ meInvoice /invoice/templates.

        Returns:
            list[dict] — danh sách template.
        """
        self.ensure_one()
        # meInvoice /invoice/templates dùng GET (payload rỗng)
        body = self._post_meinvoice('/invoice/templates', payload={})
        data = body.get('data') or body.get('Data') or []
        if isinstance(data, dict):
            data = [data]
        _logger.info('meInvoice templates (%d): %s', len(data), data)
        return data

    def action_get_meinvoice_templates(self):
        """Nút bấm: lấy và hiển thị danh sách mẫu hóa đơn."""
        self.ensure_one()
        templates = self.get_meinvoice_templates()
        if not templates:
            raise UserError('meInvoice không trả về mẫu hóa đơn nào.')
        lines = []
        for t in templates:
            tid = t.get('TemplateID') or t.get('templateId') or t.get('id') or '?'
            tname = t.get('TemplateName') or t.get('templateName') or t.get('name') or ''
            lines.append('%s — %s' % (tid, tname))
        raise UserError('Danh sách mẫu hóa đơn meInvoice:\n\n' + '\n'.join(lines))

    def action_check_meinvoice_status_cron(self):
        """Cron: kiểm tra trạng thái CQT cho hóa đơn trong queue (cqt_check_queued=True)."""
        config = self.sudo().search([], limit=1, order='id asc')
        if not config or not config.meinvoice_enabled or not config.meinvoice_auto_check_status:
            return

        from datetime import timedelta as _td
        from datetime import datetime as _dt

        interval_hours = max(1, config.meinvoice_status_check_interval or 2)
        cutoff = _dt.utcnow() - _td(hours=interval_hours)

        # Chỉ check hóa đơn đã được queue, chưa check gần đây
        invoices = self.env['meinvoice.invoice'].sudo().search([
            ('cqt_check_queued', '=', True),
            ('transaction_id', '!=', False),
            '|',
            ('cqt_checked_at', '=', False),
            ('cqt_checked_at', '<', cutoff),
        ])

        if not invoices:
            _logger.info('meInvoice status cron: không có hóa đơn trong queue.')
            return

        _logger.info('meInvoice status cron: kiểm tra %d hóa đơn...', len(invoices))
        transaction_ids = [inv.transaction_id for inv in invoices]

        try:
            status_list = config.get_meinvoice_invoice_status(transaction_ids)
        except Exception:
            _logger.exception('meInvoice status cron: gọi API thất bại.')
            return

        # Map TransactionID → status result
        status_map = {}
        for item in (status_list or []):
            if not isinstance(item, dict):
                _logger.warning('meInvoice status cron: item không phải dict, bỏ qua: %r', item)
                continue
            tid = (item.get('TransactionID') or item.get('transactionId') or '').strip()
            if tid:
                status_map[tid] = item

        now = _dt.utcnow()
        for inv in invoices:
            item = status_map.get(inv.transaction_id)
            if not item:
                inv.sudo().write({'cqt_checked_at': now})
                continue

            raw_status = item.get('InvStatus') or item.get('invStatus') or item.get('Status') or 0
            desc = (item.get('Description') or item.get('description') or '').strip()
            try:
                raw_status = int(raw_status)
            except (TypeError, ValueError):
                raw_status = 0

            # meInvoice InvStatus: 1=đang chờ, 2=CQT chấp nhận, 3=CQT từ chối
            if raw_status == 2:
                new_state = 'accepted'
                still_pending = False
            elif raw_status == 3:
                new_state = 'rejected'
                still_pending = False
            elif raw_status == 1:
                new_state = 'submitted'
                still_pending = True   # re-queue để check lại lần sau
            else:
                new_state = inv.state  # giữ nguyên nếu không rõ
                still_pending = True

            inv.sudo().write({
                'state': new_state,
                'cqt_status_code': str(raw_status),
                'cqt_status_desc': desc,
                'cqt_checked_at': now,
                'cqt_check_queued': still_pending,
            })
            _logger.info(
                'meInvoice cron: %s → state=%s (%s)', inv.transaction_id, new_state, desc
            )


    def action_sync_catalog_to_odoo(self):
        """Đồng bộ danh mục hàng hóa (type=2) và đơn vị tính (type=4) từ MISA
        → ghi misa_inventory_item_id lên product.template / misa_unit_id lên uom.uom.
        Chạy thủ công một lần, không gọi trong cron/sync phiếu.
        """
        self.ensure_one()
        self.ensure_sync_ready()

        # ---- Pre-load toàn bộ product + uom vào dict 1 lần (tránh N DB query) ----
        product_env = self.env['product.product'].sudo()
        uom_env = self.env['uom.uom'].sudo()

        # {default_code: [product_ids]}
        all_products = product_env.search([('default_code', '!=', False)])
        code_to_products = {}
        for p in all_products:
            code = (p.default_code or '').strip()
            if code:
                code_to_products.setdefault(code, []).append(p)

        # {uom_name: [uom_ids]}
        all_uoms = uom_env.search([])
        name_to_uoms = {}
        for u in all_uoms:
            name = (u.name or '').strip()
            if name:
                name_to_uoms.setdefault(name, []).append(u)

        # ---- 1. Lấy toàn bộ hàng hóa (data_type=2) — 1 lần fetch, cached ----
        inv_items = self._get_all_dictionary(2)
        item_updated = 0
        for item in inv_items:
            code = (item.get('inventory_item_code') or '').strip()
            item_id = (item.get('inventory_item_id') or '').strip()
            if not code or not item_id:
                continue
            for p in code_to_products.get(code, []):
                if p.misa_inventory_item_id != item_id:
                    p.write({'misa_inventory_item_id': item_id})
                    item_updated += 1

        # ---- 2. Lấy toàn bộ đơn vị tính (data_type=4) — 1 lần fetch, cached ----
        unit_items = self._get_all_dictionary(4)
        unit_updated = 0
        for item in unit_items:
            name = (item.get('unit_name') or '').strip()
            unit_id = (item.get('unit_id') or '').strip()
            if not name or not unit_id:
                continue
            for u in name_to_uoms.get(name, []):
                if u.misa_unit_id != unit_id:
                    u.write({'misa_unit_id': unit_id})
                    unit_updated += 1

        # Xóa module cache để lần sau fetch mới
        db = self.env.cr.dbname
        _DICT_CACHE.pop((db, 2), None)
        _DICT_CACHE.pop((db, 4), None)

        msg = (
            f'Đồng bộ danh mục hoàn tất!\n'
            f'• Hàng hóa: đã cập nhật {item_updated} sản phẩm '
            f'(trên tổng {len(inv_items)} mục MISA).\n'
            f'• Đơn vị tính: đã cập nhật {unit_updated} UoM '
            f'(trên tổng {len(unit_items)} mục MISA).'
        )
        _logger.info('MISA catalog sync: %s', msg)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đồng bộ danh mục MISA',
                'message': msg,
                'type': 'success',
                'sticky': True,
            },
        }

    def action_sync_catalog_unmapped_only(self):
        """Chỉ đồng bộ sản phẩm/UoM chưa có MISA ID (bỏ qua những cái đã map).
        Nhanh hơn full sync vì chỉ write những record thực sự thiếu.
        """
        self.ensure_one()
        self.ensure_sync_ready()

        product_env = self.env['product.product'].sudo()
        uom_env = self.env['uom.uom'].sudo()

        # Chỉ load sản phẩm chưa có mapping
        unmapped_products = product_env.search([
            ('default_code', '!=', False),
            ('misa_inventory_item_id', 'in', [False, '']),
        ])
        code_to_products = {}
        for p in unmapped_products:
            code = (p.default_code or '').strip()
            if code:
                code_to_products.setdefault(code, []).append(p)

        # Chỉ load UoM chưa có mapping
        unmapped_uoms = uom_env.search([('misa_unit_id', 'in', [False, ''])])
        name_to_uoms = {}
        for u in unmapped_uoms:
            name = (u.name or '').strip()
            if name:
                name_to_uoms.setdefault(name, []).append(u)

        item_updated = 0
        unit_updated = 0

        if code_to_products:
            inv_items = self._get_all_dictionary(2)
            for item in inv_items:
                code = (item.get('inventory_item_code') or '').strip()
                item_id = (item.get('inventory_item_id') or '').strip()
                if not code or not item_id:
                    continue
                for p in code_to_products.get(code, []):
                    p.write({'misa_inventory_item_id': item_id})
                    item_updated += 1

        if name_to_uoms:
            unit_items = self._get_all_dictionary(4)
            for item in unit_items:
                name = (item.get('unit_name') or '').strip()
                unit_id = (item.get('unit_id') or '').strip()
                if not name or not unit_id:
                    continue
                for u in name_to_uoms.get(name, []):
                    u.write({'misa_unit_id': unit_id})
                    unit_updated += 1

        # Xóa cache sau khi dùng
        db = self.env.cr.dbname
        _DICT_CACHE.pop((db, 2), None)
        _DICT_CACHE.pop((db, 4), None)

        msg = (
            f'Đồng bộ sản phẩm chưa map hoàn tất!\n'
            f'• Hàng hóa: đã map {item_updated}/{len(unmapped_products)} sản phẩm chưa có ID.\n'
            f'• Đơn vị tính: đã map {unit_updated}/{len(unmapped_uoms)} UoM chưa có ID.'
        )
        _logger.info('MISA catalog sync (unmapped only): %s', msg)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đồng bộ sản phẩm mới',
                'message': msg,
                'type': 'success',
                'sticky': True,
            },
        }

    def action_fetch_invoice_templates(self):
        """Lấy danh sách mẫu hóa đơn điện tử từ MISA và hiển thị dạng bảng."""
        self.ensure_one()
        self.ensure_sync_ready()

        templates = []
        # Thử các endpoint meInvoice ACT OpenAPI
        endpoints = [
            '/apir/einvoice/actopen/get_invoice_template',
            '/apir/einvoice/actopen/invoice_template/list',
            '/apir/einvoice/actopen/template',
        ]
        last_error = ''
        for ep in endpoints:
            try:
                body = self._post_actopen(ep, {
                    'app_id': self.app_id,
                    'org_company_code': self.org_company_code,
                }, include_token=True)
                data = body.get('Data') or body.get('data') or []
                if isinstance(data, str):
                    data = json.loads(data) or []
                if isinstance(data, list) and data:
                    templates = data
                    _logger.info('Invoice templates from %s: %d items', ep, len(templates))
                    break
                elif isinstance(data, dict):
                    # Có thể là {"items": [...]}
                    items = data.get('items') or data.get('Items') or []
                    if items:
                        templates = items
                        break
            except Exception as e:
                last_error = str(e)
                _logger.warning('meInvoice endpoint %s failed: %s', ep, e)

        message = False
        if not templates:
            message = (
                'Không lấy được danh sách mẫu hóa đơn từ API MISA (lỗi: %s).\n\n'
                'Lấy thủ công:\n'
                '1. Vào meInvoice → Đăng ký phát hành\n'
                '2. Click vào mẫu hóa đơn đang dùng → nhìn URL lấy UUID = Invoice Template ID\n'
                '3. Ký hiệu (series) ví dụ 1C25TAA hiển thị trong cột Ký hiệu' % last_error
            )

        line_vals = []
        for t in templates:
            tid = (t.get('invoice_template_id') or t.get('template_id') or t.get('id') or '')
            series = (t.get('inv_series') or t.get('serial') or t.get('invoice_series') or
                      t.get('inv_symbol') or t.get('symbol') or '')
            name = (t.get('invoice_template_name') or t.get('template_name') or t.get('name') or '')
            status = str(t.get('status') or t.get('state') or '')
            line_vals.append((0, 0, {
                'template_id': tid,
                'series': series,
                'name': name,
                'status': status,
            }))

        wizard = self.env['misa.invoice.template.wizard'].create({
            'message': message,
            'line_ids': line_vals,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Mẫu hóa đơn MISA (%d mẫu)' % len(templates),
            'res_model': 'misa.invoice.template.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _ensure_token_valid(self):
        """Tự động refresh token nếu hết hạn (dùng access_code đã lưu)."""
        self.ensure_one()
        expired_str = (self.token_expired_time or '').strip()
        if not expired_str or not self.access_code:
            return
        try:
            from datetime import datetime
            # MISA thường trả về ISO format: "2026-05-06T10:30:00" hoặc có Z
            expired_dt = datetime.fromisoformat(expired_str.replace('Z', '').strip()[:19])
            if datetime.utcnow() >= expired_dt:
                _logger.info('MISA token hết hạn (%s), đang tự động làm mới...', expired_str)
                self.sudo().action_connect_misa()
                _logger.info('MISA token đã được làm mới thành công.')
        except Exception:
            _logger.warning('Không thể parse token_expired_time "%s", bỏ qua auto-refresh.', expired_str)

    def ensure_sync_ready(self):
        self.ensure_one()
        self._ensure_token_valid()
        missing = []
        if not self.app_id:
            missing.append('App ID')
        if not self.org_company_code:
            missing.append('Org Company Code')
        if not self.api_url:
            missing.append('API URL')
        if not self.access_token:
            missing.append('Access Token')
        if missing:
            raise UserError('Thiếu cấu hình MISA: %s' % ', '.join(missing))
        return True

    def delete_call_back_data(self):
        """Xoa ket qua goi callback cua tai khoan ung dung ACT.
        
        Endpoint: POST /api/oauth/actopensupport/delete_call_back_data
        Dung de xoa cac ket qua callback da ghi nhan de test.
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
        }
        return self._post_actopen('/api/oauth/actopensupport/delete_call_back_data', payload, include_token=False)

    def check_call_back_data(self):
        """Kiem tra cac ket qua goi callback cua tai khoan ung dung demo.
        
        Endpoint: POST /api/oauth/actopensupport/check_call_back_data
        Dung de kiem tra cac loi goi da tu phat toi ham call_back_data,
        dung de test thong luong callback.
        
        Returns:
            dict: Trai ve Success, ErrorMessage, va Data (danh sach ket qua callback).
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
        }
        return self._post_actopen('/api/oauth/actopensupport/check_call_back_data', payload, include_token=False)

    def action_test_outgoing_push(self):
        """Action de test push outgoing (dung cho test)"""
        return True
