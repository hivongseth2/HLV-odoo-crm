import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Trạng thái hàng coi là "đủ để lên xe". Lấy đúng bộ giá trị của
# hlv.delivery.planner.snapshot.stock_status, không tự định nghĩa lại.
READY_STOCK_STATES = ('ready', 'delivered')


class HlvDeliveryTripRegistration(models.Model):
    """Sale đăng ký cho đơn của mình đi một chuyến.

    Đăng ký ở CẤP ĐƠN (một bản ghi cho một sale.order), nhưng giao diện gom hiển thị
    theo điểm — ba đơn cùng khách hiện thành một dòng có badge "3 đơn".
    """

    _name = 'hlv.delivery.trip.registration'
    _description = 'Đăng ký chuyến giao hàng'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _rec_name = 'sale_order_id'

    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn hàng', required=True, index=True, ondelete='cascade',
        tracking=True,
    )
    partner_id = fields.Many2one(related='sale_order_id.partner_id', store=True, index=True)
    point_id = fields.Many2one(
        related='sale_order_id.partner_id.x_delivery_point_id', store=True, index=True,
        string='Điểm giao',
    )
    warehouse_id = fields.Many2one(
        related='sale_order_id.warehouse_id', store=True, index=True, string='Kho',
    )
    saler_code = fields.Char(
        string='Mã sale', compute='_compute_saler_code', store=True, index=True,
    )
    requested_by_id = fields.Many2one(
        'res.users', string='Người đăng ký', required=True, index=True,
        default=lambda self: self.env.user, tracking=True,
    )
    desired_date = fields.Date(
        string='Ngày mong muốn', required=True, index=True, tracking=True,
        default=fields.Date.context_today,
    )
    trip_id = fields.Many2one(
        'hlv.delivery.trip', string='Chuyến', index=True, tracking=True,
        help='Để trống nghĩa là "xin giao ngày này, điều phối tự xếp chuyến".',
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('submitted', 'Chờ duyệt'),
            ('accepted', 'Đã nhận'),
            ('rejected', 'Từ chối'),
            ('deferred', 'Dời lại'),
            ('cancelled', 'Đã huỷ'),
        ],
        default='draft', required=True, index=True, tracking=True,
    )
    priority = fields.Selection(
        [('0', 'Bình thường'), ('1', 'Gấp')], default='0', string='Mức ưu tiên', tracking=True,
    )
    reason = fields.Text(string='Lý do của sale')
    dispatcher_note = fields.Text(string='Phản hồi của điều phối', tracking=True)
    handled_by_id = fields.Many2one('res.users', string='Người xử lý', readonly=True)
    handled_at = fields.Datetime(string='Xử lý lúc', readonly=True)
    auto_accepted = fields.Boolean(string='Máy tự nhận', readonly=True)

    resulting_stop_id = fields.Many2one(
        'hlv.delivery.trip.stop', string='Điểm đã xếp', readonly=True,
        help='Chỉ được set khi hàng đã đủ và đơn thực sự vào chuyến.',
    )

    stock_state = fields.Selection(
        [
            ('ready', 'Đủ hàng'),
            ('partial_ready', 'Đủ một phần'),
            ('out_of_stock', 'Chưa có hàng'),
            ('delivered', 'Đã giao'),
            ('unknown', 'Chưa rõ'),
        ],
        string='Tình trạng hàng', compute='_compute_stock_state', store=True, index=True,
    )
    is_waiting_goods = fields.Boolean(
        string='Chờ hàng', compute='_compute_stock_state', store=True, index=True,
    )

    @api.constrains('sale_order_id', 'state')
    def _check_single_active_registration(self):
        """Một đơn chỉ được có một đăng ký đang sống.

        Không dùng ràng buộc SQL: unique một phần (partial unique index) không khai được
        qua _sql_constraints, còn EXCLUDE thì cần extension btree_gist.
        """
        for reg in self.filtered(lambda r: r.state in ('submitted', 'accepted')):
            duplicate = self.search_count([
                ('id', '!=', reg.id),
                ('sale_order_id', '=', reg.sale_order_id.id),
                ('state', 'in', ('submitted', 'accepted')),
            ])
            if duplicate:
                raise ValidationError(
                    'Đơn %s đã có một đăng ký đang chờ duyệt hoặc đã được nhận.'
                    % reg.sale_order_id.name
                )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('sale_order_id')
    def _compute_saler_code(self):
        for reg in self:
            reg.saler_code = (
                getattr(reg.sale_order_id, 'x_studio_misa_saler_code', '') or ''
            ).strip()

    @api.depends('sale_order_id')
    def _compute_stock_state(self):
        """Đọc tình trạng hàng từ snapshot của hlv_sale_delivery_planning.

        Không tự tính lại: snapshot đã có cron làm sạch và đã xử lý các trường hợp
        đơn bị trả/ngừng, giao một phần, đã giao trong ngày.
        """
        snapshots = {}
        order_ids = self.mapped('sale_order_id').ids
        if order_ids:
            for snap in self.env['hlv.delivery.planner.snapshot'].sudo().search([
                ('sale_order_id', 'in', order_ids),
            ]):
                snapshots[snap.sale_order_id.id] = snap.stock_status
        for reg in self:
            status = snapshots.get(reg.sale_order_id.id) or 'unknown'
            reg.stock_state = status
            reg.is_waiting_goods = status not in READY_STOCK_STATES

    # ------------------------------------------------------------------
    # Ràng buộc
    # ------------------------------------------------------------------
    @api.constrains('trip_id', 'desired_date')
    def _check_trip_date(self):
        for reg in self:
            if reg.trip_id and reg.trip_id.date and reg.trip_id.date != reg.desired_date:
                raise ValidationError(
                    'Chuyến "%s" chạy ngày %s, không khớp ngày mong muốn %s.'
                    % (reg.trip_id.name, reg.trip_id.date, reg.desired_date)
                )

    # ------------------------------------------------------------------
    # Luồng
    # ------------------------------------------------------------------
    def action_submit(self):
        for reg in self:
            if reg.state not in ('draft', 'deferred'):
                raise UserError('Chỉ đăng ký ở trạng thái nháp/dời lại mới gửi được.')
            reg.state = 'submitted'
            reg._notify_dispatcher()
            reg._try_auto_accept()
        return True

    def _warehouse_config(self):
        """Cấu hình kho — đọc bằng sudo vì sale không nhất thiết đọc được stock.warehouse."""
        self.ensure_one()
        warehouse = self.trip_id.warehouse_id or self.warehouse_id
        return warehouse.sudo()

    def _try_auto_accept(self):
        """Tự nhận nếu kho bật auto-accept và chuyến còn nhận đăng ký.

        Trần điểm là trần MỀM nên chỗ đã đầy không phải lý do từ chối — chỉ cảnh báo
        cho điều phối thấy trên màn xếp chuyến.
        """
        self.ensure_one()
        if self.state != 'submitted' or not self.trip_id:
            return False
        warehouse = self._warehouse_config()
        if not warehouse or not warehouse.x_dispatch_auto_accept:
            return False
        if not self.trip_id.accepts_registration:
            return False
        # sudo: chính sale đang bấm, mà xếp điểm vào chuyến là việc của điều phối —
        # sale không có quyền ghi trip.stop.
        self.sudo()._accept(auto=True)
        return True

    def action_accept(self):
        for reg in self:
            if not reg.trip_id:
                raise UserError(
                    'Chưa chọn chuyến cho đăng ký của đơn %s.' % reg.sale_order_id.name
                )
            reg._accept(auto=False)
        return True

    def _accept(self, auto=False):
        self.ensure_one()
        self.write({
            'state': 'accepted',
            'handled_by_id': self.env.user.id,
            'handled_at': fields.Datetime.now(),
            'auto_accepted': auto,
        })
        self._assign_stop_if_ready()
        self._notify_requester('accepted')
        return True

    def _assign_stop_if_ready(self):
        """Chỉ đưa đơn vào chuyến khi hàng đã đủ.

        Đơn chưa đủ hàng vẫn nằm trong chuyến dưới dạng "chờ hàng" để điều phối nhìn
        thấy trước — tránh cảnh vừa cho xe đi thì hàng về.
        """
        self.ensure_one()
        if self.state != 'accepted' or not self.trip_id or self.resulting_stop_id:
            return False
        if self.is_waiting_goods:
            return False
        record = self.sudo()
        stop = record.trip_id.add_sale_order(record.sale_order_id)
        record.resulting_stop_id = stop.id
        return True

    def action_reject(self):
        for reg in self:
            reg.write({
                'state': 'rejected',
                'handled_by_id': self.env.user.id,
                'handled_at': fields.Datetime.now(),
            })
            reg._notify_requester('rejected')
        return True

    def action_defer(self):
        self._defer()
        return True

    def _defer(self, note=None):
        for reg in self:
            vals = {
                'state': 'deferred',
                'handled_by_id': self.env.user.id,
                'handled_at': fields.Datetime.now(),
            }
            if note:
                vals['dispatcher_note'] = note
            reg.write(vals)
            reg._notify_requester('deferred')
        return True

    def action_cancel(self):
        for reg in self:
            if reg.resulting_stop_id:
                # sudo: gỡ đơn khỏi điểm là thao tác trên chuyến, sale không ghi được.
                stop = reg.resulting_stop_id.sudo()
                stop.sale_order_ids = [fields.Command.unlink(reg.sale_order_id.id)]
                if not stop.sale_order_ids:
                    stop.unlink()
                reg.sudo().resulting_stop_id = False
            reg.state = 'cancelled'
        return True

    # ------------------------------------------------------------------
    # Cron: đơn chờ hàng đã đủ hàng thì đẩy vào chuyến
    # ------------------------------------------------------------------
    @api.model
    def cron_promote_waiting_goods(self, limit=200):
        """Quét đăng ký đang chờ hàng, đưa vào chuyến khi snapshot báo đã đủ.

        Một chiều: chỉ ĐỌC snapshot của module hlv_sale_delivery_planning, không can
        thiệp vào cron làm sạch snapshot của module đó.
        """
        regs = self.search([
            ('state', '=', 'accepted'),
            ('is_waiting_goods', '=', True),
            ('resulting_stop_id', '=', False),
        ], limit=limit)
        if not regs:
            return 0
        # Bắt buộc tính lại vì stock_state là stored compute, chỉ đổi khi đơn đổi —
        # còn snapshot thì được cron của module cũ cập nhật độc lập.
        regs._compute_stock_state()
        regs.flush_recordset(['stock_state', 'is_waiting_goods'])
        promoted = 0
        for reg in regs:
            if reg.is_waiting_goods:
                continue
            if not reg.trip_id:
                continue
            if reg.trip_id.accepts_registration or reg.trip_id.state == 'published':
                try:
                    if reg._assign_stop_if_ready():
                        promoted += 1
                        reg._notify_requester('loaded')
                except UserError as exc:
                    reg.message_post(body='Không xếp được vào chuyến: %s' % exc)
            else:
                reg._defer('Hàng về sau khi chuyến đã khoá — cần chọn chuyến khác.')
        if promoted:
            _logger.info('Đăng ký chờ hàng: đã xếp %s đơn vào chuyến', promoted)
        return promoted

    # ------------------------------------------------------------------
    # Thông báo
    # ------------------------------------------------------------------
    def _notify_dispatcher(self):
        self.ensure_one()
        self.env['bus.bus'].sudo()._sendone('delivery_planner_channel', 'dispatch_registration_new', {
            'registration_id': self.id,
            'order_id': self.sale_order_id.id,
            'order_name': self.sale_order_id.name,
            'partner_name': self.partner_id.display_name,
            'desired_date': fields.Date.to_string(self.desired_date),
            'trip_id': self.trip_id.id,
            'trip_name': self.trip_id.name or '',
            'requested_by': self.requested_by_id.display_name,
            'priority': self.priority,
        })

    def _notify_requester(self, action):
        self.ensure_one()
        labels = {
            'accepted': 'Đăng ký đã được nhận',
            'rejected': 'Đăng ký bị từ chối',
            'deferred': 'Đăng ký bị dời lại',
            'loaded': 'Đơn đã được xếp vào chuyến',
        }
        title = labels.get(action, 'Đăng ký có cập nhật')
        body = '%s — %s%s' % (
            self.sale_order_id.name,
            self.trip_id.name or 'chưa gán chuyến',
            (': %s' % self.dispatcher_note) if self.dispatcher_note else '',
        )
        payload = {
            'registration_id': self.id,
            'order_id': self.sale_order_id.id,
            'order_name': self.sale_order_id.name,
            'state': self.state,
            'action': action,
            'title': title,
            'body': body,
            'trip_id': self.trip_id.id,
            'user_id': self.requested_by_id.id,
        }
        self.env['bus.bus'].sudo()._sendone(
            'sale_plan_public_channel', 'dispatch_registration_handled', payload,
        )
        self.message_post(body='%s. %s' % (title, body))
        self._push_webpush(title, body)

    def _push_webpush(self, title, body):
        self.ensure_one()
        try:
            from odoo.addons.hlv_sale_delivery_planning.controllers.sale_plan_controller import (
                _send_sale_plan_webpush,
            )
        except Exception:
            return 0
        subs = self.env['hlv.sale.plan.web.push.subscription'].sudo().search([
            ('active', '=', True), ('user_id', '=', self.requested_by_id.id),
        ])
        return _send_sale_plan_webpush(self.env, subs, {
            'type': 'dispatch_registration_handled',
            'title': title,
            'body': body,
            'url': '/delivery_plan?tab=mine',
            'tag': 'dispatch-reg-%s' % self.id,
        })
