import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Hạn mặc định cho một việc điền thói quen, và chu kỳ soát lại sau khi đã duyệt.
TASK_DEADLINE_DAYS = 7
REVIEW_CYCLE_DAYS = 180


class HlvDeliveryProfileTask(models.Model):
    """Việc giao cho sale: điền / soát lại thói quen của một điểm giao.

    Lý do model này tồn tại: trong 86 ghim trên bản đồ chỉ có 3 ghim ghi chú thói quen.
    Không có cơ chế giao việc thì bảng thói quen sẽ mãi rỗng, và mọi con số định mức
    của điều phối đều dựa trên giả định.
    """

    _name = 'hlv.delivery.profile.task'
    _description = 'Việc cập nhật thói quen khách'
    _inherit = ['mail.thread']
    _order = 'state, deadline, id'
    _rec_name = 'point_id'

    point_id = fields.Many2one(
        'hlv.delivery.point', string='Điểm giao', required=True, index=True,
        ondelete='cascade',
    )
    profile_id = fields.Many2one(
        'hlv.delivery.partner.profile', string='Bảng thói quen', index=True, ondelete='cascade',
    )
    zone_id = fields.Many2one(related='point_id.zone_id', store=True, string='Cụm tuyến')
    assigned_user_id = fields.Many2one(
        'res.users', string='Sale phụ trách', required=True, index=True, tracking=True,
    )
    assigned_by_id = fields.Many2one(
        'res.users', string='Người giao', default=lambda self: self.env.user, readonly=True,
    )
    deadline = fields.Date(string='Hạn', index=True, tracking=True)
    state = fields.Selection(
        [
            ('open', 'Đang chờ'),
            ('submitted', 'Sale đã xác nhận'),
            ('approved', 'Đã duyệt'),
            ('cancelled', 'Bỏ qua'),
        ],
        default='open', required=True, index=True, tracking=True,
    )
    origin = fields.Selection(
        [('auto', 'Máy sinh'), ('manual', 'Giao tay')], default='manual', required=True,
    )
    missing_fields = fields.Char(
        string='Còn thiếu', compute='_compute_missing', store=True,
    )
    completeness = fields.Float(compute='_compute_missing', store=True, string='Độ đầy (%)')
    note = fields.Text()
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue')

    @api.depends('profile_id.missing_fields', 'profile_id.completeness')
    def _compute_missing(self):
        for task in self:
            task.missing_fields = task.profile_id.missing_fields or ''
            task.completeness = task.profile_id.completeness or 0.0

    @api.depends('state', 'deadline')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            task.is_overdue = bool(
                task.state == 'open' and task.deadline and task.deadline < today
            )

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        overdue = [('state', '=', 'open'), ('deadline', '<', today)]
        positive = (operator == '=' and value) or (operator == '!=' and not value)
        return overdue if positive else ['!', '&'] + overdue

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_submit(self):
        """Sale xác nhận đã điền xong."""
        for task in self:
            if task.state != 'open':
                continue
            task.state = 'submitted'
            task.message_post(body='Sale đã xác nhận thói quen khách.')
        return True

    def action_approve(self):
        """Điều phối duyệt — đặt luôn hạn soát lại cho chu kỳ sau."""
        due = fields.Date.add(fields.Date.context_today(self), days=REVIEW_CYCLE_DAYS)
        for task in self:
            if task.profile_id:
                task.profile_id.write({'review_due_date': due})
            task.state = 'approved'
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_open_profile(self):
        self.ensure_one()
        profile = self.profile_id or self.point_id.get_or_create_profile()
        if not self.profile_id:
            self.profile_id = profile.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Thói quen khách — %s' % self.point_id.name,
            'res_model': 'hlv.delivery.partner.profile',
            'res_id': profile.id,
            'view_mode': 'form',
        }

    @api.model
    def assign_for_points(self, point_ids, user=None, deadline=None, note=''):
        """Giao tay một loạt điểm cho sale. Bỏ qua điểm đã có việc đang mở."""
        points = self.env['hlv.delivery.point'].browse(point_ids)
        created = self.browse()
        for point in points:
            profile = point.get_or_create_profile()
            assignee = user or profile.responsible_sale_user_id
            if not assignee:
                raise UserError(
                    'Điểm "%s" chưa có sale phụ trách — chọn người nhận việc.' % point.name
                )
            if self.search_count([
                ('point_id', '=', point.id), ('state', 'in', ('open', 'submitted')),
            ]):
                continue
            created |= self.create({
                'point_id': point.id,
                'profile_id': profile.id,
                'assigned_user_id': assignee.id,
                'deadline': deadline or fields.Date.add(
                    fields.Date.context_today(self), days=TASK_DEADLINE_DAYS,
                ),
                'note': note,
                'origin': 'manual',
            })
        return created

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def cron_generate_tasks(self, limit=200):
        """Sinh việc cho mọi điểm có sale phụ trách mà thói quen chưa xong.

        Không sinh trùng: điểm đã có việc đang mở hoặc chờ duyệt thì bỏ qua.
        """
        Profile = self.env['hlv.delivery.partner.profile']
        profiles = Profile.search([
            ('responsible_sale_user_id', '!=', False),
            ('verification_state', 'in', ('draft', 'expired')),
        ], limit=limit)
        if not profiles:
            return 0
        busy_points = set(self.search([
            ('point_id', 'in', profiles.mapped('point_id').ids),
            ('state', 'in', ('open', 'submitted')),
        ]).mapped('point_id').ids)
        deadline = fields.Date.add(fields.Date.context_today(self), days=TASK_DEADLINE_DAYS)
        created_by_user = {}
        for profile in profiles:
            if profile.point_id.id in busy_points:
                continue
            task = self.create({
                'point_id': profile.point_id.id,
                'profile_id': profile.id,
                'assigned_user_id': profile.responsible_sale_user_id.id,
                'deadline': deadline,
                'origin': 'auto',
            })
            created_by_user.setdefault(profile.responsible_sale_user_id, self.browse())
            created_by_user[profile.responsible_sale_user_id] |= task
        if created_by_user:
            self._push_new_tasks(created_by_user)
            _logger.info(
                'Việc thói quen khách: sinh %s việc cho %s sale',
                sum(len(t) for t in created_by_user.values()), len(created_by_user),
            )
        return sum(len(t) for t in created_by_user.values())

    @api.model
    def cron_close_done_tasks(self):
        """Đóng việc khi thói quen đã được xác nhận ngoài luồng (điều phối tự điền)."""
        tasks = self.search([('state', '=', 'open')])
        done = tasks.filtered(
            lambda t: t.profile_id and t.profile_id.verification_state == 'confirmed'
        )
        if done:
            done.write({'state': 'submitted'})
        return len(done)

    def _push_new_tasks(self, created_by_user):
        """Một thông báo gộp cho mỗi sale, không phải mỗi việc một cái."""
        try:
            from odoo.addons.hlv_sale_delivery_planning.controllers.sale_plan_controller import (
                _send_sale_plan_webpush,
            )
        except Exception:
            return 0
        Subscription = self.env['hlv.sale.plan.web.push.subscription'].sudo()
        sent = 0
        for user, tasks in created_by_user.items():
            subs = Subscription.search([('active', '=', True), ('user_id', '=', user.id)])
            if not subs:
                continue
            sample = ', '.join(tasks[:3].mapped('point_id.name'))
            sent += _send_sale_plan_webpush(self.env, subs, {
                'type': 'dispatch_profile_task',
                'title': 'Có %s khách cần bạn điền thói quen giao hàng' % len(tasks),
                'body': sample + ('…' if len(tasks) > 3 else ''),
                'url': '/delivery_plan?tab=points',
                'tag': 'dispatch-profile-task-%s' % user.id,
            })
        return sent
