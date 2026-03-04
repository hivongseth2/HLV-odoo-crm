from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class GoogleAdsStrategy(models.Model):
    _name = 'google.ads.strategy'
    _description = 'Chiến Lược Quảng Cáo Tự Động'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Tên Chiến Lược', required=True, tracking=True)
    active = fields.Boolean(default=True, string='Kích Hoạt')
    sequence = fields.Integer(default=10)

    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Google Ads',
        required=True, ondelete='restrict', tracking=True,
    )
    feed_id = fields.Many2one(
        'google.ads.product.feed', string='Product Feed',
        required=True, ondelete='restrict', tracking=True,
    )

    strategy_type = fields.Selection([
        ('protect_low',   'Bảo Vệ Hàng Sắp Hết'),
        ('push_stock',    'Đẩy Hàng Tồn Kho Cao'),
        ('optimize_profit', 'Tối Ưu Lợi Nhuận'),
        ('push_new',      'Đẩy Hàng Mới Nhập'),
        ('auto_balance',  'Cân Bằng Tự Động'),
    ], string='Loại Chiến Lược', required=True, default='auto_balance',
        tracking=True,
    )

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('active', 'Đang Chạy'),
        ('paused', 'Tạm Dừng'),
    ], string='Trạng Thái', default='draft', tracking=True)

    # ────────────────────────────────────────────
    # Threshold Configuration
    # ────────────────────────────────────────────
    stock_low_threshold = fields.Float(
        string='Ngưỡng Tồn Thấp',
        default=20, help='Số lượng tồn kho dưới mức này → coi là "sắp hết hàng"',
    )
    stock_high_threshold = fields.Float(
        string='Ngưỡng Tồn Cao',
        default=200, help='Số lượng tồn kho trên mức này → coi là "tồn đọng"',
    )
    days_stock_critical = fields.Integer(
        string='Ngày Tồn Nguy Hiểm',
        default=7, help='Dưới X ngày tồn kho → hành động khẩn cấp',
    )
    min_margin_percent = fields.Float(
        string='Biên LN Tối Thiểu (%)',
        default=15.0, help='Chỉ chạy QC khi margin sản phẩm ≥ giá trị này',
    )
    max_cpa = fields.Float(
        string='CPA Tối Đa (VNĐ)',
        default=100000, help='Chi phí trên mỗi chuyển đổi tối đa chấp nhận được',
    )
    target_roas = fields.Float(
        string='ROAS Mục Tiêu',
        default=3.0, help='Return On Ad Spend mục tiêu. VD: 3.0 = thu 3đ cho 1đ chi',
    )
    budget_increase_percent = fields.Float(
        string='% Tăng Budget',
        default=30, help='% tăng budget cho campaign cần đẩy mạnh',
    )
    budget_decrease_percent = fields.Float(
        string='% Giảm Budget',
        default=30, help='% giảm budget cho campaign cần thu hẹp',
    )
    new_product_days = fields.Integer(
        string='SP Mới Trong (ngày)',
        default=30, help='Sản phẩm tạo trong vòng N ngày gần nhất = hàng mới',
    )

    # ────────────────────────────────────────────
    # Dry-run / Live mode
    # ────────────────────────────────────────────
    is_live = fields.Boolean(
        string='Chế độ Live',
        default=False,
        help='Tắt = Dry-run (chỉ ghi log, không gửi lệnh lên Google). '
             'Bật = Gửi lệnh thực sự lên Google Ads.',
        tracking=True,
    )

    # ────────────────────────────────────────────
    # Linked auto-generated rules
    # ────────────────────────────────────────────
    rule_ids = fields.One2many(
        'google.ads.rule', 'strategy_id', string='Rules Tự Sinh',
    )
    rule_count = fields.Integer(
        string='Số Rules', compute='_compute_rule_count',
    )

    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for rec in self:
            rec.rule_count = len(rec.rule_ids)

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def action_activate(self):
        for rec in self:
            if not rec.rule_ids:
                rec.action_generate_rules()
            rec.state = 'active'

    def action_pause(self):
        for rec in self:
            rec.state = 'paused'
            rec.rule_ids.write({'active': False})

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    # ─────────────────────────────────────────────
    # Rule Generation Logic
    # ─────────────────────────────────────────────
    def action_generate_rules(self):
        """Sinh rules tự động dựa trên strategy_type + product feed"""
        for strategy in self:
            # Xoá rules cũ do hệ thống tạo
            strategy.rule_ids.filtered(lambda r: r.auto_generated).unlink()

            lines = strategy.feed_id.line_ids
            if not lines:
                raise UserError(_("Feed '%s' chưa có sản phẩm nào. "
                                  "Hãy thêm sản phẩm trước.") % strategy.feed_id.name)

            method_name = f'_generate_rules_{strategy.strategy_type}'
            method = getattr(strategy, method_name, None)
            if method:
                method(lines)
            else:
                raise UserError(_("Chưa hỗ trợ chiến lược: %s") % strategy.strategy_type)

            strategy.message_post(
                body=_("Đã sinh %s rules tự động cho chiến lược '%s'.")
                     % (len(strategy.rule_ids.filtered('auto_generated')), strategy.name)
            )

    # ── protect_low ──────────────────────────────
    def _generate_rules_protect_low(self, lines):
        """Sắp hết hàng → Pause campaign tương ứng"""
        self.ensure_one()
        Rule = self.env['google.ads.rule']

        for line in lines.filtered(lambda l: l.campaign_ids):
            Rule.create({
                'name': _("[Auto] Pause khi hết hàng — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'stock_qty',
                'condition_operator': '<',
                'condition_value': self.stock_low_threshold,
                'action_type': 'pause',
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })

    # ── push_stock ───────────────────────────────
    def _generate_rules_push_stock(self, lines):
        """Tồn kho cao → Enable + tăng budget"""
        self.ensure_one()
        Rule = self.env['google.ads.rule']

        for line in lines.filtered(lambda l: l.campaign_ids):
            # Rule 1: enable nếu đang pause mà tồn kho cao
            Rule.create({
                'name': _("[Auto] Enable đẩy hàng tồn — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'stock_qty',
                'condition_operator': '>',
                'condition_value': self.stock_high_threshold,
                'action_type': 'enable',
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })
            # Rule 2: cũng tăng budget
            Rule.create({
                'name': _("[Auto] Tăng budget đẩy tồn — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'stock_qty',
                'condition_operator': '>',
                'condition_value': self.stock_high_threshold,
                'action_type': 'increase_budget',
                'action_value': self.budget_increase_percent,
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })

    # ── optimize_profit ──────────────────────────
    def _generate_rules_optimize_profit(self, lines):
        """CPA quá cao hoặc Margin quá thấp → Pause"""
        self.ensure_one()
        Rule = self.env['google.ads.rule']

        for line in lines.filtered(lambda l: l.campaign_ids):
            # Rule 1: CPA vượt max → Pause
            Rule.create({
                'name': _("[Auto] Pause CPA cao — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'cpa',
                'condition_operator': '>',
                'condition_value': self.max_cpa,
                'action_type': 'pause',
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })
            # Rule 2: Margin thấp → Pause
            Rule.create({
                'name': _("[Auto] Pause margin thấp — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'margin_percent',
                'condition_operator': '<',
                'condition_value': self.min_margin_percent,
                'action_type': 'pause',
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })

    # ── push_new ─────────────────────────────────
    def _generate_rules_push_new(self, lines):
        """Sản phẩm mới + tồn kho đủ → Enable"""
        self.ensure_one()
        Rule = self.env['google.ads.rule']

        for line in lines.filtered(lambda l: l.campaign_ids):
            Rule.create({
                'name': _("[Auto] Enable hàng mới — %s") % line.product_id.name,
                'auto_generated': True,
                'strategy_id': self.id,
                'account_id': self.account_id.id,
                'target_type': 'campaign',
                'condition_field': 'is_new_product',
                'condition_operator': '=',
                'condition_value': 1,
                'action_type': 'enable',
                'product_feed_line_id': line.id,
                'active': self.state == 'active',
            })

    # ── auto_balance ─────────────────────────────
    def _generate_rules_auto_balance(self, lines):
        """Tổng hợp: protect_low + push_stock + optimize_profit"""
        self.ensure_one()
        self._generate_rules_protect_low(lines)
        self._generate_rules_push_stock(lines)
        self._generate_rules_optimize_profit(lines)

    # ─────────────────────────────────────────────
    # View helpers
    # ─────────────────────────────────────────────
    def action_view_rules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rules Tự Sinh'),
            'res_model': 'google.ads.rule',
            'view_mode': 'list,form',
            'domain': [('strategy_id', '=', self.id)],
            'context': {'default_strategy_id': self.id},
        }
