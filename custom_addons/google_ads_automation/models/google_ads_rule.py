from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging
from datetime import timedelta

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

    hero_header_html = fields.Html(compute='_compute_hero_header_html')

    def _compute_hero_header_html(self):
        for rec in self:
            status_ping = 'bg-success' if rec.active else 'bg-danger'
            status_text = _('ACTIVE') if rec.active else _('INACTIVE')
            
            html = f"""
                <div class="o_hero_header">
                    <div class="status_badge text-end">
                        <span class="o_status_ping {status_ping}"></span>
                        <span class="badge text-bg-light fw-bold shadow-sm border">{status_text}</span>
                    </div>
                    <div class="row align-items-center">
                        <div class="col-auto">
                            <div class="bg-light p-3 rounded-4 border text-primary">
                                <i class="fa fa-terminal fa-4x"></i>
                            </div>
                        </div>
                        <div class="col">
                            <span class="o_logic_tag mb-2 d-inline-block bg-primary">AUTOMATION RULE</span>
                            
                            <p class="text-muted mt-2 mb-0 fw-medium">
                                <i class="fa fa-bullseye me-1"></i> Target: 
                                <span class="text-dark fw-bold">{rec.target_type}</span>
                                <span class="ms-3 pe-2"><i class="fa fa-google me-1"></i> Account: <span class="text-dark">{rec.account_id.name or '—'}</span></span>
                            </p>
                        </div>
                    </div>
                </div>
            """
            rec.hero_header_html = Markup(html)

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
            checked_details = []
            for rec in target_records:
                val = rule._evaluate_condition_value(rec)
                if rule._check_condition(val):
                    applicable_records.append((rec, val))
                else:
                    checked_details.append(f"- {rec.name}: Thực tế {round(val, 2)} (Yêu cầu: {rule.condition_operator} {rule.condition_value})")

            # 2. Ghi log & thực thi
            if not applicable_records:
                detail_msg = "\n".join(checked_details) if checked_details else "Không có chiến dịch/nhóm QC nào cờ Trạng Thái = 'Đang hoạt động' để đánh giá."
                msg_body = _('Chạy thành công — Không có đối tượng nào thoả mãn điều kiện lúc này.\nBáo cáo:\n%s') % detail_msg
                self.env['google.ads.rule.log'].create({
                    'rule_id': rule.id,
                    'status': 'success',
                    'message': msg_body,
                })
                
                # NẾU USER BẤM BẰNG TAY (UI) THÌ SHOW POPUP
                if len(self) == 1:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Quy Tắc Đã Chạy'),
                            'message': msg_body,
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
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

                rule._execute_action(rec)

        # NẾU CÓ BẤT KỲ RECORD NÀO SATISFIED VÀ BẤM UI THÌ SHOW POPUP
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thành Công'),
                    'message': _('Đã phát hiện và thực thi thao tác cho các chiến dịch thỏa điều kiện!'),
                    'type': 'success',
                    'sticky': False,
                }
            }

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

        # Product-aware fields — lấy từ Feed Line hoặc trực tiếp từ Product trên Campaign/AdGroup
        if field in ('stock_qty', 'margin_percent', 'days_of_stock', 'avg_daily_sales', 'is_new_product'):
            feed_line = self.product_feed_line_id
            
            if feed_line:
                # Trường hợp có Feed Line cụ thể (Rule sinh từ Strategy)
                product = feed_line
                if field == 'stock_qty': return product.qty_available
                elif field == 'margin_percent': return product.margin_percent
                elif field == 'days_of_stock': return product.days_of_stock
                elif field == 'avg_daily_sales': return product.avg_daily_sales
                elif field == 'is_new_product':
                    days = self.strategy_id.new_product_days if self.strategy_id else 30
                    cutoff = fields.Date.today() - timedelta(days=days)
                    create_date = product.product_id.create_date.date()
                    return 1 if create_date >= cutoff else 0

            elif hasattr(rec, 'product_ids') and rec.product_ids:
                # Trường hợp Rule thủ công đánh vào Campaign có nhiều SP
                products = rec.product_ids
                if field == 'stock_qty':
                    # Lấy tổng tồn kho của các SP trong campaign này
                    return sum(p.qty_available for p in products)
                elif field == 'margin_percent':
                    # Lấy trung bình cộng biên lợi nhuận
                    margins = [(p.list_price - p.standard_price) / p.list_price * 100 for p in products if p.list_price > 0]
                    return sum(margins) / len(margins) if margins else 0
                elif field == 'days_of_stock':
                    # Lấy số ngày tồn thấp nhất (nguy hiểm nhất)
                    active_days = [p.qty_available / p.avg_daily_sales for p in products if hasattr(p, 'avg_daily_sales') and p.avg_daily_sales > 0]
                    return min(active_days) if active_days else 9999
                elif field == 'avg_daily_sales':
                    return sum(p.avg_daily_sales for p in products if hasattr(p, 'avg_daily_sales'))
                elif field == 'is_new_product':
                    # Rule thỏa mãn nếu CÓ BẤT KỲ sản phẩm nào là mới
                    days = self.strategy_id.new_product_days if self.strategy_id else 30
                    cutoff = fields.Date.today() - timedelta(days=days)
                    return 1 if any(p.create_date.date() >= cutoff for p in products) else 0
            
            return 0


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

        if self.account_id.is_demo:
            self.env['google.ads.rule.log'].create({
                'rule_id': self.id,
                'target_name': rec.name,
                'status': 'action_taken',
                'message': _("[DEMO] Chế độ Live: Gửi lệnh thay đổi trạng thái Google Ads (giả lập) thành: %s" % new_status),
            })
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
    @api.model
    def _run_rules_for_products(self, product_tmpl_ids):
        """
        Kích hoạt chạy Rule ngay lập tức cho danh sách sản phẩm (Reactive Trigger).
        Được gọi từ stock.move khi có biến động kho.
        """
        if not product_tmpl_ids:
            return
        
        _logger.info("Reactive Trigger: Checking rules for products %s", product_tmpl_ids)
        
        # 1. Tìm các Feed Lines chứa sản phẩm này
        feed_lines = self.env['google.ads.product.feed.line'].search([
            ('product_id', 'in', product_tmpl_ids)
        ])
        if not feed_lines:
            return

        # 2. Cập nhật tồn kho ngay lập tức cho các line này
        for line in feed_lines:
            line._compute_stock_fields()
            line._compute_margin_percent()
            line._compute_avg_daily_sales()

        # 3. Tìm các Rule liên kết trực tiếp với Feed Line này
        rules = self.search([
            ('active', '=', True),
            ('product_feed_line_id', 'in', feed_lines.ids)
        ])
        
        # 4. Tìm thêm các Rule thủ công (không auto-gen) nhưng target vào Campaign có chứa SP này
        # (Chỉ lấy các rule đang active)
        manual_rules = self.search([
            ('active', '=', True),
            ('auto_generated', '=', False),
            ('target_type', '=', 'campaign')
        ])
        for m_rule in manual_rules:
            # Nếu rule này áp dụng cho account của SP và campaign có chứa SP
            campaigns = m_rule._get_target_records()
            for camp in campaigns:
                if any(p.id in product_tmpl_ids for p in camp.product_ids):
                    rules |= m_rule
                    break

        if rules:
            _logger.info("Found %s relevant rules to execute immediately.", len(rules))
            rules.run_rule()
