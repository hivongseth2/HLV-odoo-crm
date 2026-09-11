import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'Asia/Ho_Chi_Minh'
# Thời gian đứng tại điểm khi khách chưa khai thói quen.
FALLBACK_SERVICE_MINUTES = 10


class HlvDeliveryTrip(models.Model):
    _name = 'hlv.delivery.trip'
    _description = 'Chuyến giao hàng'
    _inherit = ['mail.thread']
    _order = 'plan_day_id, sequence, id'

    name = fields.Char(required=True, default='Chuyến mới', tracking=True)
    sequence = fields.Integer(default=10)
    plan_day_id = fields.Many2one(
        'hlv.delivery.plan.day', string='Kế hoạch ngày', required=True, index=True,
        ondelete='cascade',
    )
    date = fields.Date(related='plan_day_id.date', store=True, index=True)
    warehouse_id = fields.Many2one(related='plan_day_id.warehouse_id', store=True, index=True)
    company_id = fields.Many2one(related='plan_day_id.company_id', store=True, index=True)
    zone_id = fields.Many2one('hlv.delivery.zone', string='Cụm tuyến', index=True, tracking=True)

    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe', tracking=True,
        domain="[('x_dispatch_enabled', '=', True)]",
    )
    driver_user_id = fields.Many2one(
        'res.users', string='Tài xế', tracking=True,
        help='Nguồn sự thật về tài xế. Khớp thẳng với stock.picking.shipper_user_id khi đối '
             'chiếu kế hoạch với thực tế.',
    )
    driver_partner_id = fields.Many2one(
        related='driver_user_id.partner_id', string='Liên hệ tài xế', store=False,
    )
    driver_display_name = fields.Char(
        compute='_compute_driver_display_name', store=True, string='Tên tài xế',
    )
    driver_name_note = fields.Char(
        string='Tên tài xế thật', tracking=True,
        help='Bắt buộc khi gán vào tài khoản dùng chung (VD "Tài xế khác") — nếu không thì hai '
             'chuyến cùng ngày sẽ không phân biệt được ai lái xe nào.',
    )
    fleet_driver_mismatch = fields.Char(compute='_compute_fleet_driver_mismatch')

    session = fields.Selection(
        [
            ('morning', 'Sáng'),
            ('afternoon', 'Chiều'),
            ('flexible', 'Linh hoạt'),
            ('technical', 'Kỹ thuật'),
        ],
        string='Ca', default='flexible', required=True, tracking=True,
        help='Không nên chia cứng sáng/chiều quá sớm: khi đơn bị chặn thủ tục, tài xế tự lấp '
             'bằng điểm khác.',
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('planned', 'Đã xếp'),
            ('published', 'Đã công bố'),
            ('departed', 'Đã xuất phát'),
            ('done', 'Hoàn tất'),
            ('cancelled', 'Huỷ'),
        ],
        default='draft', required=True, index=True, tracking=True,
    )
    planned_depart_at = fields.Datetime(string='Giờ xuất phát dự kiến', tracking=True)
    note = fields.Text()

    stop_ids = fields.One2many('hlv.delivery.trip.stop', 'trip_id', string='Điểm giao')
    stop_count = fields.Integer(compute='_compute_stop_stats', store=True)
    order_count = fields.Integer(compute='_compute_stop_stats', store=True)
    piece_count = fields.Integer(
        string='Số kiện (nhập tay)',
        help='Odoo không tính được: cân nặng chỉ có ở 751/25178 sản phẩm. Điều phối ước lượng '
             'và nhập tay. Kim Long và EC Van đều chở 15 kiện thoải mái.',
    )
    estimated_minutes = fields.Integer(compute='_compute_estimated_minutes', store=True)

    max_stops = fields.Integer(compute='_compute_capacity', store=True, string='Trần điểm')
    slots_left = fields.Integer(compute='_compute_capacity', store=True, string='Còn chỗ')
    is_over_capacity = fields.Boolean(
        compute='_compute_capacity', store=True, string='Vượt trần',
        help='Trần mềm: chỉ cảnh báo, không chặn.',
    )

    # --- Đăng ký từ sale ----------------------------------------------------
    registration_ids = fields.One2many(
        'hlv.delivery.trip.registration', 'trip_id', string='Đăng ký của sale',
    )
    pending_registration_ids = fields.One2many(
        'hlv.delivery.trip.registration', 'trip_id', string='Đơn chờ hàng',
        domain=[('state', '=', 'accepted'), ('is_waiting_goods', '=', True)],
    )
    pending_registration_count = fields.Integer(compute='_compute_registration_counts')
    new_registration_count = fields.Integer(compute='_compute_registration_counts')

    registration_deadline = fields.Datetime(
        string='Hạn đăng ký', compute='_compute_registration_deadline',
        store=True, readonly=False, tracking=True,
        help='Mặc định lấy theo cấu hình của kho, sửa được cho từng chuyến.',
    )
    is_locked = fields.Boolean(string='Đã khoá', tracking=True, copy=False)
    locked_by_id = fields.Many2one('res.users', string='Người khoá', readonly=True, copy=False)
    locked_at = fields.Datetime(string='Khoá lúc', readonly=True, copy=False)
    lock_reason = fields.Char(string='Lý do khoá', copy=False)
    accepts_registration = fields.Boolean(compute='_compute_accepts_registration')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('driver_user_id', 'driver_user_id.dispatch_driver_name')
    def _compute_driver_display_name(self):
        for trip in self:
            trip.driver_display_name = trip.driver_user_id.dispatch_driver_name or ''

    @api.depends('driver_user_id', 'vehicle_id', 'vehicle_id.driver_id')
    def _compute_fleet_driver_mismatch(self):
        """Cảnh báo (không chặn) khi tài xế của chuyến khác tài xế đang gán cho xe trong Đội xe.

        Bỏ qua với tài khoản dùng chung, vì tài khoản đó không đại diện một người cụ thể
        nên cảnh báo sẽ luôn kêu.
        """
        for trip in self:
            trip.fleet_driver_mismatch = False
            if not trip.vehicle_id or not trip.driver_user_id:
                continue
            if trip.driver_user_id.x_is_shared_driver:
                continue
            fleet_driver = trip.vehicle_id.driver_id
            if fleet_driver and fleet_driver != trip.driver_user_id.partner_id:
                trip.fleet_driver_mismatch = (
                    'Trong Đội xe, %s đang gán cho %s.' % (
                        trip.vehicle_id.display_name, fleet_driver.display_name,
                    )
                )

    @api.depends('stop_ids', 'stop_ids.sale_order_ids', 'stop_ids.state')
    def _compute_stop_stats(self):
        for trip in self:
            stops = trip.stop_ids.filtered(lambda s: s.state != 'skipped')
            trip.stop_count = len(stops)
            trip.order_count = len(stops.mapped('sale_order_ids'))

    @api.depends('stop_ids', 'stop_count', 'zone_id',
                 'zone_id.hub_to_first_minutes', 'zone_id.median_leg_minutes')
    def _compute_estimated_minutes(self):
        for trip in self:
            if not trip.stop_count:
                trip.estimated_minutes = 0
                continue
            zone = trip.zone_id
            hub = zone.hub_to_first_minutes if zone else 42
            leg = zone.median_leg_minutes if zone else 16
            service = 0
            for stop in trip.stop_ids:
                service += stop.service_minutes or FALLBACK_SERVICE_MINUTES
            trip.estimated_minutes = hub + leg * max(0, trip.stop_count - 1) + service

    @api.depends('stop_count', 'zone_id', 'zone_id.max_stops')
    def _compute_capacity(self):
        for trip in self:
            max_stops = trip.zone_id.max_stops or 0
            trip.max_stops = max_stops
            trip.slots_left = (max_stops - trip.stop_count) if max_stops else 0
            trip.is_over_capacity = bool(max_stops) and trip.stop_count > max_stops

    @api.depends('registration_ids', 'registration_ids.state',
                 'registration_ids.is_waiting_goods')
    def _compute_registration_counts(self):
        for trip in self:
            regs = trip.registration_ids
            trip.pending_registration_count = len(
                regs.filtered(lambda r: r.state == 'accepted' and r.is_waiting_goods)
            )
            trip.new_registration_count = len(regs.filtered(lambda r: r.state == 'submitted'))

    @api.depends('date', 'planned_depart_at', 'warehouse_id',
                 'warehouse_id.x_dispatch_deadline_time',
                 'warehouse_id.x_dispatch_deadline_offset_h')
    def _compute_registration_deadline(self):
        for trip in self:
            trip.registration_deadline = trip._default_registration_deadline()

    def _default_registration_deadline(self):
        """Hạn đăng ký mặc định theo cấu hình kho.

        offset > 0  -> tính lùi từ giờ xe chạy.
        offset == 0 -> giờ tuyệt đối trong ngày (mặc định 15:00 giờ VN).
        """
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse or not self.date:
            return False
        offset = warehouse.x_dispatch_deadline_offset_h or 0.0
        if offset and self.planned_depart_at:
            return self.planned_depart_at - timedelta(hours=offset)
        hour_float = warehouse.x_dispatch_deadline_time
        if hour_float is False or hour_float is None:
            hour_float = 15.0
        hours = int(hour_float)
        minutes = int(round((hour_float - hours) * 60))
        tz = pytz.timezone(self.env.user.tz or DEFAULT_TZ)
        local = tz.localize(datetime.combine(self.date, time(hour=min(hours, 23), minute=min(minutes, 59))))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.depends('state', 'is_locked', 'registration_deadline')
    def _compute_accepts_registration(self):
        # Không store được: giá trị còn phụ thuộc thời điểm hiện tại so với hạn đăng ký.
        now = fields.Datetime.now()
        for trip in self:
            trip.accepts_registration = bool(
                trip.state == 'published'
                and not trip.is_locked
                and (not trip.registration_deadline or trip.registration_deadline > now)
            )

    # ------------------------------------------------------------------
    # Ràng buộc
    # ------------------------------------------------------------------
    @api.constrains('driver_user_id', 'driver_name_note')
    def _check_shared_driver_note(self):
        for trip in self:
            if trip.driver_user_id.x_is_shared_driver and not (trip.driver_name_note or '').strip():
                raise ValidationError(
                    'Tài khoản "%s" là tài khoản tài xế dùng chung. Phải ghi tên tài xế thật '
                    'vào ô "Tên tài xế thật", nếu không hai chuyến cùng ngày sẽ không phân '
                    'biệt được ai lái xe nào.' % trip.driver_user_id.dispatch_driver_name
                )

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_lock(self):
        self.write({
            'is_locked': True,
            'locked_by_id': self.env.user.id,
            'locked_at': fields.Datetime.now(),
        })
        self._notify_changed('locked')
        return True

    def action_unlock(self):
        self.write({'is_locked': False, 'locked_by_id': False, 'locked_at': False})
        self._notify_changed('unlocked')
        return True

    def action_plan(self):
        self.filtered(lambda t: t.state == 'draft').write({'state': 'planned'})
        return True

    def action_depart(self):
        for trip in self:
            if trip.state != 'published':
                raise UserError('Chỉ chuyến đã công bố mới cho xuất phát.')
            trip.write({'state': 'departed', 'is_locked': True})
        self._notify_changed('departed')
        return True

    def action_done(self):
        self.write({'state': 'done'})
        self._notify_changed('done')
        return True

    def action_cancel(self):
        for trip in self:
            trip.registration_ids.filtered(
                lambda r: r.state in ('submitted', 'accepted')
            )._defer('Chuyến đã bị huỷ.')
            trip.write({'state': 'cancelled'})
        self._notify_changed('cancelled')
        return True

    # ------------------------------------------------------------------
    # Thông báo
    # ------------------------------------------------------------------
    def _interested_sale_user_ids(self):
        """User sale có đơn nằm trong chuyến này (suy từ mã sale MISA của đơn)."""
        self.ensure_one()
        orders = self.stop_ids.mapped('sale_order_ids')
        codes = {
            (getattr(o, 'x_studio_misa_saler_code', '') or '').strip().upper()
            for o in orders
        }
        codes.discard('')
        if not codes:
            return []
        code_map = self.env['hlv.delivery.partner.profile']._user_ids_by_saler_code()
        user_ids = set()
        for code in codes:
            user_ids.update(code_map.get(code, []))
        return list(user_ids)

    def _notify_changed(self, action='update'):
        payload_base = {'action': action}
        bus = self.env['bus.bus'].sudo()
        for trip in self:
            payload = dict(
                payload_base,
                trip_id=trip.id,
                trip_name=trip.name,
                plan_day_id=trip.plan_day_id.id,
                date=fields.Date.to_string(trip.date) if trip.date else False,
                warehouse_id=trip.warehouse_id.id,
                state=trip.state,
            )
            bus._sendone('delivery_planner_channel', 'dispatch_trip_changed', payload)
            if trip.state in ('published', 'departed', 'done', 'cancelled'):
                bus._sendone('sale_plan_public_channel', 'dispatch_trip_changed', payload)
        return True

    # ------------------------------------------------------------------
    # Xếp điểm
    # ------------------------------------------------------------------
    def add_sale_order(self, order):
        """Đưa một đơn vào chuyến, gộp vào điểm sẵn có nếu cùng điểm giao.

        Gộp theo ĐIỂM chứ không theo mã khách: nhiều đơn cùng một khách tốn thêm 0 phút
        (trung vị), nên chúng phải nằm chung một stop.
        """
        self.ensure_one()
        point = order.partner_id.x_delivery_point_id
        if not point:
            raise UserError(
                'Khách "%s" chưa được gắn điểm giao. Vào Điều phối > Điểm giao để gắn trước.'
                % order.partner_id.display_name
            )
        stop = self.stop_ids.filtered(lambda s: s.point_id == point)[:1]
        if stop:
            stop.sale_order_ids = [fields.Command.link(order.id)]
        else:
            stop = self.env['hlv.delivery.trip.stop'].create({
                'trip_id': self.id,
                'point_id': point.id,
                'sequence': (max(self.stop_ids.mapped('sequence')) + 10) if self.stop_ids else 10,
                'sale_order_ids': [fields.Command.set([order.id])],
            })
        return stop
