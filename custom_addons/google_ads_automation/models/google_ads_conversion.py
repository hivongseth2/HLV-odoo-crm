from odoo import api, fields, models, _
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class GoogleAdsConversion(models.Model):
    _name = 'google.ads.conversion'
    _description = 'Lượt Chuyển Đổi — Đơn Hàng Liên Kết Google Ads'
    _order = 'order_date desc'
    _rec_name = 'order_ref'

    # ── Nguồn dữ liệu ────────────────────────────
    source = fields.Selection([
        ('woocommerce', 'WooCommerce'),
        ('manual',      'Thủ Công'),
        ('demo',        'Demo'),
    ], string='Nguồn', default='woocommerce', required=True)

    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Google Ads',
        required=True, ondelete='cascade', index=True, readonly=True,
    )
    campaign_id = fields.Many2one(
        'google.ads.campaign', string='Chiến Dịch',
        ondelete='set null', index=True, readonly=True,
    )

    # ── Thông tin đơn hàng ───────────────────────
    order_ref = fields.Char(string='Mã Đơn Hàng', required=True, index=True, readonly=True)
    order_date = fields.Datetime(string='Ngày Đặt Hàng', required=True, readonly=True)
    revenue = fields.Float(string='Doanh Thu (VNĐ)', required=True, readonly=True)
    product_names = fields.Char(string='Sản Phẩm', readonly=True)
    customer_name = fields.Char(string='Khách Hàng', readonly=True)
    order_status = fields.Selection([
        ('pending',    'Chờ Thanh Toán'),
        ('processing', 'Đang Xử Lý'),
        ('completed',  'Hoàn Thành'),
        ('cancelled',  'Đã Hủy'),
        ('refunded',   'Đã Hoàn Tiền'),
    ], string='Trạng Thái Đơn', default='completed', readonly=True)

    # ── Google Ads Attribution ───────────────────
    gclid = fields.Char(
        string='Google Click ID (gclid)',
        help='ID click từ Google Ads, lưu trong meta WooCommerce khi khách click QC rồi mua hàng',
        readonly=True,
    )

    # ── Computed ROI ─────────────────────────────
    campaign_cost = fields.Float(
        string='Chi Phí Campaign (VNĐ)',
        related='campaign_id.cost', readonly=True,
    )
    roas = fields.Float(
        string='ROAS', compute='_compute_roas', store=False,
        help='Revenue / Campaign Cost',
    )

    def action_upload_to_google(self):
        """Đẩy lượt chuyển đổi này lên Google Ads API (Bỏ qua GTM)"""
        self.ensure_one()
        if not self.gclid:
            raise UserError(_("Không có GCLID để đồng bộ."))

        # Tìm hành động chuyển đổi phù hợp (VD: 'Purchase' hoặc 'Purchase (Offline)')
        actions = self.env['google.ads.conversion.action'].search([
            ('account_id', '=', self.account_id.id),
            ('active', '=', True)
        ], limit=1)
        
        if not actions:
            raise UserError(_("Vui lòng cấu hình ít nhất một 'Hành động chuyển đổi' (Conversion Action) Google Ads."))

        if self.account_id.is_demo:
            self.message_post(body=_("[DEMO] Đã giả lập upload chuyển đổi lên Google Ads thành công."))
            return True

        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id
        
        # Định dạng ngày giờ chuẩn ISO with Timezone (Google yêu cầu yyyy-mm-dd hh:mm:ss+tz)
        # Odoo lưu UTC, chúng ta giả định +07:00 (Vietnam) để tối ưu
        dt_str = self.order_date.strftime('%Y-%m-%d %H:%M:%S+0700')
        
        conversion_data = {
            'gclid': self.gclid,
            'conversion_action_id': actions.google_conversion_id,
            'conversion_date_time': dt_str,
            'conversion_value': self.revenue,
            'currency_code': 'VND',
        }
        
        from ..services.google_ads_conversion_service import GoogleAdsConversionService
        ok, result = GoogleAdsConversionService.upload_click_conversion(client, customer_id, conversion_data)
        
        if ok:
            self.message_post(body=_("Đã upload chuyển đổi lên Google Ads API thành công tại: %s") % result)
        else:
            raise UserError(_("Lỗi upload: %s") % result)

    @api.depends('revenue', 'campaign_id.cost')
    def _compute_roas(self):
        for rec in self:
            cost = rec.campaign_id.cost if rec.campaign_id else 0
            rec.roas = rec.revenue / cost if cost > 0 else 0

    # ── UI/UX Rendering ──────────────────────────
    status_label = fields.Char(compute='_compute_status_info')
    hero_header_html = fields.Html(compute='_compute_status_info')

    @api.depends('order_status', 'source', 'order_ref')
    def _compute_status_info(self):
        selection = dict(self._fields['order_status'].selection)
        for rec in self:
            rec.status_label = selection.get(rec.order_status, rec.order_status)
            
            # Render Hero Header
            status_color = 'bg-success' if rec.order_status == 'completed' else \
                          'bg-warning' if rec.order_status == 'processing' else \
                          'bg-danger' if rec.order_status == 'cancelled' else 'bg-info'
            
            html = f"""
                <div class="o_hero_header mb-4">
                    <div class="status_badge">
                        <span class="o_status_ping {status_color}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm border">{rec.status_label}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-primary">
                                <i class="fa fa-shopping-cart fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">GOOGLE ADS CONVERSION</span>
                            <div class="d-flex align-items-center mb-1">
                                <h1 class="me-3 mb-0">{rec.order_ref}</h1>
                            </div>
                            <div class="d-flex align-items-center text-muted mt-2 fw-medium">
                                <div>
                                    <i class="fa fa-calendar me-1"></i> Ngày đặt: <span class="text-dark fw-bold">{rec.order_date or '—'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-user me-1"></i> Khách hàng: <span class="text-dark">{rec.customer_name or 'Khách vãng lai'}</span>
                                </div>
                                <div class="ms-4">
                                    <i class="fa fa-globe me-1"></i> Nguồn: <span class="text-dark">{rec.source.upper()}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)
