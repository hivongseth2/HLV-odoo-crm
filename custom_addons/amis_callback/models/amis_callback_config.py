# -*- coding: utf-8 -*-
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta

import requests
from requests.exceptions import HTTPError

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Module-level cache: {(db_name, data_type): (timestamp, [items])}
# Tồn tại trong suốt vòng đời worker process — tránh 429 khi cron xử lý nhiều picking
_DICT_CACHE_TTL = 300  # seconds (5 phút)
_DICT_CACHE: dict = {}
_DICT_PAGE_CACHE: dict = {}
_GET_DICTIONARY_MIN_INTERVAL = 1.2  # seconds, serialized across Odoo workers


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
    sync_purchase_order_enabled = fields.Boolean(
        string='Đồng bộ đơn mua hàng',
        default=False,
        help='Bật để tự động đẩy purchase.order đã xác nhận lên MISA dưới dạng Đơn mua hàng (pu_order).',
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

    misa_inventory_cache_last_sync_time = fields.Char(
        string='Cursor hàng hóa MISA',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ thay đổi hàng hóa MISA thành công gần nhất.',
    )
    misa_inventory_cache_delete_last_sync_time = fields.Char(
        string='Cursor hàng hóa MISA đã xóa',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ danh mục hàng hóa bị xóa thành công gần nhất.',
    )
    misa_inventory_cache_overlap_minutes = fields.Integer(
        string='Overlap cursor hàng hóa MISA (phút)',
        default=5,
        help='Khi đồng bộ tăng dần, request sẽ lùi cursor lại khoảng này để replay vùng biên paging MISA.',
    )
    misa_unit_cache_last_sync_time = fields.Char(
        string='Cursor ĐVT MISA',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ thay đổi đơn vị tính MISA thành công gần nhất.',
    )
    misa_unit_cache_delete_last_sync_time = fields.Char(
        string='Cursor ĐVT MISA đã xóa',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ đơn vị tính bị xóa thành công gần nhất.',
    )
    misa_vendor_cache_last_sync_time = fields.Char(
        string='Cursor nhà cung cấp MISA',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ thay đổi nhà cung cấp MISA thành công gần nhất.',
    )
    misa_vendor_cache_delete_last_sync_time = fields.Char(
        string='Cursor nhà cung cấp MISA đã xóa',
        readonly=True,
        copy=False,
        help='LastSyncTime của lần đồng bộ nhà cung cấp bị xóa thành công gần nhất.',
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

    # ── meInvoice: Gửi email cho khách hàng ─────────────────────────────────
    meinvoice_mail_enabled = fields.Boolean(
        string='Bật gửi email HĐĐT cho khách hàng',
        default=False,
        help='Bật để hiển thị nút "Gửi email" trên form hóa đơn meInvoice và '
             'cho phép cấu hình gửi tự động.',
    )
    meinvoice_mail_template_draft_id = fields.Many2one(
        'mail.template',
        string='Mẫu email — Bản nháp',
        domain="[('model', '=', 'meinvoice.invoice')]",
        help='Mẫu email dùng khi gửi hóa đơn ở trạng thái Nháp (chưa cấp mã CQT).',
    )
    meinvoice_mail_template_published_id = fields.Many2one(
        'mail.template',
        string='Mẫu email — Đã cấp mã',
        domain="[('model', '=', 'meinvoice.invoice')]",
        help='Mẫu email dùng khi gửi hóa đơn đã phát hành (có số HĐ / mã CQT).',
    )
    meinvoice_mail_auto_send_draft = fields.Boolean(
        string='Tự động gửi email khi tạo bản nháp',
        default=False,
        help='Khi tạo hóa đơn nháp meInvoice và có email người mua, hệ thống tự gửi '
             'email theo mẫu "Bản nháp". Yêu cầu bật "Gửi email HĐĐT".',
    )
    meinvoice_mail_auto_send_published = fields.Boolean(
        string='Tự động gửi email khi phát hành thành công',
        default=True,
        help='Sau khi gửi hóa đơn lên CQT thành công và có email người mua, hệ thống '
             'tự gửi email theo mẫu "Đã cấp mã". Yêu cầu bật "Gửi email HĐĐT".',
    )
    meinvoice_mail_cc = fields.Char(
        string='Email CC mặc định',
        help='Danh sách email CC (cách nhau bằng dấu phẩy) thêm vào mọi email HĐĐT gửi đi. '
             'Để trống nếu không cần CC.',
    )
    meinvoice_mail_attach_pdf = fields.Boolean(
        string='Đính kèm PDF từ meInvoice (bản chính thức)',
        default=True,
        help='Khi gửi email hóa đơn đã cấp mã, tải PDF từ meInvoice và đính kèm vào email. '
             'Bỏ chọn nếu chỉ muốn dùng nội dung mẫu email.',
    )
    meinvoice_mail_attach_pdf_draft = fields.Boolean(
        string='Đính kèm PDF bản xem trước (bản nháp)',
        default=True,
        help='Khi gửi email bản nháp, tải PDF xem trước từ meInvoice (/invoice/unpublishview) '
             'và đính kèm vào email. Bỏ chọn nếu không muốn đính kèm PDF cho bản nháp.',
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
            cache, stale = self.env['amis.misa.vendor.cache'].sudo().lookup_for_partner(self, partner)
            if cache:
                misa_id = cache.account_object_id or ''
                if misa_id:
                    partner.sudo().write({'misa_account_object_id': misa_id})
                    if cache.partner_id.id != partner.id:
                        cache.sudo().write({'partner_id': partner.id})
                    account_object_id = misa_id
                    account_object_code = cache.account_object_code or account_object_code
                    account_object_name = cache.account_object_name or account_object_name
                    _logger.info('Resolved partner %s → account_object_id=%s from mirror cache', partner.name, misa_id)
            elif stale:
                _logger.warning('Bỏ qua account_object cache không còn dùng cho partner %s: %s', partner.name, stale.account_object_id)

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
            cache = self.env['amis.misa.vendor.cache'].sudo().search([
                ('config_id', '=', self.id),
                ('account_object_id', '=', uid_lower),
                ('is_deleted', '=', False),
                ('misa_inactive', '=', False),
            ], limit=1)
            resolved = cache.to_misa_item() if cache else None
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

        # Chưa cache → lookup mirror cache account_object
        search_name = expected_name.upper()
        cache = self.env['amis.misa.vendor.cache'].sudo().search([
            ('config_id', '=', self.id),
            ('account_object_name', '=ilike', expected_name),
            ('is_deleted', '=', False),
            ('misa_inactive', '=', False),
        ], limit=1)
        if cache and (cache.account_object_name or '').upper() == search_name:
            misa_id = cache.account_object_id or ''
            acode = cache.account_object_code or ''
            if misa_id:
                self.sudo().write({field_name: misa_id})
                _logger.info('Auto-cached shopee shop %s → %s = %s from mirror cache', identifier, field_name, misa_id)
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
        if include_token:
            self._ensure_token_valid()
        headers = self._build_headers(include_token=include_token)
        max_retries = 5 if path in (
            '/apir/sync/actopen/get_dictionary',
            '/apir/sync/actopen/get_dictionary_delete',
        ) else 3
        delay = 5  # seconds
        last_exc = None
        token_refreshed = False
        for attempt in range(max_retries):
            try:
                response = self._actopen_post_with_rate_limit(path, url, payload, headers, timeout)
                if include_token and response.status_code in (401, 403) and not token_refreshed and self.access_code:
                    _logger.info('AMIS token rejected with HTTP %s on %s, reconnecting once.', response.status_code, path)
                    self.sudo().action_connect_misa()
                    headers = self._build_headers(include_token=True)
                    token_refreshed = True
                    continue
                if response.status_code == 429:
                    wait = self._misa_429_wait_seconds(response, attempt, default_delay=delay)
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
                if include_token and not token_refreshed and self.access_code and self._is_misa_token_expired_error(err):
                    _logger.info('AMIS returned token error on %s (%s), reconnecting once.', path, err)
                    self.sudo().action_connect_misa()
                    headers = self._build_headers(include_token=True)
                    token_refreshed = True
                    continue
                raise UserError(f'MISA trả về lỗi: {err}')
            return body

        _logger.error('AMIS call failed after %d retries (429): %s', max_retries, path)
        raise UserError(f'Gọi API MISA thất bại sau {max_retries} lần thử: 429 Too Many Requests ({path})')

    def _actopen_post_with_rate_limit(self, path, url, payload, headers, timeout):
        if path not in (
            '/apir/sync/actopen/get_dictionary',
            '/apir/sync/actopen/get_dictionary_delete',
        ):
            return requests.post(url, json=payload, headers=headers, timeout=timeout)

        lock_name = 'amis_callback:%s:%s' % (path.rsplit('/', 1)[-1], self.env.cr.dbname)
        self.env.cr.execute("SELECT pg_advisory_lock(hashtext(%s)::bigint)", [lock_name])
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            time.sleep(_GET_DICTIONARY_MIN_INTERVAL)
            return response
        finally:
            self.env.cr.execute("SELECT pg_advisory_unlock(hashtext(%s)::bigint)", [lock_name])

    def _misa_429_wait_seconds(self, response, attempt, default_delay=5):
        retry_after = (response.headers.get('Retry-After') or '').strip() if response is not None else ''
        if retry_after:
            try:
                return max(1, min(int(float(retry_after)), 300))
            except (TypeError, ValueError):
                pass
        if response is not None and '/get_dictionary' in getattr(response, 'url', ''):
            return min(30 * (attempt + 1), 180)
        return default_delay * (2 ** attempt)

    def _is_misa_token_expired_error(self, error):
        text = unicodedata.normalize('NFKD', str(error or ''))
        text = ''.join(char for char in text if not unicodedata.combining(char)).lower()
        return 'token' in text and any(marker in text for marker in ('het han', 'expired', 'invalid'))

    def push_dictionary(self, dictionary_items):
        self.ensure_one()
        if not dictionary_items:
            return {'Success': True}
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'dictionary': dictionary_items,
        }
        result = self._post_actopen('/apir/sync/actopen/save_dictionary', payload, include_token=True)
        changed_data_types = set()
        for item in dictionary_items:
            try:
                dictionary_type = int(item.get('dictionary_type') or 0)
            except (TypeError, ValueError):
                continue
            if dictionary_type == 1:
                changed_data_types.add(1)  # account_object
            elif dictionary_type == 3:
                changed_data_types.add(2)  # inventory_item
            elif dictionary_type == 6:
                changed_data_types.add(4)  # unit
        if changed_data_types:
            self.clear_dictionary_cache(changed_data_types)
        self.upsert_unit_cache_from_dictionary_items(dictionary_items)
        self.upsert_inventory_cache_from_dictionary_items(dictionary_items)
        self.upsert_vendor_cache_from_dictionary_items(dictionary_items)
        return result

    def clear_dictionary_cache(self, data_types=None):
        self.ensure_one()
        data_types = data_types or []
        db_name = self.env.cr.dbname
        data_type_set = {int(data_type) for data_type in data_types}
        for data_type in data_type_set:
            _DICT_CACHE.pop((db_name, data_type), None)
        for key in list(_DICT_PAGE_CACHE):
            if key[0] == db_name and key[1] in data_type_set:
                _DICT_PAGE_CACHE.pop(key, None)
        cr = self.env.cr
        tx_cache = getattr(cr, '_amis_dict_cache', None)
        if tx_cache is not None:
            for data_type in data_types:
                tx_cache.pop(int(data_type), None)

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
        _DICT_CACHE[cache_key] = (time.monotonic(), all_items)
        tx_cache[key] = all_items
        _logger.info('MISA dictionary type=%d: fetched %d items (cached for this transaction)', data_type, len(all_items))
        return all_items

    def get_dictionary(self, data_type, branch_id=None, skip=0, take=100, last_sync_time=None, use_cache=True):
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
        cache_key = (
            self.env.cr.dbname,
            int(data_type),
            branch_id or '',
            int(skip or 0),
            take,
            last_sync_time or '',
        )
        now = time.monotonic()
        cached = _DICT_PAGE_CACHE.get(cache_key)
        if use_cache and cached and (now - cached[0]) < _DICT_CACHE_TTL:
            return cached[1]

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

        result = {
            'raw': body,
            'items': items,
            'custom_data': custom_data,
            'last_sync_time': custom_data.get('LastSyncTime'),
        }
        if use_cache:
            _DICT_PAGE_CACHE[cache_key] = (time.monotonic(), result)
        return result

    def get_dictionary_delete(self, data_type, branch_id=None, skip=0, take=100, last_sync_time=None):
        """Lay danh muc da bi xoa tu AMIS ke toan theo endpoint get_dictionary_delete."""
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
        body = self._post_actopen('/apir/sync/actopen/get_dictionary_delete', payload, include_token=True)

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

    def _misa_inventory_cache_request_cursor(self, cursor):
        cursor = (cursor or '').strip()
        if not cursor:
            return None
        minutes = max(int(self.misa_inventory_cache_overlap_minutes or 0), 0)
        if not minutes:
            return cursor
        try:
            parsed = datetime.fromisoformat(cursor.replace('Z', '+00:00'))
            return (parsed - timedelta(minutes=minutes)).isoformat()
        except Exception:
            _logger.warning('Khong parse duoc LastSyncTime hang hoa MISA "%s", dung nguyen cursor.', cursor)
            return cursor

    def _upsert_inventory_cache_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.inventory.cache'].sudo()
        created = 0
        updated = 0
        skipped = 0
        for item in items or []:
            item_id = (item.get('inventory_item_id') or item.get('id') or item.get('ID') or '').strip()
            if not item_id:
                skipped += 1
                continue
            existed = bool(Cache.search([
                ('config_id', '=', self.id),
                ('inventory_item_id', '=', item_id),
            ], limit=1))
            Cache.upsert_from_misa_item(self, item)
            if existed:
                updated += 1
            else:
                created += 1
        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _mark_inventory_cache_deleted_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.inventory.cache'].sudo()
        marked = 0
        skipped = 0
        for item in items or []:
            rec = Cache.mark_deleted_from_misa_item(self, item)
            if rec:
                marked += 1
            else:
                skipped += 1
        return {'deleted': marked, 'skipped': skipped}

    def upsert_inventory_cache_from_dictionary_items(self, dictionary_items):
        self.ensure_one()
        inventory_items = []
        for item in dictionary_items or []:
            try:
                dictionary_type = int(item.get('dictionary_type') or 0)
            except (TypeError, ValueError):
                dictionary_type = 0
            if dictionary_type == 3:
                inventory_items.append(item)
        if not inventory_items:
            return {'created': 0, 'updated': 0, 'skipped': 0}
        return self._upsert_inventory_cache_items(inventory_items)

    def _upsert_unit_cache_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.unit.cache'].sudo()
        created = 0
        updated = 0
        skipped = 0
        for item in items or []:
            item_id = (item.get('unit_id') or item.get('id') or item.get('ID') or '').strip()
            if not item_id:
                skipped += 1
                continue
            existed = bool(Cache.search([
                ('config_id', '=', self.id),
                ('unit_id', '=', item_id),
            ], limit=1))
            Cache.upsert_from_misa_item(self, item)
            if existed:
                updated += 1
            else:
                created += 1
        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _mark_unit_cache_deleted_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.unit.cache'].sudo()
        marked = 0
        skipped = 0
        for item in items or []:
            rec = Cache.mark_deleted_from_misa_item(self, item)
            if rec:
                marked += 1
            else:
                skipped += 1
        return {'deleted': marked, 'skipped': skipped}

    def upsert_unit_cache_from_dictionary_items(self, dictionary_items):
        self.ensure_one()
        unit_items = []
        for item in dictionary_items or []:
            try:
                dictionary_type = int(item.get('dictionary_type') or 0)
            except (TypeError, ValueError):
                dictionary_type = 0
            if dictionary_type == 6:
                unit_items.append(item)
        if not unit_items:
            return {'created': 0, 'updated': 0, 'skipped': 0}
        return self._upsert_unit_cache_items(unit_items)

    def _upsert_vendor_cache_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.vendor.cache'].sudo()
        created = 0
        updated = 0
        skipped = 0
        for item in items or []:
            item_id = (item.get('account_object_id') or item.get('id') or item.get('ID') or '').strip()
            if not item_id:
                skipped += 1
                continue
            existed = bool(Cache.search([
                ('config_id', '=', self.id),
                ('account_object_id', '=', item_id),
            ], limit=1))
            Cache.upsert_from_misa_item(self, item)
            if existed:
                updated += 1
            else:
                created += 1
        return {'created': created, 'updated': updated, 'skipped': skipped}

    def _mark_vendor_cache_deleted_items(self, items):
        self.ensure_one()
        Cache = self.env['amis.misa.vendor.cache'].sudo()
        marked = 0
        skipped = 0
        for item in items or []:
            rec = Cache.mark_deleted_from_misa_item(self, item)
            if rec:
                marked += 1
            else:
                skipped += 1
        return {'deleted': marked, 'skipped': skipped}

    def upsert_vendor_cache_from_dictionary_items(self, dictionary_items):
        self.ensure_one()
        vendor_items = []
        for item in dictionary_items or []:
            try:
                dictionary_type = int(item.get('dictionary_type') or 0)
            except (TypeError, ValueError):
                dictionary_type = 0
            if dictionary_type == 1:
                vendor_items.append(item)
        if not vendor_items:
            return {'created': 0, 'updated': 0, 'skipped': 0}
        return self._upsert_vendor_cache_items(vendor_items)

    def _misa_mirror_scope_data_type(self, scope):
        scope = scope or ''
        if scope == 'unit':
            return 4
        if scope == 'product':
            return 2
        if scope == 'vendor':
            return 1
        raise UserError('Phạm vi mirror MISA không hỗ trợ: %s' % scope)

    def _misa_mirror_cursor_field(self, scope, operation):
        if scope == 'unit':
            return 'misa_unit_cache_delete_last_sync_time' if operation == 'deleted' else 'misa_unit_cache_last_sync_time'
        if scope == 'product':
            return 'misa_inventory_cache_delete_last_sync_time' if operation == 'deleted' else 'misa_inventory_cache_last_sync_time'
        if scope == 'vendor':
            return 'misa_vendor_cache_delete_last_sync_time' if operation == 'deleted' else 'misa_vendor_cache_last_sync_time'
        return ''

    def _misa_mirror_skip_field(self, scope):
        if scope == 'unit':
            return 'unit_skip'
        if scope == 'vendor':
            return 'vendor_skip'
        return 'product_skip'

    def _misa_mirror_request_cursor(self, job):
        self.ensure_one()
        if job.mirror_mode == 'full':
            return None
        field_name = self._misa_mirror_cursor_field(job.scope, job.mirror_operation)
        return self._misa_inventory_cache_request_cursor(getattr(self, field_name, '') if field_name else '')

    def _misa_mirror_all_cursors_ready(self):
        self.ensure_one()
        return all([
            self.misa_unit_cache_last_sync_time,
            self.misa_unit_cache_delete_last_sync_time,
            self.misa_inventory_cache_last_sync_time,
            self.misa_inventory_cache_delete_last_sync_time,
            self.misa_vendor_cache_last_sync_time,
            self.misa_vendor_cache_delete_last_sync_time,
        ])

    def _misa_mirror_apply_cursor(self, job, cursor=None):
        self.ensure_one()
        cursor = cursor or job.next_cursor
        if not cursor:
            return
        field_name = self._misa_mirror_cursor_field(job.scope, job.mirror_operation)
        if field_name:
            self.sudo().write({field_name: cursor})

    def _misa_mirror_upsert_changed_cache(self, scope, items):
        if scope == 'unit':
            return self._upsert_unit_cache_items(items)
        if scope == 'product':
            return self._upsert_inventory_cache_items(items)
        if scope == 'vendor':
            return self._upsert_vendor_cache_items(items)
        return {'created': 0, 'updated': 0, 'skipped': len(items or [])}

    def _misa_mirror_mark_deleted_cache(self, scope, items):
        if scope == 'unit':
            return self._mark_unit_cache_deleted_items(items)
        if scope == 'product':
            return self._mark_inventory_cache_deleted_items(items)
        if scope == 'vendor':
            return self._mark_vendor_cache_deleted_items(items)
        return {'deleted': 0, 'skipped': len(items or [])}

    def _misa_mirror_apply_changed_page_to_odoo(self, scope, items, job):
        if scope == 'unit':
            return self._sync_misa_unit_cache_page_to_odoo(items, job=job)
        if scope == 'product':
            return self._sync_misa_inventory_cache_page_to_odoo(items, job=job)
        if scope == 'vendor':
            return self._sync_misa_vendor_cache_page_to_odoo(items, job=job)
        return {'updated': 0, 'skipped': len(items or []), 'error': 0}

    def _execute_misa_mirror_job(self, job):
        self.ensure_one()
        job.ensure_one()
        self.ensure_sync_ready()

        page_size = min(max(int(job.batch_size or 100), 1), 100)
        if not job.request_cursor and job.mirror_mode != 'full':
            job.sudo().write({'request_cursor': self._misa_mirror_request_cursor(job) or ''})
        request_cursor = None if job.mirror_mode == 'full' else (job.request_cursor or None)
        skip_field = self._misa_mirror_skip_field(job.scope)
        skip = int(getattr(job, skip_field) or 0)
        data_type = self._misa_mirror_scope_data_type(job.scope)

        if job.mirror_operation == 'deleted':
            result = self.get_dictionary_delete(
                data_type=data_type,
                skip=skip,
                take=page_size,
                last_sync_time=request_cursor,
            )
        else:
            result = self.get_dictionary(
                data_type=data_type,
                skip=skip,
                take=page_size,
                last_sync_time=request_cursor,
                use_cache=False,
            )

        if not job.next_cursor and result.get('last_sync_time'):
            job.sudo().write({'next_cursor': result.get('last_sync_time') or ''})

        items = result.get('items') or []
        if job.mirror_operation == 'deleted':
            cache_stats = self._misa_mirror_mark_deleted_cache(job.scope, items)
            odoo_stats = {'updated': 0, 'skipped': 0, 'error': 0}
        else:
            cache_stats = self._misa_mirror_upsert_changed_cache(job.scope, items)
            odoo_stats = self._misa_mirror_apply_changed_page_to_odoo(job.scope, items, job)

        next_skip = skip + len(items)
        has_more = len(items) >= page_size
        write_vals = {
            skip_field: next_skip,
            'total_count': job.total_count + len(items),
            'created_count': job.created_count + int(cache_stats.get('created') or 0),
            'updated_count': (
                job.updated_count
                + int(cache_stats.get('updated') or 0)
                + int(odoo_stats.get('updated') or 0)
            ),
            'skipped_count': (
                job.skipped_count
                + int(cache_stats.get('skipped') or 0)
                + int(odoo_stats.get('skipped') or 0)
            ),
            'error_count': job.error_count + int(odoo_stats.get('error') or 0),
            'processed_at': fields.Datetime.now(),
            'summary': (
                'Scope=%s, operation=%s, mode=%s, skip=%s -> %s, item=%s'
                % (job.scope, job.mirror_operation, job.mirror_mode, skip, next_skip, len(items))
            ),
        }
        if job.mirror_operation == 'deleted':
            write_vals['updated_count'] = job.updated_count + int(cache_stats.get('deleted') or 0)
        if has_more:
            write_vals['status'] = 'pending'
        else:
            write_vals['status'] = 'done'
            if not job.next_cursor:
                write_vals['next_cursor'] = fields.Datetime.now().isoformat()
        job.sudo().write(write_vals)
        if not has_more:
            self._misa_mirror_apply_cursor(job, cursor=write_vals.get('next_cursor') or job.next_cursor)
        return write_vals

    def _sync_misa_unit_cache_page_to_odoo(self, items, job=None):
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        updated = 0
        skipped = 0
        for item in items or []:
            unit_name = (item.get('unit_name') or '').strip()
            unit_id = (item.get('unit_id') or '').strip()
            if not unit_name or not unit_id:
                skipped += 1
                continue
            matched_uoms = Uom.search([('name', '=ilike', unit_name)])
            if not matched_uoms:
                skipped += 1
                continue
            for uom in matched_uoms:
                vals = {}
                if (uom.misa_unit_id or '').strip() != unit_id:
                    vals['misa_unit_id'] = unit_id
                if not vals:
                    continue
                change_summary = self._catalog_change_summary(uom, vals)
                uom.write(vals)
                self._catalog_log_change(
                    job, 'unit', 'map', 'uom.uom', uom.id,
                    unit_id, unit_name, unit_name, change_summary,
                )
                updated += 1
        return {'updated': updated, 'skipped': skipped, 'error': 0}

    def _sync_misa_inventory_cache_page_to_odoo(self, items, job=None):
        Product = self.env['product.product'].sudo().with_context(active_test=False)
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        codes = {
            (item.get('inventory_item_code') or '').strip()
            for item in items or []
            if (item.get('inventory_item_code') or '').strip()
        }
        products_by_code = {}
        if codes:
            for product in Product.search([('default_code', 'in', list(codes))]):
                code = (product.default_code or '').strip()
                if code:
                    products_by_code.setdefault(code, product)

        uoms_by_misa_id = {}
        for uom in Uom.search([('misa_unit_id', '!=', False)]):
            unit_id = (uom.misa_unit_id or '').strip()
            if unit_id:
                uoms_by_misa_id.setdefault(unit_id.lower(), []).append(uom)

        updated = 0
        skipped = 0
        error = 0
        for item in items or []:
            item_id = (item.get('inventory_item_id') or '').strip()
            code = (item.get('inventory_item_code') or '').strip()
            name = (item.get('inventory_item_name') or '').strip()
            if not item_id or not code or not name:
                skipped += 1
                continue
            product = products_by_code.get(code)
            if not product:
                skipped += 1
                continue
            self._ensure_catalog_product_units_mapped(item, uoms_by_misa_id, job=job)
            if self._log_catalog_product_uom_exception(product, item, uoms_by_misa_id, job=job):
                skipped += 1
                continue
            existing_misa_id = (product.misa_inventory_item_id or '').strip()
            if existing_misa_id and existing_misa_id.lower() != item_id.lower():
                skipped += 1
                summary = 'Bỏ qua cập nhật ID MISA: Odoo đang có=%s, MISA trả về=%s' % (existing_misa_id, item_id)
                self._catalog_log_change(
                    job, 'product', 'skip', 'product.product', product.id,
                    item_id, code, name, summary,
                )
                continue
            if existing_misa_id:
                continue
            write_vals = {'misa_inventory_item_id': item_id}
            change_summary = self._catalog_change_summary(product, write_vals)
            try:
                with self.env.cr.savepoint():
                    product.write(write_vals)
            except Exception as exc:
                error += 1
                self._catalog_log_change(
                    job, 'product', 'error', 'product.product', product.id,
                    item_id, code, name, 'Bỏ qua cập nhật: %s' % exc,
                )
                continue
            cache = self.env['amis.misa.inventory.cache'].sudo().search([
                ('config_id', '=', self.id),
                ('inventory_item_id', '=', item_id),
            ], limit=1)
            if cache and cache.product_id.id != product.id:
                cache.write({'product_id': product.id})
            self._catalog_log_change(
                job, 'product', 'map', 'product.product', product.id,
                item_id, code, name, change_summary,
            )
            updated += 1
        return {'updated': updated, 'skipped': skipped, 'error': error}

    def _misa_vendor_partner_maps(self):
        Partner = self.env['res.partner'].sudo().with_context(
            active_test=False,
            skip_misa_partner_sync=True,
        )
        partner_domain = [('parent_id', '=', False), ('supplier_rank', '>', 0)]
        if 'hlv_business_role' in Partner._fields:
            partner_domain = [
                ('parent_id', '=', False),
                '|',
                ('supplier_rank', '>', 0),
                ('hlv_business_role', '=', 'supplier'),
            ]
        partners = Partner.search(partner_domain)
        partners_by_misa_id = {}
        partners_by_ref = {}
        partners_by_tax = {}
        partners_by_tax_ref = {}
        ambiguous_tax_keys = set()
        for partner in partners:
            misa_id = (partner.misa_account_object_id or '').strip()
            ref_key = self._misa_vendor_match_code(partner.ref)
            tax_key = self._misa_vendor_match_tax(partner.vat)
            if misa_id:
                partners_by_misa_id.setdefault(misa_id.lower(), partner)
            if ref_key:
                partners_by_ref.setdefault(ref_key, partner)
            if tax_key:
                existing_tax_partner = partners_by_tax.get(tax_key)
                if existing_tax_partner and existing_tax_partner.id != partner.id:
                    ambiguous_tax_keys.add(tax_key)
                elif tax_key not in ambiguous_tax_keys:
                    partners_by_tax[tax_key] = partner
            if tax_key and ref_key:
                partners_by_tax_ref.setdefault((tax_key, ref_key), partner)
        for tax_key in ambiguous_tax_keys:
            partners_by_tax.pop(tax_key, None)
        return partners_by_misa_id, partners_by_ref, partners_by_tax, partners_by_tax_ref, ambiguous_tax_keys

    def _sync_misa_vendor_cache_page_to_odoo(self, items, job=None):
        maps = self._misa_vendor_partner_maps()
        partners_by_misa_id, partners_by_ref, partners_by_tax, partners_by_tax_ref, ambiguous_tax_keys = maps
        updated = 0
        skipped = 0
        for item in items or []:
            if not self._misa_truthy(item.get('is_vendor')):
                skipped += 1
                continue
            misa_id = (item.get('account_object_id') or '').strip()
            code = (item.get('account_object_code') or '').strip()
            name = (item.get('account_object_name') or '').strip()
            code_key = self._misa_vendor_match_code(code)
            tax_key = self._misa_vendor_match_tax(item.get('company_tax_code'))
            if not misa_id or not name:
                skipped += 1
                continue
            partner = partners_by_misa_id.get(misa_id.lower())
            match_source = 'misa_id' if partner else ''
            if not partner and tax_key and code_key:
                partner = partners_by_tax_ref.get((tax_key, code_key))
                match_source = 'tax_ref' if partner else ''
            if not partner and tax_key:
                partner = partners_by_tax.get(tax_key)
                match_source = 'tax' if partner else ''
            if not partner and code_key:
                partner = partners_by_ref.get(code_key)
                match_source = 'ref' if partner else ''
            if not partner:
                skipped += 1
                continue
            skip_reason = self._misa_vendor_match_skip_reason(partner, code, name, misa_id, tax_key, match_source)
            if skip_reason:
                skipped += 1
                self._catalog_log_change(
                    job, 'vendor', 'skip', 'res.partner', partner.id,
                    misa_id, code, name, skip_reason,
                )
                continue

            vals = self._misa_vendor_vals(item, partner=partner)
            write_vals = {
                key: value for key, value in vals.items()
                if not self._record_value_matches(partner, key, value)
            }
            partner_updated = False
            if write_vals:
                operation = 'map' if not (partner.misa_account_object_id or '').strip() and 'misa_account_object_id' in write_vals else 'update'
                change_summary = self._catalog_change_summary(partner, write_vals)
                partner.write(write_vals)
                self._catalog_log_change(
                    job, 'vendor', operation, 'res.partner', partner.id,
                    misa_id, code, name, change_summary,
                )
                partner_updated = True
            bank_updated = self._sync_misa_vendor_bank_accounts(partner, item, job=job)
            if bank_updated:
                self._catalog_log_change(
                    job, 'bank', 'update', 'res.partner', partner.id,
                    misa_id, code, name, 'Đã cập nhật thông tin tài khoản ngân hàng từ MISA',
                )
                partner_updated = True
            cache = self.env['amis.misa.vendor.cache'].sudo().search([
                ('config_id', '=', self.id),
                ('account_object_id', '=', misa_id),
            ], limit=1)
            if cache and cache.partner_id.id != partner.id:
                cache.write({'partner_id': partner.id})
            if cache:
                self._misa_link_vendor_bank_cache_to_partner(cache, partner)
            if partner_updated:
                updated += 1
                partners_by_misa_id[misa_id.lower()] = partner
                if code_key:
                    partners_by_ref[code_key] = partner
                if tax_key and tax_key not in ambiguous_tax_keys:
                    partners_by_tax[tax_key] = partner
                if tax_key and code_key:
                    partners_by_tax_ref[(tax_key, code_key)] = partner
        return {'updated': updated, 'skipped': skipped, 'error': 0}

    def _misa_link_vendor_bank_cache_to_partner(self, cache, partner):
        PartnerBank = self.env['res.partner.bank'].sudo().with_context(active_test=False)
        for line in cache.bank_line_ids:
            if not line.acc_number:
                continue
            bank = PartnerBank.search([
                ('partner_id', '=', partner.id),
                ('acc_number', '=', line.acc_number),
            ], limit=1)
            if bank and line.partner_bank_id.id != bank.id:
                line.write({'partner_bank_id': bank.id})

    def _sync_inventory_cache_changed_from_misa(self, full=False, page_size=100):
        self.ensure_one()
        page_size = min(max(int(page_size or 100), 1), 100)
        request_cursor = None if full else self._misa_inventory_cache_request_cursor(
            self.misa_inventory_cache_last_sync_time
        )
        skip = 0
        total = 0
        created = 0
        updated = 0
        skipped = 0
        next_cursor = False
        while True:
            result = self.get_dictionary(
                data_type=2,
                skip=skip,
                take=page_size,
                last_sync_time=request_cursor,
                use_cache=False,
            )
            if not next_cursor and result.get('last_sync_time'):
                next_cursor = result.get('last_sync_time')
            items = result.get('items') or []
            stats = self._upsert_inventory_cache_items(items)
            total += len(items)
            created += stats.get('created', 0)
            updated += stats.get('updated', 0)
            skipped += stats.get('skipped', 0)
            if len(items) < page_size:
                break
            skip += page_size

        if next_cursor:
            self.sudo().write({'misa_inventory_cache_last_sync_time': next_cursor})
        _logger.info(
            'MISA inventory cache changed sync: full=%s request_cursor=%s next_cursor=%s total=%d created=%d updated=%d skipped=%d',
            full, request_cursor, next_cursor, total, created, updated, skipped,
        )
        return {
            'total': total,
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'request_cursor': request_cursor,
            'next_cursor': next_cursor,
        }

    def _sync_inventory_cache_deleted_from_misa(self, full=False, page_size=100):
        self.ensure_one()
        page_size = min(max(int(page_size or 100), 1), 100)
        request_cursor = None if full else self._misa_inventory_cache_request_cursor(
            self.misa_inventory_cache_delete_last_sync_time
        )
        skip = 0
        total = 0
        deleted = 0
        skipped = 0
        next_cursor = False
        while True:
            result = self.get_dictionary_delete(
                data_type=2,
                skip=skip,
                take=page_size,
                last_sync_time=request_cursor,
            )
            if not next_cursor and result.get('last_sync_time'):
                next_cursor = result.get('last_sync_time')
            items = result.get('items') or []
            stats = self._mark_inventory_cache_deleted_items(items)
            total += len(items)
            deleted += stats.get('deleted', 0)
            skipped += stats.get('skipped', 0)
            if len(items) < page_size:
                break
            skip += page_size

        if next_cursor:
            self.sudo().write({'misa_inventory_cache_delete_last_sync_time': next_cursor})
        _logger.info(
            'MISA inventory cache deleted sync: full=%s request_cursor=%s next_cursor=%s total=%d deleted=%d skipped=%d',
            full, request_cursor, next_cursor, total, deleted, skipped,
        )
        return {
            'total': total,
            'deleted': deleted,
            'skipped': skipped,
            'request_cursor': request_cursor,
            'next_cursor': next_cursor,
        }

    def _sync_inventory_cache_from_misa(self, full=False):
        self.ensure_one()
        self.ensure_sync_ready()
        changed = self._sync_inventory_cache_changed_from_misa(full=full)
        deleted = self._sync_inventory_cache_deleted_from_misa(full=full)
        return {'changed': changed, 'deleted': deleted}

    def action_sync_inventory_cache_full(self):
        return self.action_enqueue_misa_mirror_full()

    def action_sync_inventory_cache_incremental(self):
        return self.action_enqueue_misa_mirror_incremental()

    def action_open_inventory_cache(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cache hàng hóa MISA',
            'res_model': 'amis.misa.inventory.cache',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
            'target': 'current',
        }

    @api.model
    def cron_sync_inventory_cache_from_misa(self):
        return self.cron_sync_misa_mirror()

    def push_inward_voucher(self, voucher_payload, dictionary_items=None, reference_items=None):
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        if reference_items:
            payload['reference'] = reference_items
        _logger.info(
            'AMIS save inward payload:\n%s',
            json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        )
        result = self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)
        _logger.info(
            'AMIS save inward response: %s',
            json.dumps(result, ensure_ascii=False, default=str),
        )
        return result

    def push_purchase_order(self, voucher_payload, dictionary_items=None):
        """Push pu_order (Don mua hang, voucher_type=21) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        _logger.info(
            'AMIS save purchase order payload:\n%s',
            json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        )
        result = self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)
        _logger.info(
            'AMIS save purchase order response: %s',
            json.dumps(result, ensure_ascii=False, default=str),
        )
        return result

    def push_payment_request(self, voucher_payload):
        """Push ba_withdraw (de nghi chi tien nha cung cap, voucher_type=3) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': [],
        }
        _logger.info(
            'AMIS save payment request payload:\n%s',
            json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        )
        result = self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)
        _logger.info(
            'AMIS save payment request response: %s',
            json.dumps(result, ensure_ascii=False, default=str),
        )
        return result

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
        """Tự động refresh token meInvoice nếu chưa có hoặc đã quá 13 ngày.

        Bọc trong try/except để lỗi refresh không làm fail cả luồng gọi API.
        Nếu refresh thất bại, log cảnh báo và tiếp tục dùng token cũ (nếu còn).
        """
        self.ensure_one()
        if not self.meinvoice_enabled:
            return
        if not self.meinvoice_token or not self.meinvoice_token_acquired:
            if self.meinvoice_username and self.meinvoice_password:
                _logger.info('meInvoice: token chưa có, tự động lấy mới...')
                try:
                    self.action_connect_meinvoice()
                except Exception as exc:
                    _logger.warning('meInvoice: tự động lấy token thất bại: %s', exc)
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
            try:
                self.action_connect_meinvoice()
            except Exception as exc:
                _logger.warning(
                    'meInvoice: refresh token thất bại, tiếp tục dùng token cũ: %s', exc
                )

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
        # API trả về data dưới dạng JSON string (ví dụ: "[]") — cần parse
        if isinstance(data, str):
            try:
                import json as _json
                data = _json.loads(data)
            except Exception:
                data = []
        if isinstance(data, dict):
            data = [data]
        _logger.info('meInvoice invoice status: %s', data)
        return data

    def get_meinvoice_download_url(self, transaction_id, file_type='PDF'):
        """Tải file hóa đơn từ meInvoice /invoice/download.

        Body: ["TransactionID"] (list of string)
        Params: invoiceWithCode=true, invoiceCalcu=false, downloadDataType=pdf/xml
        Response Data: base64 encoded file content (JSON string wrapping list of dicts)

        Returns:
            str — base64 encoded file content.
        """
        self.ensure_one()
        if not transaction_id:
            raise UserError('Thiếu TransactionID để tải hóa đơn.')
        import json as _json
        params = {
            'invoiceWithCode': 'true',
            'invoiceCalcu': 'false',
            'downloadDataType': file_type.lower(),
        }
        body = self._post_meinvoice('/invoice/download', payload=[transaction_id], params=params)
        data = body.get('data') or body.get('Data') or '[]'
        if isinstance(data, str):
            try:
                data = _json.loads(data)
            except Exception:
                data = []
        if isinstance(data, dict):
            data = [data]
        if not data:
            raise UserError('meInvoice không trả về dữ liệu hóa đơn.')
        item = data[0]
        if not isinstance(item, dict):
            raise UserError('meInvoice trả về định dạng không xác định: %s' % str(item)[:200])
        err_code = (item.get('ErrorCode') or item.get('errorCode') or '').strip()
        if err_code:
            if err_code == 'InvoiceNotExist':
                raise UserError(
                    'Hóa đơn đã được cấp số trên meInvoice nhưng chưa được chuyển tiếp lên Cơ quan Thuế.\n'
                    'Vui lòng chờ meInvoice xử lý hoặc liên hệ meInvoice để kiểm tra trạng thái hóa đơn.'
                )
            raise UserError('meInvoice lỗi tải hóa đơn: %s' % err_code)
        b64_data = item.get('Data') or item.get('data') or ''
        if not b64_data:
            raise UserError('meInvoice không trả về nội dung file hóa đơn.')
        _logger.info('meInvoice download (%s): nhận được %d bytes base64', file_type, len(b64_data))
        return b64_data

    def get_meinvoice_pdf_bytes(self, transaction_id):
        """Tải PDF hóa đơn từ meInvoice và trả về raw bytes.

        Returns:
            bytes — nội dung PDF, hoặc b'' nếu không tải được.
        """
        self.ensure_one()
        if not transaction_id:
            return b''
        url = self.get_meinvoice_download_url(transaction_id, file_type='PDF')
        if not url:
            return b''
        try:
            resp = requests.get(url, timeout=30, allow_redirects=True, headers={
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'vi,en-US;q=0.9,en;q=0.8',
                'upgrade-insecure-requests': '1',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            })
            resp.raise_for_status()
            content = resp.content or b''
            if not content or (b'%PDF' not in content[:10] and 'pdf' not in resp.headers.get('Content-Type', '').lower()):
                _logger.warning('meInvoice: tải PDF published không có nội dung PDF (%s)', transaction_id)
                return b''
            return content
        except Exception as exc:
            _logger.warning('meInvoice: tải PDF thất bại (%s): %s', transaction_id, exc)
            return b''

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
                # Nếu InvCode đã được lưu → CQT đã cấp mã (trả về từ POST /invoice)
                if inv.inv_code:
                    inv.sudo().write({
                        'state': 'accepted',
                        'cqt_check_queued': False,
                        'cqt_checked_at': now,
                    })
                    _logger.info(
                        'meInvoice cron: %s đã có InvCode=%s → đánh dấu accepted',
                        inv.transaction_id, inv.inv_code,
                    )
                else:
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


    def cron_sync_catalog_from_misa(self):
        _logger.info('Cron MISA cũ đã tắt. Dùng cron mirror MISA thay thế.')
        return True

    @api.model
    def cron_sync_misa_mirror(self):
        configs = self.sudo().search([('active', '=', True)])
        if not configs:
            _logger.info('Bỏ qua cron mirror MISA: chưa có cấu hình AMIS callback.')
            return True
        for config in configs:
            try:
                config._ensure_misa_mirror_jobs(trigger='cron')
            except Exception:
                _logger.exception('Tạo job mirror MISA thất bại cho cấu hình %s', config.id)
        return True

    def _misa_mirror_has_open_jobs(self):
        self.ensure_one()
        return bool(self.env['amis.catalog.sync.job'].sudo().search([
            ('config_id', '=', self.id),
            ('direction', '=', 'from_misa'),
            ('scope', 'in', ('unit', 'product', 'vendor')),
            ('status', 'in', ('pending', 'running', 'error')),
        ], limit=1))

    def _misa_mirror_last_done_at(self):
        self.ensure_one()
        job = self.env['amis.catalog.sync.job'].sudo().search([
            ('config_id', '=', self.id),
            ('direction', '=', 'from_misa'),
            ('scope', 'in', ('unit', 'product', 'vendor')),
            ('status', 'in', ('done', 'error')),
        ], order='processed_at desc, create_date desc', limit=1)
        return job.processed_at or job.create_date if job else False

    def _ensure_misa_mirror_jobs(self, trigger='cron'):
        self.ensure_one()
        if self._misa_mirror_has_open_jobs():
            return self.env['amis.catalog.sync.job']
        mode = 'incremental' if self._misa_mirror_all_cursors_ready() else 'full'
        if mode == 'incremental':
            last_done = self._misa_mirror_last_done_at()
            if last_done and (fields.Datetime.now() - last_done).total_seconds() < 300:
                return self.env['amis.catalog.sync.job']
        return self._enqueue_misa_mirror_jobs(mode=mode, trigger=trigger)

    def _enqueue_misa_mirror_jobs(self, mode='incremental', trigger='manual'):
        self.ensure_one()
        Job = self.env['amis.catalog.sync.job'].sudo()
        jobs = Job
        for scope, operation in (
            ('unit', 'changed'),
            ('unit', 'deleted'),
            ('product', 'changed'),
            ('product', 'deleted'),
            ('vendor', 'changed'),
            ('vendor', 'deleted'),
        ):
            jobs |= Job.enqueue_mirror(
                self,
                scope=scope,
                operation=operation,
                mode=mode,
                trigger=trigger,
            )
        return jobs

    def action_enqueue_misa_mirror_full(self):
        self.ensure_one()
        jobs = self._enqueue_misa_mirror_jobs(mode='full', trigger='manual')
        return self._open_misa_mirror_jobs(jobs)

    def action_enqueue_misa_mirror_incremental(self):
        self.ensure_one()
        jobs = self._enqueue_misa_mirror_jobs(mode='incremental', trigger='manual')
        return self._open_misa_mirror_jobs(jobs)

    def action_open_misa_mirror_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hàng đợi mirror MISA',
            'res_model': 'amis.catalog.sync.job',
            'view_mode': 'list,form',
            'domain': [
                ('config_id', '=', self.id),
                ('direction', '=', 'from_misa'),
                ('scope', 'in', ('unit', 'product', 'vendor')),
            ],
            'context': {'search_default_pending': 1},
            'target': 'current',
        }

    def _open_misa_mirror_jobs(self, jobs):
        jobs = jobs.sudo()
        action = self.action_open_misa_mirror_jobs()
        if len(jobs) == 1:
            action.update({'view_mode': 'form', 'res_id': jobs.id})
        return action

    def action_sync_catalog_to_odoo(self):
        return self.action_enqueue_misa_mirror_incremental()

    def action_sync_product_catalog_to_odoo(self):
        return self.action_enqueue_misa_mirror_incremental()

    def action_sync_vendor_catalog_to_odoo(self):
        return self.action_enqueue_misa_mirror_incremental()

    def action_sync_catalog_unmapped_only(self):
        return self.action_enqueue_misa_mirror_incremental()

    def _open_catalog_sync_job(self, job):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hàng đợi mirror MISA',
            'res_model': 'amis.catalog.sync.job',
            'view_mode': 'form',
            'res_id': job.id,
            'target': 'current',
        }

    def _catalog_sync_notification(self, title, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success',
                'sticky': True,
            },
        }

    def _sync_catalog_from_misa_to_odoo(self, unmapped_only=False, create_missing=True, job=None):
        self.ensure_one()
        product_result = self._sync_product_catalog_from_misa_to_odoo(
            unmapped_only=unmapped_only,
            job=job,
        )
        product_has_more = not bool(product_result.get('complete', True))
        vendor_complete = True
        if product_has_more:
            vendor_summary = {'total': 0, 'updated': 0, 'created': 0, 'skipped': 0, 'error': 0}
        else:
            vendor_result = self._sync_vendor_catalog_from_misa_to_odoo(
                unmapped_only=unmapped_only,
                create_missing=create_missing,
                job=job,
            )
            vendor_summary = vendor_result.get('vendors') or {}
            vendor_complete = bool(vendor_result.get('complete', True))

        product_summary = product_result.get('products') or {}
        unit_summary = product_result.get('units') or {}
        totals = {
            'total': unit_summary['total'] + product_summary['total'] + vendor_summary['total'],
            'updated': unit_summary['updated'] + product_summary['updated'] + vendor_summary['updated'],
            'created': unit_summary.get('created', 0) + product_summary['created'] + vendor_summary['created'],
            'skipped': unit_summary.get('skipped', 0) + product_summary.get('skipped', 0) + vendor_summary.get('skipped', 0),
            'error': unit_summary.get('error', 0) + product_summary.get('error', 0) + vendor_summary.get('error', 0),
        }
        msg = (
            'Mirror MISA hoàn tất!\n'
            '• Hàng hóa: map/cập nhật %(updated_product)s, tạo mới %(created_product)s '
            '(trên %(total_product)s mục MISA).\n'
            '• Đơn vị tính: map/cập nhật %(updated_unit)s (trên %(total_unit)s mục MISA).\n'
            '• Nhà cung cấp: map/cập nhật %(updated_vendor)s, tạo mới %(created_vendor)s '
            '(trên %(total_vendor)s mục MISA).'
        ) % {
            'updated_product': product_summary['updated'],
            'created_product': product_summary['created'],
            'total_product': product_summary['total'],
            'updated_unit': unit_summary['updated'],
            'total_unit': unit_summary['total'],
            'updated_vendor': vendor_summary['updated'],
            'created_vendor': vendor_summary['created'],
            'total_vendor': vendor_summary['total'],
        }
        return {
            'message': msg,
            'units': unit_summary,
            'products': product_summary,
            'vendors': vendor_summary,
            'totals': totals,
            'complete': (not product_has_more) and vendor_complete,
        }

    def _sync_product_catalog_from_misa_to_odoo(self, unmapped_only=False, job=None):
        self.ensure_one()
        if job and job.unit_sync_done:
            unit_summary = {'total': 0, 'updated': 0, 'created': 0, 'skipped': 0, 'error': 0}
        else:
            unit_summary = self._sync_misa_units_to_odoo(unmapped_only=unmapped_only, job=job)
            if job:
                job.sudo().write({'unit_sync_done': True})
        product_summary = self._sync_misa_products_to_odoo(
            unmapped_only=unmapped_only,
            create_missing=False,
            job=job,
        )
        product_has_more = bool(product_summary.get('has_more'))
        totals = {
            'total': unit_summary['total'] + product_summary['total'],
            'updated': unit_summary['updated'] + product_summary['updated'],
            'created': unit_summary.get('created', 0) + product_summary['created'],
            'skipped': unit_summary.get('skipped', 0) + product_summary.get('skipped', 0),
            'error': unit_summary.get('error', 0) + product_summary.get('error', 0),
        }
        msg = (
            'Mirror sản phẩm MISA %(status)s.\n'
            '• Hàng hóa: map/cập nhật %(updated_product)s, tạo mới %(created_product)s '
            '(trên %(total_product)s mục MISA).\n'
            '• Đơn vị tính: map/cập nhật %(updated_unit)s (trên %(total_unit)s mục MISA).'
        ) % {
            'status': 'đang chạy theo batch' if product_has_more else 'hoàn tất',
            'updated_product': product_summary['updated'],
            'created_product': product_summary['created'],
            'total_product': product_summary['total'],
            'updated_unit': unit_summary['updated'],
            'total_unit': unit_summary['total'],
        }
        return {
            'message': msg,
            'units': unit_summary,
            'products': product_summary,
            'totals': totals,
            'complete': not product_has_more,
        }

    def _sync_vendor_catalog_from_misa_to_odoo(self, unmapped_only=False, create_missing=True, job=None):
        self.ensure_one()
        if job and job.vendor_sync_done:
            vendor_summary = {'total': 0, 'updated': 0, 'created': 0, 'skipped': 0, 'error': 0}
            vendor_has_more = False
        else:
            batch_skip = int(job.vendor_skip or 0) if job else 0
            batch_take = int(job.batch_size or 100) if job else 100
            vendor_summary = self._sync_misa_vendors_to_odoo(
                unmapped_only=unmapped_only,
                create_missing=create_missing,
                job=job,
                skip=batch_skip,
                take=batch_take,
            )
            vendor_has_more = bool(vendor_summary.get('has_more'))
            if job:
                job.sudo().write({'vendor_sync_done': not vendor_has_more})
        msg = (
            'Mirror nhà cung cấp MISA %(status)s.\n'
            '• Nhà cung cấp: map/cập nhật %(updated_vendor)s, tạo mới %(created_vendor)s '
            '(trên %(total_vendor)s mục MISA).'
        ) % {
            'status': 'đang chạy theo batch' if vendor_has_more else 'hoàn tất',
            'updated_vendor': vendor_summary['updated'],
            'created_vendor': vendor_summary['created'],
            'total_vendor': vendor_summary['total'],
        }
        return {
            'message': msg,
            'vendors': vendor_summary,
            'totals': vendor_summary,
            'complete': not vendor_has_more,
        }

    def _sync_misa_units_to_odoo(self, unmapped_only=False, job=None):
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        domain = []
        if unmapped_only:
            domain.append(('misa_unit_id', 'in', [False, '']))
        uoms = Uom.search(domain)
        name_to_uoms = {}
        for uom in uoms:
            name = (uom.name or '').strip()
            if name:
                name_to_uoms.setdefault(name.casefold(), []).append(uom)

        unit_items = self._get_all_dictionary(4)
        updated = 0
        skipped = 0
        for item in unit_items:
            unit_name = (item.get('unit_name') or '').strip()
            unit_id = (item.get('unit_id') or '').strip()
            if not unit_name or not unit_id:
                skipped += 1
                continue
            matched_uoms = name_to_uoms.get(unit_name.casefold(), [])
            for uom in matched_uoms:
                vals = {}
                if (uom.misa_unit_id or '').strip() != unit_id:
                    vals['misa_unit_id'] = unit_id
                if vals:
                    change_summary = self._catalog_change_summary(uom, vals)
                    uom.write(vals)
                    self._catalog_log_change(
                        job, 'unit', 'map', 'uom.uom', uom.id,
                        unit_id, unit_name, unit_name, change_summary,
                    )
                    updated += 1
        return {'total': len(unit_items), 'updated': updated, 'created': 0, 'skipped': skipped, 'error': 0}

    def _sync_misa_products_to_odoo(self, unmapped_only=False, create_missing=True, job=None):
        Product = self.env['product.product'].sudo().with_context(active_test=False)
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        batch_skip = int(job.product_skip or 0) if job else 0
        batch_take = int(job.batch_size or 100) if job else 100
        if batch_take <= 0:
            batch_take = 100

        result = self.get_dictionary(data_type=2, skip=batch_skip, take=batch_take)
        inv_items = result.get('items') or []
        self._upsert_inventory_cache_items(inv_items)
        codes = {
            (item.get('inventory_item_code') or '').strip()
            for item in inv_items
            if (item.get('inventory_item_code') or '').strip()
        }
        products_by_code = {}
        if codes:
            for product in Product.search([('default_code', 'in', list(codes))]):
                code = (product.default_code or '').strip()
                if code:
                    products_by_code.setdefault(code, product)

        uoms_by_misa_id = {}
        for uom in Uom.search([('misa_unit_id', '!=', False)]):
            unit_id = (uom.misa_unit_id or '').strip()
            if unit_id:
                uoms_by_misa_id.setdefault(unit_id.lower(), []).append(uom)

        updated = 0
        created = 0
        skipped = 0
        error = 0
        for item in inv_items:
            item_id = (item.get('inventory_item_id') or '').strip()
            code = (item.get('inventory_item_code') or '').strip()
            name = (item.get('inventory_item_name') or '').strip()
            if not item_id or not code or not name:
                skipped += 1
                continue
            product = products_by_code.get(code)
            if not product:
                skipped += 1
                continue
            if product:
                if unmapped_only and (product.misa_inventory_item_id or '').strip():
                    continue
                self._ensure_catalog_product_units_mapped(item, uoms_by_misa_id, job=job)
                if self._log_catalog_product_uom_exception(product, item, uoms_by_misa_id, job=job):
                    skipped += 1
                existing_misa_id = (product.misa_inventory_item_id or '').strip()
                if existing_misa_id and existing_misa_id.lower() != item_id.lower():
                    skipped += 1
                    summary = 'Bỏ qua cập nhật ID MISA: Odoo đang có=%s, MISA trả về=%s' % (existing_misa_id, item_id)
                    _logger.warning('Xung đột map hàng hóa MISA cho %s (%s): %s', product.display_name, code, summary)
                    self._catalog_log_change(
                        job, 'product', 'skip', 'product.product', product.id,
                        item_id, code, name, summary,
                    )
                    continue
                write_vals = {}
                if not existing_misa_id:
                    write_vals['misa_inventory_item_id'] = item_id
                if write_vals:
                    change_summary = self._catalog_change_summary(product, write_vals)
                    try:
                        with self.env.cr.savepoint():
                            product.write(write_vals)
                    except Exception as exc:
                        error += 1
                        _logger.warning(
                            'Bỏ qua cập nhật hàng hóa MISA cho %s (%s): %s',
                            product.display_name, code, exc,
                        )
                        self._catalog_log_change(
                            job, 'product', 'error', 'product.product', product.id,
                            item_id, code, name, 'Bỏ qua cập nhật: %s' % exc,
                        )
                        continue
                    self._catalog_log_change(
                        job, 'product', 'map', 'product.product', product.id,
                        item_id, code, name, change_summary,
                    )
                    updated += 1
                continue
        next_skip = batch_skip + len(inv_items)
        has_more = len(inv_items) >= min(batch_take, 100)
        if job:
            job.sudo().write({'product_skip': next_skip})
        return {
            'total': len(inv_items),
            'updated': updated,
            'created': created,
            'skipped': skipped,
            'error': error,
            'skip': batch_skip,
            'next_skip': next_skip,
            'has_more': has_more,
        }

    def _misa_catalog_product_unit_entries(self, item):
        entries = []

        def add(unit_id, unit_name=''):
            unit_id = (unit_id or '').strip()
            unit_name = (unit_name or '').strip()
            if unit_id and not unit_name:
                unit_name = self._misa_catalog_unit_name_by_id(unit_id)
            if unit_id:
                entries.append({'unit_id': unit_id, 'unit_name': unit_name})

        add(item.get('unit_id'), item.get('unit_name'))
        add(item.get('main_unit_id'), item.get('main_unit_name'))
        raw_converts = (
            item.get('inventory_item_unit_convert')
            or item.get('inventory_item_unit_converts')
            or item.get('unit_convert')
            or item.get('unit_list')
            or []
        )
        if isinstance(raw_converts, str):
            try:
                raw_converts = json.loads(raw_converts) if raw_converts.strip() else []
            except Exception:
                raw_converts = []
        if isinstance(raw_converts, dict):
            raw_converts = [raw_converts]
        if isinstance(raw_converts, list):
            for convert in raw_converts:
                if not isinstance(convert, dict):
                    continue
                add(
                    convert.get('unit_id'),
                    convert.get('unit_name') or convert.get('unit_name_convert'),
                )

        seen = set()
        result = []
        for entry in entries:
            key = (entry['unit_id'].lower(), entry.get('unit_name', '').casefold())
            if key in seen:
                continue
            seen.add(key)
            result.append(entry)
        return result

    def _misa_catalog_unit_name_by_id(self, unit_id):
        unit_id = (unit_id or '').strip().lower()
        if not unit_id:
            return ''
        cache = self.env['amis.misa.unit.cache'].sudo().search([
            ('config_id', '=', self.id),
            ('unit_id', '=', unit_id),
        ], limit=1)
        if cache:
            return (cache.unit_name or '').strip()
        return ''

    def _ensure_catalog_product_units_mapped(self, item, uoms_by_misa_id, job=None):
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        for entry in self._misa_catalog_product_unit_entries(item):
            unit_id = (entry.get('unit_id') or '').strip()
            unit_name = (entry.get('unit_name') or '').strip()
            if not unit_id or not unit_name:
                continue
            key = unit_id.lower()
            existing_candidates = uoms_by_misa_id.setdefault(key, [])
            matched_uoms = Uom.search([('name', '=ilike', unit_name)])
            for uom in matched_uoms:
                if uom not in existing_candidates:
                    existing_candidates.append(uom)
                if (uom.misa_unit_id or '').strip() == unit_id:
                    continue
                old_value = uom.misa_unit_id or ''
                uom.write({'misa_unit_id': unit_id})
                self._catalog_log_change(
                    job, 'unit', 'map', 'uom.uom', uom.id,
                    unit_id, unit_name, unit_name,
                    'Map ID ĐVT theo hàng hóa MISA: %s -> %s' % (old_value, unit_id),
                )

    def _log_catalog_product_uom_exception(self, product, item, uoms_by_misa_id, job=None):
        unit_id = (item.get('unit_id') or item.get('main_unit_id') or '').strip().lower()
        if not unit_id:
            return False
        code = (item.get('inventory_item_code') or '').strip()
        name = (item.get('inventory_item_name') or '').strip()
        item_id = (item.get('inventory_item_id') or '').strip()
        candidates = uoms_by_misa_id.get(unit_id) or []
        current_uoms = (product.uom_id | product.uom_po_id).filtered(lambda uom: uom)
        if candidates and any(uom in current_uoms for uom in candidates):
            return False
        current_names = {
            (uom.name or '').strip().casefold()
            for uom in current_uoms
            if (uom.name or '').strip()
        }
        candidate_names = {
            (uom.name or '').strip().casefold()
            for uom in candidates
            if (uom.name or '').strip()
        }
        misa_names = {
            (entry.get('unit_name') or '').strip().casefold()
            for entry in self._misa_catalog_product_unit_entries(item)
            if (entry.get('unit_name') or '').strip()
        }
        if current_names & (candidate_names | misa_names):
            return False
        misa_uom_text = ', '.join(
            '%s [%s]' % (uom.display_name, uom.category_id.display_name if uom.category_id else '')
            for uom in candidates
        ) or ', '.join(entry.get('unit_name') or entry.get('unit_id') or '' for entry in self._misa_catalog_product_unit_entries(item)) or unit_id
        odoo_uom_text = ', '.join(
            '%s [%s]' % (uom.display_name, uom.category_id.display_name if uom.category_id else '')
            for uom in current_uoms
        )
        summary = 'ĐVT lệch thật, cần xử lý mapping thủ công: Odoo=%s; MISA=%s. Chưa cập nhật ĐVT sản phẩm.' % (
            odoo_uom_text,
            misa_uom_text,
        )
        _logger.warning('Ngoại lệ ĐVT hàng hóa MISA cho %s (%s): %s', product.display_name, code, summary)
        self._catalog_log_change(
            job, 'product', 'skip', 'product.product', product.id,
            item_id, code, name, summary,
            issue_type='uom_mismatch',
        )
        return True

    def _misa_product_vals(self, item, uoms_by_misa_id, product=None):
        Product = self.env['product.product']
        vals = {
            'name': (item.get('inventory_item_name') or '').strip(),
            'default_code': (item.get('inventory_item_code') or '').strip(),
            'misa_inventory_item_id': (item.get('inventory_item_id') or '').strip(),
        }
        if 'purchase_ok' in Product._fields:
            vals['purchase_ok'] = True
        if 'sale_ok' in Product._fields:
            vals['sale_ok'] = True
        if 'active' in Product._fields:
            vals['active'] = not bool(item.get('inactive'))
        unit_id = (item.get('unit_id') or item.get('main_unit_id') or '').strip().lower()
        uom = self._select_catalog_product_uom(uoms_by_misa_id.get(unit_id) or [], product=product)
        if uom and 'uom_id' in Product._fields:
            vals['uom_id'] = uom.id
        if uom and 'uom_po_id' in Product._fields:
            vals['uom_po_id'] = uom.id
        return vals

    def _select_catalog_product_uom(self, candidates, product=None):
        if not candidates:
            return self.env['uom.uom']
        if product:
            for uom in candidates:
                if uom == product.uom_id or uom == product.uom_po_id:
                    return uom
            if product.uom_id:
                for uom in candidates:
                    if uom.category_id == product.uom_id.category_id:
                        return uom
        return candidates[0]

    def _filter_catalog_product_uom_write_vals(self, product, write_vals, item, job=None):
        uom_fields = [field for field in ('uom_id', 'uom_po_id') if field in write_vals]
        if not uom_fields:
            return write_vals, 0

        Uom = self.env['uom.uom'].sudo()
        StockMove = self.env['stock.move'].sudo()
        has_stock_moves = bool(StockMove.search([('product_id', '=', product.id)], limit=1))
        reasons = []
        details = []
        for field_name in uom_fields:
            old_uom = product[field_name]
            new_uom = Uom.browse(write_vals[field_name]) if write_vals[field_name] else Uom
            old_category = old_uom.category_id.display_name if old_uom and old_uom.category_id else ''
            new_category = new_uom.category_id.display_name if new_uom and new_uom.category_id else ''
            details.append(
                '%s: %s [%s] -> %s [%s]' % (
                    field_name,
                    old_uom.display_name if old_uom else '',
                    old_category,
                    new_uom.display_name if new_uom else '',
                    new_category,
                )
            )
            old_name = (old_uom.name or '').strip().casefold() if old_uom else ''
            new_name = (new_uom.name or '').strip().casefold() if new_uom else ''
            if old_uom and new_uom and old_uom.category_id != new_uom.category_id and old_name != new_name:
                reasons.append('%s khác nhóm ĐVT (%s -> %s)' % (field_name, old_category, new_category))

        if has_stock_moves:
            reasons.append('sản phẩm đã có phát sinh kho')
        if not reasons:
            return write_vals, 0

        filtered_vals = dict(write_vals)
        for field_name in uom_fields:
            filtered_vals.pop(field_name, None)
        code = (item.get('inventory_item_code') or '').strip()
        name = (item.get('inventory_item_name') or '').strip()
        item_id = (item.get('inventory_item_id') or '').strip()
        summary = 'Bỏ qua cập nhật ĐVT: %s. Lý do: %s' % (
            '; '.join(details),
            '; '.join(dict.fromkeys(reasons)),
        )
        _logger.warning(
            'Bỏ qua cập nhật ĐVT MISA cho hàng hóa %s (%s): %s',
            product.display_name,
            code,
            summary,
        )
        self._catalog_log_change(
            job, 'product', 'skip', 'product.product', product.id,
            item_id, code, name, summary,
            issue_type='uom_mismatch',
        )
        return filtered_vals, 1

    def _sync_misa_vendors_to_odoo(self, unmapped_only=False, create_missing=True, job=None, skip=0, take=None):
        Partner = self.env['res.partner'].sudo().with_context(
            active_test=False,
            skip_misa_partner_sync=True,
        )
        partner_domain = [('parent_id', '=', False), ('supplier_rank', '>', 0)]
        if 'hlv_business_role' in Partner._fields:
            partner_domain = [
                ('parent_id', '=', False),
                '|',
                ('supplier_rank', '>', 0),
                ('hlv_business_role', '=', 'supplier'),
            ]
        partners = Partner.search(partner_domain)
        partners_by_misa_id = {}
        partners_by_ref = {}
        partners_by_tax = {}
        partners_by_tax_ref = {}
        ambiguous_tax_keys = set()
        for partner in partners:
            misa_id = (partner.misa_account_object_id or '').strip()
            ref_key = self._misa_vendor_match_code(partner.ref)
            tax_key = self._misa_vendor_match_tax(partner.vat)
            if misa_id:
                partners_by_misa_id.setdefault(misa_id.lower(), partner)
            if ref_key:
                partners_by_ref.setdefault(ref_key, partner)
            if tax_key:
                existing_tax_partner = partners_by_tax.get(tax_key)
                if existing_tax_partner and existing_tax_partner.id != partner.id:
                    ambiguous_tax_keys.add(tax_key)
                elif tax_key not in ambiguous_tax_keys:
                    partners_by_tax[tax_key] = partner
            if tax_key and ref_key:
                partners_by_tax_ref.setdefault((tax_key, ref_key), partner)
        for tax_key in ambiguous_tax_keys:
            partners_by_tax.pop(tax_key, None)

        batch_take = int(take or 0)
        if batch_take > 0:
            if batch_take > 100:
                batch_take = 100
            batch_skip = int(skip or 0)
            account_items = self.get_dictionary(data_type=1, skip=batch_skip, take=batch_take).get('items') or []
        else:
            batch_skip = 0
            account_items = self._get_all_dictionary(1)
        vendor_items = [item for item in account_items if self._misa_truthy(item.get('is_vendor'))]
        updated = 0
        created = 0
        skipped = 0
        for item in vendor_items:
            misa_id = (item.get('account_object_id') or '').strip()
            code = (item.get('account_object_code') or '').strip()
            name = (item.get('account_object_name') or '').strip()
            code_key = self._misa_vendor_match_code(code)
            tax_key = self._misa_vendor_match_tax(item.get('company_tax_code'))
            if not misa_id or not name:
                skipped += 1
                continue
            partner = partners_by_misa_id.get(misa_id.lower())
            match_source = 'misa_id' if partner else ''
            if not partner and tax_key and code_key:
                partner = partners_by_tax_ref.get((tax_key, code_key))
                match_source = 'tax_ref' if partner else ''
            if not partner and tax_key:
                partner = partners_by_tax.get(tax_key)
                match_source = 'tax' if partner else ''
            if not partner and code_key:
                partner = partners_by_ref.get(code_key)
                match_source = 'ref' if partner else ''
            if partner:
                skip_reason = self._misa_vendor_match_skip_reason(partner, code, name, misa_id, tax_key, match_source)
                if skip_reason:
                    skipped += 1
                    self._catalog_log_change(
                        job, 'vendor', 'skip', 'res.partner', partner.id,
                        misa_id, code, name, skip_reason,
                    )
                    continue
            if not partner and self._misa_vendor_is_pm_variant(code, name):
                skipped += 1
                self._catalog_log_change(
                    job, 'vendor', 'skip', 'res.partner', 0,
                    misa_id, code, name,
                    'Bỏ qua mã phụ PM vì không tìm thấy NCC Odoo khớp chính xác',
                )
                continue
            vals = self._misa_vendor_vals(item, partner=partner)
            if partner:
                if unmapped_only and (partner.misa_account_object_id or '').strip():
                    continue
                partner_updated = False
                write_vals = {
                    key: value for key, value in vals.items()
                    if not self._record_value_matches(partner, key, value)
                }
                if write_vals:
                    operation = 'map' if not (partner.misa_account_object_id or '').strip() and 'misa_account_object_id' in write_vals else 'update'
                    change_summary = self._catalog_change_summary(partner, write_vals)
                    partner.write(write_vals)
                    self._catalog_log_change(
                        job, 'vendor', operation, 'res.partner', partner.id,
                        misa_id, code, name, change_summary,
                    )
                    partner_updated = True
                bank_updated = self._sync_misa_vendor_bank_accounts(partner, item, job=job)
                if bank_updated:
                    self._catalog_log_change(
                        job, 'vendor', 'update', 'res.partner', partner.id,
                        misa_id, code, name, 'Đã cập nhật thông tin tài khoản ngân hàng từ MISA',
                    )
                    partner_updated = True
                if partner_updated:
                    updated += 1
                    partners_by_misa_id[misa_id.lower()] = partner
                    if code_key:
                        partners_by_ref[code_key] = partner
                    if tax_key and tax_key not in ambiguous_tax_keys:
                        partners_by_tax[tax_key] = partner
                    if tax_key and code_key:
                        partners_by_tax_ref[(tax_key, code_key)] = partner
                continue
            skipped += 1
        next_skip = batch_skip + len(account_items)
        has_more = bool(batch_take > 0 and len(account_items) >= batch_take)
        if job and batch_take > 0:
            job.sudo().write({'vendor_skip': next_skip})
        return {
            'total': len(vendor_items),
            'updated': updated,
            'created': created,
            'skipped': skipped,
            'error': 0,
            'skip': batch_skip,
            'next_skip': next_skip,
            'has_more': has_more,
        }

    def _misa_text_key(self, value):
        text = unicodedata.normalize('NFKD', str(value or ''))
        text = ''.join(char for char in text if not unicodedata.combining(char))
        return ' '.join(text.replace('_', ' ').replace('-', ' ').split()).upper()

    def _misa_truthy(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'y', 'co', 'có'}
        return bool(value)

    def _misa_vendor_is_pm_variant(self, code, name):
        code_key = (code or '').strip().upper()
        name_key = (name or '').strip().upper()
        return (
            code_key.endswith('_PM')
            or code_key.endswith('-PM')
            or code_key.endswith(' - PM')
            or name_key.endswith('_PM')
            or name_key.endswith(' - PM')
        )

    def _misa_vendor_pm_base_code(self, code):
        code_key = (code or '').strip().upper()
        for suffix in ('_PM', '-PM', ' - PM'):
            if code_key.endswith(suffix):
                return code_key[:-len(suffix)].strip()
        return ''

    def _misa_vendor_base_code(self, code):
        raw = (code or '').strip()
        raw_upper = raw.upper()
        for suffix in ('_PM', '-PM', ' - PM'):
            if raw_upper.endswith(suffix):
                return raw[:-len(suffix)].strip()
        return raw

    def _misa_vendor_same_pm_base(self, left, right):
        left_key = self._misa_vendor_match_code(left)
        right_key = self._misa_vendor_match_code(right)
        if not left_key or not right_key:
            return False
        left_base = self._misa_vendor_pm_base_code(left_key) or left_key
        right_base = self._misa_vendor_pm_base_code(right_key) or right_key
        return left_base == right_base

    def _misa_vendor_tax_name_matches(self, partner, item):
        if not partner:
            return False
        partner_tax = self._misa_vendor_match_tax(partner.vat)
        item_tax = self._misa_vendor_match_tax(item.get('company_tax_code'))
        partner_name = self._misa_text_key(partner.name)
        raw_item_name = (item.get('account_object_name') or '').strip()
        item_names = {
            self._misa_text_key(raw_item_name),
            self._misa_text_key(self._misa_vendor_base_code(raw_item_name)),
        }
        return bool(partner_tax and partner_tax == item_tax and partner_name and partner_name in item_names)

    def _misa_vendor_should_update_ref(self, partner, code):
        incoming_code = (code or '').strip()
        if not incoming_code:
            return False
        if not partner:
            return True
        current_code = (partner.ref or '').strip()
        if not current_code:
            return True
        if self._misa_vendor_match_code(current_code) == self._misa_vendor_match_code(incoming_code):
            return True
        if not self._misa_vendor_same_pm_base(current_code, incoming_code):
            return True

        incoming_is_pm = self._misa_vendor_is_pm_variant(incoming_code, '')
        current_is_pm = self._misa_vendor_is_pm_variant(current_code, '')
        if incoming_is_pm and not current_is_pm:
            return False
        if current_is_pm and not incoming_is_pm:
            return True
        return False

    def _misa_vendor_match_code(self, value):
        return ' '.join(str(value or '').strip().upper().split())

    def _misa_vendor_match_tax(self, value):
        return re.sub(r'[^0-9A-Z]+', '', str(value or '').strip().upper())

    def _misa_partner_is_supplier(self, partner):
        business_role = getattr(partner, 'hlv_business_role', '') or ''
        return int(partner.supplier_rank or 0) > 0 or business_role == 'supplier'

    def _misa_vendor_match_skip_reason(self, partner, code, name, misa_id, tax_key, match_source):
        if not self._misa_partner_is_supplier(partner):
            return 'Bỏ qua vì partner Odoo không phải nhà cung cấp'

        existing_ref = self._misa_vendor_match_code(partner.ref)
        incoming_code_key = self._misa_vendor_match_code(code)
        existing_tax = self._misa_vendor_match_tax(partner.vat)
        tax_matched = bool(existing_tax and tax_key and existing_tax == tax_key)
        incoming_is_pm = self._misa_vendor_is_pm_variant(code, name)
        if incoming_is_pm and match_source != 'misa_id' and not tax_matched:
            return 'Bỏ qua mã phụ PM vì chưa khớp ID MISA hoặc mã số thuế'

        existing_pm_base = self._misa_vendor_pm_base_code(existing_ref)
        restoring_base_from_pm = bool(existing_pm_base and incoming_code_key == existing_pm_base)
        if restoring_base_from_pm:
            return ''

        if match_source == 'misa_id':
            if (
                existing_ref
                and incoming_code_key
                and existing_ref != incoming_code_key
                and not self._misa_vendor_same_pm_base(existing_ref, incoming_code_key)
            ):
                return 'Bỏ qua vì ID MISA khớp nhưng mã NCC trên Odoo và MISA khác nhau'
            if existing_tax and tax_key and existing_tax != tax_key:
                return 'Bỏ qua vì ID MISA khớp nhưng mã số thuế trên Odoo và MISA khác nhau'
            return ''

        if match_source == 'tax_ref':
            return ''

        if match_source == 'tax':
            return ''

        if match_source == 'ref':
            if not incoming_code_key or existing_ref != incoming_code_key:
                return 'Bỏ qua vì mã NCC trên Odoo và MISA không khớp'
            if existing_tax and tax_key and existing_tax != tax_key:
                return 'Bỏ qua vì mã NCC khớp nhưng mã số thuế khác nhau'
            return ''

        existing_misa_id = (partner.misa_account_object_id or '').strip()
        if existing_misa_id and existing_misa_id.lower() != (misa_id or '').strip().lower():
            return 'Bỏ qua vì NCC Odoo đã có ID MISA khác'
        return 'Bỏ qua vì không có khóa khớp đủ tin cậy (ID MISA, mã NCC hoặc mã số thuế + mã NCC)'

    def _misa_resolve_country(self, value):
        raw = (value or '').strip()
        if not raw:
            return self.env['res.country']
        Country = self.env['res.country'].sudo()
        key = self._misa_text_key(raw)
        if key in {'VI', 'VN', 'VNM', 'VIET NAM', 'VIETNAM'}:
            return Country.search([('code', '=', 'VN')], limit=1)
        if raw.isascii() and len(raw) in (2, 3):
            return Country.search([('code', '=', raw.upper())], limit=1)
        return Country.search([('name', '=ilike', raw)], limit=1)

    def _misa_vendor_vals(self, item, partner=None):
        Partner = self.env['res.partner']
        code = (item.get('account_object_code') or '').strip()
        base_code = self._misa_vendor_base_code(code)
        raw_name = (item.get('account_object_name') or '').strip()
        name = self._misa_vendor_base_code(raw_name) if self._misa_vendor_is_pm_variant(code, raw_name) else raw_name
        vals = {
            'name': name,
            'misa_account_object_id': (item.get('account_object_id') or '').strip(),
            'is_company': True,
            'supplier_rank': 1,
        }
        if code and self._misa_vendor_should_update_ref(partner, code):
            vals['ref'] = code
        if (
            base_code
            and 'company_registry' in Partner._fields
            and (not partner or self._misa_vendor_tax_name_matches(partner, item))
        ):
            vals['company_registry'] = base_code
        field_map = {
            'vat': item.get('company_tax_code'),
            'phone': item.get('tel') or item.get('phone'),
            'mobile': item.get('mobile'),
            'email': item.get('email_address') or item.get('email'),
            'street': item.get('account_object_address') or item.get('address'),
            'city': item.get('province_or_city'),
            'website': item.get('website'),
        }
        for field_name, value in field_map.items():
            if field_name in Partner._fields:
                cleaned_value = (value or '').strip()
                if cleaned_value:
                    vals[field_name] = cleaned_value
        street2 = ', '.join(filter(None, [
            (item.get('ward_or_commune') or '').strip(),
            (item.get('district') or '').strip(),
        ]))
        if street2 and 'street2' in Partner._fields:
            vals['street2'] = street2
        country_name = (item.get('country') or '').strip()
        if country_name and 'country_id' in Partner._fields:
            country = self._misa_resolve_country(country_name)
            if country:
                vals['country_id'] = country.id
        if 'active' in Partner._fields:
            vals['active'] = not self._misa_truthy(item.get('inactive'))
        return vals

    def _sync_misa_vendor_bank_accounts(self, partner, item, job=None):
        PartnerBank = self.env['res.partner.bank'].sudo().with_context(active_test=False)
        changed = 0
        for bank_item in self._misa_vendor_bank_items(item):
            acc_number = (
                bank_item.get('bank_account_number')
                or bank_item.get('account_number')
                or bank_item.get('bank_account')
                or bank_item.get('acc_number')
                or ''
            )
            acc_number = str(acc_number).strip()
            if not acc_number:
                continue

            bank_name = str(bank_item.get('bank_name') or '').strip()
            bank_code = str(bank_item.get('bank_code') or bank_item.get('bank_id') or '').strip()
            branch_name = str(bank_item.get('bank_branch_name') or bank_item.get('branch_name') or '').strip()
            bank_city = str(
                bank_item.get('bank_province_or_city')
                or bank_item.get('province_or_city')
                or bank_item.get('provin_or_city')
                or ''
            ).strip()
            holder_name = str(
                bank_item.get('account_holder')
                or bank_item.get('account_holder_name')
                or item.get('account_object_name')
                or partner.name
                or ''
            ).strip()

            bank = self._misa_get_or_create_bank(bank_name, bank_code, branch_name, bank_city)
            vals = {
                'partner_id': partner.id,
                'acc_number': acc_number,
            }
            if bank:
                vals['bank_id'] = bank.id
            if 'acc_holder_name' in PartnerBank._fields and holder_name:
                vals['acc_holder_name'] = holder_name

            partner_bank = PartnerBank.search([
                ('partner_id', '=', partner.id),
                ('acc_number', '=', acc_number),
            ], limit=1)
            if partner_bank:
                write_vals = {
                    key: value for key, value in vals.items()
                    if key in PartnerBank._fields and not self._record_value_matches(partner_bank, key, value)
                }
                if write_vals:
                    partner_bank.write(write_vals)
                    changed += 1
                continue

            create_vals = {
                key: value for key, value in vals.items()
                if key in PartnerBank._fields
            }
            PartnerBank.create(create_vals)
            changed += 1

        return changed

    def _misa_vendor_bank_items(self, item):
        bank_items = []
        raw = item.get('account_object_bank_account')
        if raw:
            parsed = raw
            if isinstance(raw, str):
                raw_text = raw.strip()
                try:
                    parsed = json.loads(raw_text) if raw_text else []
                except Exception:
                    parsed = []
            if isinstance(parsed, dict):
                parsed = (
                    parsed.get('data')
                    or parsed.get('Data')
                    or parsed.get('items')
                    or parsed.get('Items')
                    or [parsed]
                )
            if isinstance(parsed, list):
                bank_items.extend([bank for bank in parsed if isinstance(bank, dict)])

        single_bank = {
            'bank_account_number': item.get('bank_account') or item.get('bank_account_number'),
            'bank_name': item.get('bank_name'),
            'bank_branch_name': item.get('bank_branch_name'),
            'bank_province_or_city': item.get('bank_province_or_city'),
            'account_holder': item.get('account_object_name'),
        }
        if any((value or '').strip() if isinstance(value, str) else value for value in single_bank.values()):
            bank_items.append(single_bank)

        seen = set()
        result = []
        for bank_item in bank_items:
            acc_number = str(
                bank_item.get('bank_account_number')
                or bank_item.get('account_number')
                or bank_item.get('bank_account')
                or bank_item.get('acc_number')
                or ''
            ).strip()
            if not acc_number or acc_number in seen:
                continue
            seen.add(acc_number)
            result.append(bank_item)
        return result

    def _misa_get_or_create_bank(self, bank_name, bank_code='', branch_name='', bank_city=''):
        Bank = self.env['res.bank'].sudo()
        bank = Bank
        if bank_code and 'bic' in Bank._fields:
            bank = Bank.search([('bic', '=', bank_code)], limit=1)
        if not bank and bank_name:
            bank = Bank.search([('name', '=', bank_name)], limit=1)
        if bank or not bank_name:
            return bank

        vals = {'name': bank_name}
        if bank_code and 'bic' in Bank._fields:
            vals['bic'] = bank_code
        if branch_name and 'street' in Bank._fields:
            vals['street'] = branch_name
        if bank_city and 'city' in Bank._fields:
            vals['city'] = bank_city
        return Bank.create(vals)

    def _record_value_matches(self, record, field_name, value):
        field = record._fields.get(field_name)
        current = record[field_name]
        if field and field.type == 'many2one':
            return (current.id or False) == (value or False)
        return current == value

    def _catalog_change_summary(self, record, vals):
        parts = []
        for field_name, new_value in vals.items():
            old_value = record[field_name]
            field = record._fields.get(field_name)
            if field and field.type == 'many2one':
                old_display = old_value.display_name if old_value else ''
                new_record = self.env[field.comodel_name].browse(new_value) if new_value else self.env[field.comodel_name]
                new_display = new_record.display_name if new_record else ''
            else:
                old_display = old_value
                new_display = new_value
            parts.append('%s: %s -> %s' % (field_name, old_display or '', new_display or ''))
        return '; '.join(parts)

    def _catalog_log_change(
        self, job, data_type, operation, odoo_model, res_id, misa_id, code, name, change_summary,
        issue_type=False,
    ):
        if not job:
            return
        job.sudo().add_change_line(
            data_type=data_type,
            operation=operation,
            odoo_model=odoo_model,
            res_id=res_id,
            misa_id=misa_id,
            code=code,
            name=name,
            change_summary=change_summary,
            issue_type=issue_type,
        )

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
