from odoo import api, fields, models, _
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
        required=True, ondelete='cascade', index=True,
    )
    campaign_id = fields.Many2one(
        'google.ads.campaign', string='Chiến Dịch',
        ondelete='set null', index=True,
    )

    # ── Thông tin đơn hàng ───────────────────────
    order_ref = fields.Char(string='Mã Đơn Hàng', required=True, index=True)
    order_date = fields.Datetime(string='Ngày Đặt Hàng', required=True)
    revenue = fields.Float(string='Doanh Thu (VNĐ)', required=True)
    product_names = fields.Char(string='Sản Phẩm')
    customer_name = fields.Char(string='Khách Hàng')
    order_status = fields.Selection([
        ('pending',    'Chờ Thanh Toán'),
        ('processing', 'Đang Xử Lý'),
        ('completed',  'Hoàn Thành'),
        ('cancelled',  'Đã Hủy'),
        ('refunded',   'Đã Hoàn Tiền'),
    ], string='Trạng Thái Đơn', default='completed')

    # ── Google Ads Attribution ───────────────────
    gclid = fields.Char(
        string='Google Click ID (gclid)',
        help='ID click từ Google Ads, lưu trong meta WooCommerce khi khách click QC rồi mua hàng',
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

    @api.depends('revenue', 'campaign_id.cost')
    def _compute_roas(self):
        for rec in self:
            cost = rec.campaign_id.cost if rec.campaign_id else 0
            rec.roas = rec.revenue / cost if cost > 0 else 0
