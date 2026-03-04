from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class GoogleAdsRule(models.Model):
    _name = 'google.ads.rule'
    _description = 'Quy Tắc Tự Động Hóa Google Ads'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Tên Quy Tắc', required=True)
    active = fields.Boolean(string='Kích Hoạt', default=True)

    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Áp Dụng', required=True,
    )

    # ── Auto-generation link ─────────────────────
    auto_generated = fields.Boolean(
        string='Tự Sinh', default=False,
        help='Rule này được hệ thống tự tạo từ Strategy.',
    )
    strategy_id = fields.Many2one(
        'google.ads.strategy', string='Chiến Lược Gốc',
        ondelete='cascade',
    )
    product_feed_line_id = fields.Many2one(
        'google.ads.product.feed.line', string='Sản Phẩm Liên Kết',
        ondelete='set null',
    )

    target_type = fields.Selection([
        ('campaign', 'Chiến Dịch'),
        ('ad_group', 'Nhóm Quảng Cáo'),
        ('ad', 'Quảng Cáo')
    ], string='Đối Tượng Áp Dụng', required=True, default='campaign')

    # ── Condition ────────────────────────────────
    condition_field = fields.Selection([
        ('cost', 'Chi Phí'),
        ('clicks', 'Lượt Nhấp'),
        ('impressions', 'Lượt Hiển Thị'),
        ('conversions', 'Lượt Chuyển Đổi'),
        ('cpa', 'CPA (Chi Phí / Chuyển Đổi)'),
        # ── NEW: Product-aware conditions ────────
        ('stock_qty', 'Tồn Kho Thực Tế'),
        ('margin_percent', 'Biên Lợi Nhuận (%)'),
        ('days_of_stock', 'Số Ngày Tồn'),
        ('avg_daily_sales', 'TB Bán/Ngày'),
        ('is_new_product', 'Là Sản Phẩm Mới'),
    ], string='Trường Điều Kiện', required=True)

    condition_operator = fields.Selection([
        ('>', 'Lớn hơn'),
        ('<', 'Nhỏ hơn'),
        ('=', 'Bằng'),
        ('>=', 'Lớn hơn hoặc bằng'),
        ('<=', 'Nhỏ hơn hoặc bằng'),
    ], string='Toán Tử', required=True, default='>')

    condition_value = fields.Float(string='Giá Trị', required=True)

    # ── Action ───────────────────────────────────
    action_type = fields.Selection([
        ('pause', 'Tạm Dừng (Pause)'),
        ('enable', 'Bật Lại (Enable)'),
        ('increase_budget', 'Tăng Budget (%)'),
        ('decrease_budget', 'Giảm Budget (%)'),
        ('notify', 'Chỉ Thông Báo'),
    ], string='Hành Động', required=True, default='notify')

    action_value = fields.Float(
        string='Giá Trị Hành Động',
        help='VD: 30 = tăng/giảm 30% budget',
    )

    log_ids = fields.One2many(
        'google.ads.rule.log', 'rule_id', string='Lịch Sử Chạy',
    )

    # ─────────────────────────────────────────────
    # Core: Run Rule
    # ─────────────────────────────────────────────
    def run_rule(self):
        """Hàm thực thi logic kiểm tra và áp dụng quy tắc"""
        for rule in self:
            if not rule.active:
                continue

            _logger.info("Executing rule: %s", rule.name)

            # 1. Xác định tập đối tượng Google Ads cần kiểm tra
            target_records = rule._get_target_records()

            applicable_records = []
            for rec in target_records:
                val = rule._evaluate_condition_value(rec)
                if rule._check_condition(val):
                    applicable_records.append((rec, val))

            # 2. Ghi log & thực thi
            if not applicable_records:
                self.env['google.ads.rule.log'].create({
                    'rule_id': rule.id,
                    'status': 'success',
                    'message': _('Chạy thành công — không có đối tượng nào thoả mãn.'),
                })
                continue

            for rec, val in applicable_records:
                log_message = _(
                    "Đối tượng '%s' thoả mãn: %s %s %s (Thực tế: %s). Hành động: %s"
                ) % (
                    rec.name,
                    rule.condition_field,
                    rule.condition_operator,
                    rule.condition_value,
                    round(val, 2),
                    rule.action_type,
                )
                self.env['google.ads.rule.log'].create({
                    'rule_id': rule.id,
                    'target_name': rec.name,
                    'status': 'action_taken',
                    'message': log_message,
                })

                # Thực thi hành động
                rule._execute_action(rec)

    def _get_target_records(self):
        """Lấy tập đối tượng Google Ads cần đánh giá"""
        self.ensure_one()

        # Nếu rule liên kết với Product Feed Line → chỉ lấy campaigns của line đó
        if self.product_feed_line_id and self.product_feed_line_id.campaign_ids:
            if self.target_type == 'campaign':
                return self.product_feed_line_id.campaign_ids.filtered(
                    lambda c: c.status == 'enabled'
                )

        # Fallback: lấy tất cả đối tượng của account
        domain = []
        if self.target_type == 'campaign':
            model = self.env['google.ads.campaign']
            domain = [('account_id', '=', self.account_id.id), ('status', '=', 'enabled')]
        elif self.target_type == 'ad_group':
            model = self.env['google.ads.ad.group']
            domain = [('campaign_id.account_id', '=', self.account_id.id), ('status', '=', 'enabled')]
        elif self.target_type == 'ad':
            model = self.env['google.ads.ad']
            domain = [('ad_group_id.campaign_id.account_id', '=', self.account_id.id), ('status', '=', 'enabled')]
        else:
            return self.env['google.ads.campaign']

        return model.search(domain)

    def _evaluate_condition_value(self, rec):
        """Tính giá trị thực tế của điều kiện cho 1 record"""
        self.ensure_one()
        field = self.condition_field

        # Product-aware fields — lấy từ Feed Line
        if field in ('stock_qty', 'margin_percent', 'days_of_stock', 'avg_daily_sales', 'is_new_product'):
            feed_line = self.product_feed_line_id
            if not feed_line:
                return 0

            if field == 'stock_qty':
                return feed_line.qty_available
            elif field == 'margin_percent':
                return feed_line.margin_percent
            elif field == 'days_of_stock':
                return feed_line.days_of_stock
            elif field == 'avg_daily_sales':
                return feed_line.avg_daily_sales
            elif field == 'is_new_product':
                # SP mới = tạo trong vòng N ngày
                days = 30
                if self.strategy_id:
                    days = self.strategy_id.new_product_days or 30
                from datetime import timedelta
                cutoff = fields.Date.today() - timedelta(days=days)
                return 1 if feed_line.product_id.create_date.date() >= cutoff else 0

        # Google Ads metrics
        if field == 'cpa':
            if rec.conversions > 0:
                return rec.cost / rec.conversions
            return rec.cost  # Tốn tiền mà không có conversion → CPA = cost

        # Direct field (cost, clicks, impressions, conversions)
        return getattr(rec, field, 0) or 0

    def _check_condition(self, val):
        """So sánh val với condition"""
        self.ensure_one()
        op = self.condition_operator
        threshold = self.condition_value
        if op == '>':
            return val > threshold
        elif op == '<':
            return val < threshold
        elif op == '=':
            return abs(val - threshold) < 0.001
        elif op == '>=':
            return val >= threshold
        elif op == '<=':
            return val <= threshold
        return False

    def _execute_action(self, rec):
        """Thực thi hành động lên đối tượng Google Ads"""
        self.ensure_one()
        is_live = self.strategy_id.is_live if self.strategy_id else False

        if self.action_type == 'pause':
            rec.status = 'paused'
            if is_live:
                self._mutate_google_status(rec, 'PAUSED')

        elif self.action_type == 'enable':
            rec.status = 'enabled'
            if is_live:
                self._mutate_google_status(rec, 'ENABLED')

        elif self.action_type == 'increase_budget':
            _logger.info("[DRY-RUN] Tăng budget %s%% cho %s", self.action_value, rec.name)
            # Sẽ implement khi có Mutate Budget API

        elif self.action_type == 'decrease_budget':
            _logger.info("[DRY-RUN] Giảm budget %s%% cho %s", self.action_value, rec.name)

        elif self.action_type == 'notify':
            # Chỉ ghi log, đã ghi ở trên
            pass

    def _mutate_google_status(self, rec, new_status):
        """Gọi Google Ads Mutate API để thay đổi trạng thái thật"""
        from ..services.google_ads_mutate import GoogleAdsMutateService

        if self.target_type != 'campaign':
            _logger.warning("Mutate chỉ hỗ trợ campaign. Bỏ qua %s", rec.name)
            return

        google_id = rec.google_campaign_id
        if not google_id:
            return

        client = self.account_id._get_google_ads_client()
        customer_id = self.account_id.operating_customer_id

        if new_status == 'PAUSED':
            ok, detail = GoogleAdsMutateService.pause_campaign(client, customer_id, google_id)
        else:
            ok, detail = GoogleAdsMutateService.enable_campaign(client, customer_id, google_id)

        if not ok:
            self.env['google.ads.rule.log'].create({
                'rule_id': self.id,
                'target_name': rec.name,
                'status': 'error',
                'message': _("Mutate API failed: %s") % detail,
            })

    # ─────────────────────────────────────────────
    # Cron
    # ─────────────────────────────────────────────
    @api.model
    def cron_evaluate_all_rules(self):
        """Hàm cron chạy tự động cho tất cả các rule (Schedule Action)"""
        # 1. Sync metrics mới nhất từ Google
        accounts = self.env['google.ads.account'].search([
            ('state', '=', 'connected'), ('active', '=', True),
        ])
        for acc in accounts:
            try:
                acc.action_sync_all_data()
            except Exception as e:
                _logger.error("Cron sync account %s failed: %s", acc.name, str(e))

        # 2. Cập nhật tồn kho cho tất cả feed lines
        feeds = self.env['google.ads.product.feed'].search([('active', '=', True)])
        for feed in feeds:
            try:
                feed.action_refresh_stock()
            except Exception as e:
                _logger.error("Cron refresh stock feed %s failed: %s", feed.name, str(e))

        # 3. Chạy tất cả rules active
        rules = self.search([('active', '=', True)])
        rules.run_rule()
