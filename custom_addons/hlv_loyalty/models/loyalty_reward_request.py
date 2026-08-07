# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from bs4 import BeautifulSoup
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class HlvLoyaltyRewardRequest(models.Model):
    _name = 'hlv.loyalty.reward.request'
    _description = 'Yêu cầu đổi thưởng Loyalty'
    _order = 'date_request desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(
        string='Mã yêu cầu', readonly=True, copy=False, default='New',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        index=True, ondelete='restrict', tracking=True,
    )
    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản Loyalty',
        index=True, ondelete='restrict', tracking=True,
        help='Tài khoản Loyalty thực hiện yêu cầu đổi thưởng này. Điểm bị trừ '
             'trực tiếp ở tài khoản này, không phải ở công ty.',
    )
    request_type = fields.Selection([
        ('gift', 'Đổi quà (Voucher)'),
        ('cash', 'Đổi tiền mặt'),
    ], string='Loại yêu cầu', required=True, default='gift', tracking=True)

    # ── Gift fields ────────────────────────────────────────────────────────
    package_id = fields.Many2one(
        'hlv.loyalty.voucher.package', string='Gói quà',
        domain=[('active', '=', True)],
    )

    # ── Cash fields ────────────────────────────────────────────────────────
    points_to_redeem = fields.Integer(string='Số điểm muốn đổi', default=0)
    bank_name = fields.Char(string='Ngân hàng', tracking=True)
    account_number = fields.Char(string='Số tài khoản', tracking=True)
    account_name = fields.Char(string='Chủ tài khoản', tracking=True)

    # ── Computed ───────────────────────────────────────────────────────────
    points_required = fields.Integer(
        string='Điểm yêu cầu', compute='_compute_points_required', store=True,
    )
    cash_value = fields.Float(
        string='Giá trị quy đổi (đ)', compute='_compute_cash_value',
        store=True, digits=(15, 0),
    )

    # ── Snapshot ───────────────────────────────────────────────────────────
    balance_at_request = fields.Integer(
        string='Số dư ĐT lúc gửi', readonly=True,
        help='Điểm đổi thưởng của khách tại thời điểm gửi yêu cầu',
    )

    # ── Notes ──────────────────────────────────────────────────────────────
    customer_note = fields.Text(string='Ghi chú của khách')
    admin_note = fields.Text(string='Ghi chú xử lý', tracking=True)

    # ── State ──────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('done', 'Đã xử lý'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='pending', required=True,
        tracking=True, index=True)

    date_request = fields.Datetime(
        string='Ngày yêu cầu', default=fields.Datetime.now, readonly=True,
    )
    date_done = fields.Datetime(string='Ngày xử lý', readonly=True)
    done_by_id = fields.Many2one('res.users', string='Người xử lý', readonly=True)

    # ── Result links ───────────────────────────────────────────────────────
    history_id = fields.Many2one(
        'hlv.loyalty.history', string='Giao dịch điểm', readonly=True,
    )
    voucher_id = fields.Many2one(
        'hlv.loyalty.voucher', string='Voucher phát hành', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty',
        default=lambda self: self.env.company, readonly=True,
    )

    # Related point history (for admin view)
    partner_history_ids = fields.One2many(
        'hlv.loyalty.history', compute='_compute_partner_history_ids',
        string='Lịch sử điểm',
    )

    @api.depends('partner_id')
    def _compute_partner_history_ids(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_history_ids = self.env['hlv.loyalty.history'].sudo().search([
                    ('partner_id', '=', rec.partner_id.id),
                ], order='date desc', limit=30)
            else:
                rec.partner_history_ids = self.env['hlv.loyalty.history']

    # ── Compute ────────────────────────────────────────────────────────────

    @api.depends('request_type', 'package_id', 'points_to_redeem')
    def _compute_points_required(self):
        for rec in self:
            if rec.request_type == 'gift' and rec.package_id:
                rec.points_required = rec.package_id.points_required
            elif rec.request_type == 'cash':
                rec.points_required = rec.points_to_redeem
            else:
                rec.points_required = 0

    @api.depends('request_type', 'points_to_redeem')
    def _compute_cash_value(self):
        program = self.env['hlv.loyalty.program'].sudo().search(
            [('active', '=', True)], limit=1
        )
        rate = program.cash_rate_per_point if program else 0.0
        for rec in self:
            if rec.request_type == 'cash' and rec.points_to_redeem > 0:
                rec.cash_value = rec.points_to_redeem * rate
            else:
                rec.cash_value = 0.0

    # ── ORM ────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('hlv.loyalty.reward.request')
                    or 'New'
                )
        records = super().create(vals_list)
        records._lock_loyalty_root_rows()
        records._validate_pending_reward_points()
        records._invalidate_loyalty_reward_point_cache()
        records.filtered(lambda rec: rec.request_type != 'gift')._send_loyalty_reward_bus_notification('request_created')
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'partner_id', 'account_id', 'request_type', 'package_id', 'points_to_redeem', 'state'} & set(vals):
            self._lock_loyalty_root_rows()
            self._validate_pending_reward_points()
            self._invalidate_loyalty_reward_point_cache()
        return res

    def _invalidate_loyalty_reward_point_cache(self):
        accounts = self.env['hlv.loyalty.portal.account'].browse()
        roots = self.env['res.partner'].browse()
        for rec in self:
            if rec.account_id:
                accounts |= rec.account_id
            if rec.partner_id:
                roots |= rec.partner_id._get_loyalty_root()
        if accounts:
            accounts.invalidate_recordset([
                'loyalty_reward_pending_points',
                'loyalty_exchange_available_points',
            ])
        if roots:
            roots.invalidate_recordset([
                'loyalty_reward_pending_points',
                'loyalty_exchange_available_points',
            ])

    def _lock_loyalty_root_rows(self):
        account_ids = {rec.account_id.id for rec in self if rec.account_id}
        if account_ids:
            self.env.cr.execute(
                'SELECT id FROM hlv_loyalty_portal_account WHERE id = ANY(%s) FOR UPDATE',
                [list(account_ids)],
            )
        root_ids = {
            rec.partner_id._get_loyalty_root().id
            for rec in self
            if rec.partner_id
        }
        if root_ids:
            self.env.cr.execute(
                'SELECT id FROM res_partner WHERE id = ANY(%s) FOR UPDATE',
                [list(root_ids)],
            )

    def _validate_pending_reward_points(self):
        for rec in self.filtered(lambda item: item.state == 'pending' and (item.account_id or item.partner_id)):
            if rec.account_id:
                exchange_points = rec.account_id.loyalty_exchange_points or 0
                pending_points = rec.account_id._get_loyalty_pending_reward_points(exclude_request=rec)
            else:
                # Legacy fallback: chưa gắn tài khoản (dữ liệu cũ trước khi tách theo account).
                root = rec.partner_id._get_loyalty_root()
                exchange_points = root.loyalty_exchange_points or 0
                pending_points = root._get_loyalty_pending_reward_points(exclude_request=rec)
            available_points = max(exchange_points - pending_points, 0)
            required_points = rec.points_required or 0
            if required_points > available_points:
                raise UserError(
                    _(
                        'Không thể tạo yêu cầu đổi thưởng vượt quá điểm còn khả dụng.\n'
                        'Điểm đổi thưởng hiện có: %(exchange)s\n'
                        'Điểm đang treo: %(pending)s\n'
                        'Điểm còn có thể yêu cầu: %(available)s\n'
                        'Yêu cầu này cần: %(required)s\n'
                        'Vui lòng hủy yêu cầu đang treo rồi tạo yêu cầu mới.',
                        exchange=f'{exchange_points:,}',
                        pending=f'{pending_points:,}',
                        available=f'{available_points:,}',
                        required=f'{required_points:,}',
                    )
                )

    def _get_loyalty_notification_users(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        return company.sudo().loyalty_notification_user_ids.filtered(
            lambda user: user.active and user.partner_id
        )

    def _send_loyalty_reward_bus_notification(self, event):
        """Send configured realtime and persistent notifications for reward events."""
        bus = self.env['bus.bus'].sudo()
        for rec in self:
            users = rec._get_loyalty_notification_users()
            if not users:
                continue

            title, message = rec._get_loyalty_reward_notification_content(event)
            rec._post_loyalty_reward_mail_notification(users, title, message)

            payload = {
                'title': title,
                'message': message,
                'type': 'info',
                'sticky': True,
                'action': rec._get_loyalty_reward_open_action(),
            }
            for user in users:
                try:
                    bus._sendone(user.partner_id, 'hlv_loyalty_reward_notification', payload)
                except Exception:
                    _logger.debug(
                        'Failed to send loyalty reward bus notification to user %s',
                        user.id,
                        exc_info=True,
                    )

    def _get_loyalty_reward_notification_content(self, event):
        self.ensure_one()
        if event == 'gift_redeemed':
            package = self.package_id.display_name if self.package_id else _('Gói quà')
            voucher = self.voucher_id.code if self.voucher_id else ''
            title = _('Khách đã đổi quà Loyalty')
            message = _(
                '%(customer)s đã đổi %(package)s (%(points)s điểm).%(voucher)s',
                customer=self.partner_id.display_name,
                package=package,
                points=f'{self.points_required:,}',
                voucher=f' Voucher: {voucher}' if voucher else '',
            )
        else:
            type_label = dict(self._fields['request_type'].selection).get(
                self.request_type,
                self.request_type,
            )
            title = _('Yêu cầu đổi thưởng Loyalty mới')
            message = _(
                '%(customer)s gửi %(request_type)s %(points)s điểm. Mã: %(name)s',
                customer=self.partner_id.display_name,
                request_type=type_label,
                points=f'{self.points_required:,}',
                name=self.name,
            )
        return title, message

    def _get_loyalty_reward_open_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Yêu cầu đổi thưởng'),
            'res_model': 'hlv.loyalty.reward.request',
            'res_id': self.id,
            'views': [[False, 'form']],
            'view_mode': 'form',
            'target': 'current',
        }

    def _post_loyalty_reward_mail_notification(self, users, title, message):
        self.ensure_one()
        partner_ids = users.mapped('partner_id').ids
        if not partner_ids:
            return

        body = Markup(
            f'<p><strong>{html_escape(title)}</strong></p>'
            f'<p>{html_escape(message)}</p>'
            f'<ul>'
            f'<li>{html_escape(_("Khách hàng"))}: {html_escape(self.partner_id.display_name or "")}</li>'
            f'<li>{html_escape(_("Số điểm"))}: {self.points_required:,}</li>'
            f'<li>{html_escape(_("Trạng thái"))}: {html_escape(dict(self._fields["state"].selection).get(self.state, self.state))}</li>'
            f'</ul>'
        )
        plain_body = self._html_to_plain_text(body)
        try:
            self.sudo().with_context(mail_post_autofollow=False).message_post(
                body=body,
                subject=self._html_to_plain_text(title),
                partner_ids=partner_ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception:
            _logger.debug(
                'Failed to post loyalty reward mail notification for request %s',
                self.id,
                exc_info=True,
            )
        self._create_loyalty_reward_activities(users, title, plain_body)

    @staticmethod
    def _html_to_plain_text(html):
        soup = BeautifulSoup(str(html or ''), 'html.parser')
        for br in soup.find_all('br'):
            br.replace_with('\n')
        text = soup.get_text('\n')
        return '\n'.join(line.strip() for line in text.splitlines() if line.strip())

    @staticmethod
    def _plain_text_to_html(text):
        lines = [html_escape(line) for line in (text or '').splitlines() if line.strip()]
        return Markup('<p>%s</p>') % Markup('<br/>').join(Markup(line) for line in lines)

    def _create_loyalty_reward_activities(self, users, title, message):
        self.ensure_one()
        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not todo_type:
            return
        for user in users:
            existing = self.env['mail.activity'].sudo().search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
                ('user_id', '=', user.id),
                ('activity_type_id', '=', todo_type.id),
                ('summary', '=', title),
            ], limit=1)
            if existing:
                continue
            self.env['mail.activity'].sudo().create({
                'activity_type_id': todo_type.id,
                'res_model_id': self.env['ir.model']._get_id(self._name),
                'res_id': self.id,
                'user_id': user.id,
                'summary': title,
                'note': self._plain_text_to_html(message),
                'date_deadline': fields.Date.context_today(self),
            })

    def _mark_loyalty_reward_activities_done(self, feedback=None):
        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        domain = [
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
        ]
        if todo_type:
            domain.append(('activity_type_id', '=', todo_type.id))
        activities = self.env['mail.activity'].sudo().search(domain)
        if not activities:
            return
        feedback = feedback or _('Yêu cầu đổi thưởng đã được xử lý.')
        try:
            if hasattr(activities, 'action_feedback'):
                activities.action_feedback(feedback=feedback)
            elif hasattr(activities, '_action_done'):
                activities._action_done(feedback=feedback)
            else:
                activities.unlink()
        except Exception:
            _logger.debug(
                'Failed to mark loyalty reward activities done for requests %s',
                self.ids,
                exc_info=True,
            )

    # ── Business logic ─────────────────────────────────────────────────────

    def _deduct_exchange_points(self, description):
        """Deduct exchange points from the account (or legacy root partner), return history record."""
        self.ensure_one()
        root = self.partner_id._get_loyalty_root()
        account = self.account_id
        avail = account.loyalty_exchange_points if account else root.loyalty_exchange_points
        if avail < self.points_required:
            raise UserError(
                f'Không đủ điểm đổi thưởng.\n'
                f'Khách hàng hiện có {avail:,} điểm, yêu cầu {self.points_required:,} điểm.'
            )
        history = self.env['hlv.loyalty.history'].sudo().create({
            'partner_id': root.id,
            'account_id': account.id if account else False,
            'point_amount': -self.points_required,
            'point_type': 'exchange',
            'transaction_type': 'redeem',
            'state': 'confirmed',
            'description': description,
            'company_id': self.company_id.id,
        })
        if account:
            account.invalidate_recordset([
                'loyalty_exchange_points',
                'loyalty_reward_pending_points',
                'loyalty_exchange_available_points',
            ])
        root.invalidate_recordset([
            'loyalty_exchange_points',
            'loyalty_reward_pending_points',
            'loyalty_exchange_available_points',
        ])
        return history

    def _create_voucher(self):
        """Create voucher for gift request, return voucher record."""
        self.ensure_one()
        pkg = self.package_id
        program = pkg.program_id
        validity = pkg.validity_days or (program.voucher_validity_days if program else 30) or 30
        expiry = fields.Datetime.now() + timedelta(days=validity)
        root = self.partner_id._get_loyalty_root()
        return self.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': root.id,
            'account_id': self.account_id.id if self.account_id else False,
            'package_id': pkg.id,
            'date_expiry': expiry,
        })

    def action_done(self):
        """Admin marks request as done → deduct points, create voucher if gift."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError('Chỉ có thể xử lý yêu cầu đang Chờ duyệt.')
            desc = f'Đổi thưởng #{rec.name} – {rec.partner_id.name}'
            hist = rec._deduct_exchange_points(desc)
            voucher_id = False
            if rec.request_type == 'gift' and rec.package_id:
                voucher_id = rec._create_voucher().id
            rec.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
                'done_by_id': self.env.user.id,
                'history_id': hist.id,
                'voucher_id': voucher_id or False,
            })
            rec._mark_loyalty_reward_activities_done(
                _('Yêu cầu đổi thưởng %(name)s đã được xử lý.', name=rec.name)
            )
            if rec.request_type == 'gift':
                rec._send_loyalty_reward_bus_notification('gift_redeemed')
            _logger.info(
                'Loyalty RewardRequest: %s done (%s) – %d pts deducted from %s',
                rec.name, rec.request_type, rec.points_required, rec.partner_id.name,
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError('Không thể hủy yêu cầu đã xử lý.')
            rec.write({'state': 'cancelled'})
            rec._mark_loyalty_reward_activities_done(
                _('Yêu cầu đổi thưởng %(name)s đã bị hủy.', name=rec.name)
            )

    def action_update_bank_info(self, bank_name, account_number, account_name):
        """Khách tự đổi lại STK nhận tiền trên yêu cầu đang chờ duyệt.

        Chỉ cho phép khi còn 'pending' (chưa xử lý/chuyển tiền). Các field
        bank_name/account_number/account_name có tracking=True (model đã
        _inherit mail.thread) nên write() sẽ tự log vào chatter thời điểm
        và giá trị cũ/mới. Route gọi hàm này luôn chạy dưới sudo() (portal
        công khai, không có user Odoo riêng) nên log tracking tự động sẽ
        hiện tên user kỹ thuật (VD: Administrator) - dễ gây hiểu lầm là
        nhân viên tự sửa. Vì vậy post thêm 1 message rõ ràng, gắn tác giả
        là chính khách hàng, để phân biệt đây là khách tự đổi qua Portal.
        """
        self.ensure_one()
        if self.request_type != 'cash':
            raise UserError('Chỉ có thể đổi thông tin nhận tiền cho yêu cầu đổi tiền mặt.')
        if self.state != 'pending':
            raise UserError('Chỉ có thể đổi thông tin nhận tiền khi yêu cầu đang Chờ duyệt.')

        bank_name = (bank_name or '').strip()
        account_number = (account_number or '').strip()
        account_name = (account_name or '').strip()
        if not bank_name or not account_number or not account_name:
            raise UserError('Vui lòng nhập đầy đủ Ngân hàng, Số tài khoản và Tên chủ tài khoản.')

        old_bank, old_number, old_name = self.bank_name, self.account_number, self.account_name
        self.write({
            'bank_name': bank_name,
            'account_number': account_number,
            'account_name': account_name,
        })

        if (old_bank, old_number, old_name) != (bank_name, account_number, account_name):
            rows = [
                (label, old, new)
                for label, old, new in (
                    ('Ngân hàng', old_bank, bank_name),
                    ('Số tài khoản', old_number, account_number),
                    ('Tên chủ tài khoản', old_name, account_name),
                )
                if (old or '') != new
            ]
            body = Markup(
                '<p><strong>🔄 Khách hàng tự đổi thông tin nhận tiền qua Portal Loyalty.</strong></p>'
                '<ul>%s</ul>'
            ) % Markup('').join(
                Markup('<li>%s: %s → <strong>%s</strong></li>') % (
                    label, old or '(trống)', new,
                )
                for label, old, new in rows
            )
            self.message_post(
                body=body,
                author_id=self.partner_id.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
