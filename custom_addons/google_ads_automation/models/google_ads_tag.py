from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class GoogleAdsTag(models.Model):
    _name = 'google.ads.tag'
    _description = 'Cấu Hình Google Tag / GTM'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Tên Cấu Hình', required=True)
    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Google Ads',
        required=True, ondelete='cascade',
    )
    active = fields.Boolean(default=True)

    # ── Tag Type ──────────────────────────────────
    tag_type = fields.Selection([
        ('gtag',    'Google Tag (gtag.js) — Trực tiếp'),
        ('gtm',     'Google Tag Manager (GTM)'),
    ], string='Loại Tag', required=True, default='gtm',
        help='GTM dễ quản lý hơn, khuyến nghị dùng GTM')

    # ── Google Tag (gtag) ─────────────────────────
    measurement_id = fields.Char(
        string='Measurement ID / AW ID',
        help='Dạng G-XXXXXXXX (GA4) hoặc AW-XXXXXXXXX (Google Ads)',
    )

    # ── Google Tag Manager ────────────────────────
    gtm_container_id = fields.Char(
        string='GTM Container ID',
        help='Dạng GTM-XXXXXXX',
    )

    # ── Conversion Actions ───────────────────────
    conversion_action_ids = fields.One2many(
        'google.ads.conversion.action',
        'tag_id', string='Conversion Actions',
    )

    # ── Generated snippets (computed) ────────────
    snippet_head = fields.Text(
        string='Code Dán Vào <head>',
        compute='_compute_snippets', store=False,
    )
    snippet_body = fields.Text(
        string='Code Dán Sau <body>',
        compute='_compute_snippets', store=False,
    )
    snippet_purchase = fields.Text(
        string='Code Theo Dõi Đơn Hàng (WooCommerce)',
        compute='_compute_snippets', store=False,
    )

    @api.depends('tag_type', 'measurement_id', 'gtm_container_id', 'conversion_action_ids')
    def _compute_snippets(self):
        for tag in self:
            if tag.tag_type == 'gtm':
                tag.snippet_head, tag.snippet_body = tag._make_gtm_snippets()
                tag.snippet_purchase = tag._make_gtm_purchase_snippet()
            else:
                tag.snippet_head = tag._make_gtag_snippet()
                tag.snippet_body = ''
                tag.snippet_purchase = tag._make_gtag_purchase_snippet()

    def _make_gtm_snippets(self):
        container = self.gtm_container_id or 'GTM-XXXXXXX'
        head = f"""<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{container}');</script>
<!-- End Google Tag Manager -->"""

        body = f"""<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={container}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""
        return head, body

    def _make_gtm_purchase_snippet(self):
        """Snippet PHP cho WooCommerce thankyou page (dán vào functions.php)"""
        actions = self.conversion_action_ids.filtered(
            lambda a: a.action_type == 'purchase'
        )
        if not actions:
            return '/* Chưa có Conversion Action loại Mua Hàng */'

        action = actions[0]
        return f"""<?php
// Dán vào functions.php của theme WordPress
// Theo dõi đơn hàng WooCommerce → Google Tag Manager DataLayer
add_action('woocommerce_thankyou', 'hlv_gtm_purchase_event', 10, 1);
function hlv_gtm_purchase_event($order_id) {{
    if (!$order_id) return;
    $order = wc_get_order($order_id);
    $items = array();
    foreach ($order->get_items() as $item) {{
        $items[] = array(
            'item_id'   => $item->get_product_id(),
            'item_name' => $item->get_name(),
            'quantity'  => $item->get_quantity(),
            'price'     => $item->get_total(),
        );
    }}
    ?>
    <script>
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({{
        'event': 'purchase',
        'ecommerce': {{
            'transaction_id': '<?php echo $order_id; ?>',
            'value': '<?php echo $order->get_total(); ?>',
            'currency': '<?php echo $order->get_currency(); ?>',
            'items': <?php echo json_encode($items); ?>
        }},
        /* Gclid để link với Google Ads */
        'gclid': '<?php echo $order->get_meta("_ga_gclid", true); ?>'
    }});
    </script>
    <?php
}}
/* Conversion Label: {action.conversion_label} */
/* Conversion ID: {action.conversion_id} */"""

    def _make_gtag_snippet(self):
        mid = self.measurement_id or 'AW-XXXXXXXXX'
        return f"""<!-- Google tag (gtag.js) — Dán vào <head> WordPress -->
<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{mid}');
</script>"""

    def _make_gtag_purchase_snippet(self):
        mid = self.measurement_id or 'AW-XXXXXXXXX'
        actions = self.conversion_action_ids.filtered(
            lambda a: a.action_type == 'purchase'
        )
        label = actions[0].conversion_label if actions else 'CONVERSION_LABEL'
        return f"""<?php
// Dán vào functions.php — Theo dõi đơn hàng với gtag trực tiếp
add_action('woocommerce_thankyou', 'hlv_gtag_purchase_event', 10, 1);
function hlv_gtag_purchase_event($order_id) {{
    $order = wc_get_order($order_id);
    ?>
    <script>
      gtag('event', 'conversion', {{
        'send_to': '{mid}/{label}',
        'value': <?php echo $order->get_total(); ?>,
        'currency': '<?php echo $order->get_currency(); ?>',
        'transaction_id': '<?php echo $order_id; ?>'
      }});
    </script>
    <?php
}}"""


class GoogleAdsConversionAction(models.Model):
    _name = 'google.ads.conversion.action'
    _description = 'Google Ads Conversion Action'
    _rec_name = 'name'

    tag_id = fields.Many2one(
        'google.ads.tag', string='Tag', required=True, ondelete='cascade',
    )
    name = fields.Char(string='Tên Action', required=True)
    action_type = fields.Selection([
        ('purchase', 'Mua Hàng'),
        ('contact',  'Liên Hệ'),
        ('signup',   'Đăng Ký'),
        ('lead',     'Lead Form'),
        ('pageview', 'Xem Trang'),
        ('custom',   'Tùy Chỉnh'),
    ], string='Loại Event', required=True, default='purchase')
    conversion_id = fields.Char(
        string='Conversion ID',
        help='Lấy từ Google Ads > Goals > Conversions (dạng số: 123456789)',
    )
    conversion_label = fields.Char(
        string='Conversion Label',
        help='Lấy từ Google Ads > Goals > Conversions (dạng: AbCdEfGhIjK)',
    )
