"""API và trang /delivery_plan cho sale.

Toàn bộ việc lọc "sale có được thấy điểm của sale khác không" nằm ở đây chứ không nằm
trong record rule: quy tắc phụ thuộc cấu hình từng kho và phải so mã sale MISA vốn là
chuỗi nhiều mã phân tách bởi dấu phẩy — viết trong domain XML sẽ vừa khó đọc vừa dễ vỡ.
"""

import logging

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_ORDER_SEARCH = 40

# Field sale được phép ghi vào bảng thói quen khách. Whitelist nằm ở SERVER — client chỉ
# dùng danh sách này để dựng form, không phải nơi quyết định.
SALE_EDITABLE_PROFILE_FIELDS = (
    'zone_id', 'default_vehicle_id', 'procedure_before', 'needs_technician',
    'service_minutes', 'receiving_from', 'receiving_to', 'payment_method',
    'oversize_note', 'delivery_method', 'free_note',
)
INT_PROFILE_FIELDS = ('service_minutes',)
M2O_PROFILE_FIELDS = ('zone_id', 'default_vehicle_id')
BOOL_PROFILE_FIELDS = ('needs_technician',)
TIME_PROFILE_FIELDS = ('receiving_from', 'receiving_to')


def _parse_hour(value):
    """Nhận "08:30" (input type=time) hoặc số thực 8.5 — trả về float giờ."""
    if value in (None, '', False):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ':' in text:
        parts = text.split(':')
        try:
            return int(parts[0]) + int(parts[1]) / 60.0
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(text.replace(',', '.'))
    except ValueError:
        return 0.0


def _hour_to_text(value):
    value = value or 0.0
    if not value:
        return ''
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return '%02d:%02d' % (min(hours, 23), minutes)


def _ok(**kw):
    return dict({'status': 'success'}, **kw)


def _err(message):
    return {'status': 'error', 'message': message}


class DispatchController(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _user_saler_codes(self):
        """Mã sale MISA của tài khoản đang đăng nhập.

        Dùng lại đúng hàm của hlv_sale_delivery_planning để không có hai chỗ định nghĩa
        "đơn của tôi" lệch nhau.
        """
        service = request.env['hlv.delivery.planner.service']
        return {c.upper() for c in service._get_current_user_misa_codes()}

    def _is_dispatcher(self):
        return request.env.user.has_group('hlv_delivery_dispatch.group_dispatch_manager')

    def _order_is_mine(self, order, codes):
        code = (getattr(order, 'x_studio_misa_saler_code', '') or '').strip().upper()
        return bool(code) and code in codes

    def _warehouses(self):
        return request.env['stock.warehouse'].sudo().search([('x_dispatch_enabled', '=', True)])

    def _stop_payload(self, stop, codes, warehouse, show_all):
        mine_orders = [o for o in stop.sale_order_ids if self._order_is_mine(o, codes)]
        is_mine = bool(mine_orders)
        visible_orders = stop.sale_order_ids if (show_all or self._is_dispatcher()) else mine_orders
        show_amount = warehouse.x_dispatch_cross_sale_show_amount or self._is_dispatcher()
        return {
            'id': stop.id,
            'sequence': stop.sequence,
            'point_name': stop.point_id.name,
            'zone_name': stop.zone_id.name or '',
            'address': stop.point_id.address or '',
            'is_mine': is_mine,
            'order_count': len(stop.sale_order_ids),
            'mine_order_count': len(mine_orders),
            'service_minutes': stop.service_minutes,
            'procedure_before': stop.procedure_before or 'none',
            'needs_technician': stop.needs_technician,
            'state': stop.state,
            'orders': [
                {
                    'id': o.id,
                    'name': o.name,
                    'partner_name': o.partner_id.display_name,
                    'is_mine': self._order_is_mine(o, codes),
                    'amount': o.amount_total if (show_amount or self._order_is_mine(o, codes)) else None,
                }
                for o in visible_orders
            ],
        }

    def _trip_payload(self, trip, codes, detail=False):
        warehouse = trip.warehouse_id
        show_all = warehouse.x_dispatch_cross_sale_visible or self._is_dispatcher()
        stops = trip.stop_ids.sorted(lambda s: (s.sequence, s.id))
        visible_stops = stops
        hidden_count = 0
        if not show_all:
            visible_stops = stops.filtered(
                lambda s: any(self._order_is_mine(o, codes) for o in s.sale_order_ids)
            )
            hidden_count = len(stops) - len(visible_stops)
        mine_stop_count = len(stops.filtered(
            lambda s: any(self._order_is_mine(o, codes) for o in s.sale_order_ids)
        ))
        payload = {
            'id': trip.id,
            'name': trip.name,
            'zone_name': trip.zone_id.name or '',
            'session': trip.session,
            'state': trip.state,
            'vehicle_name': trip.vehicle_id.display_name or '',
            'driver_name': trip.driver_display_name or '',
            'driver_note': trip.driver_name_note or '',
            'planned_depart_at': fields.Datetime.to_string(trip.planned_depart_at)
            if trip.planned_depart_at else '',
            'stop_count': trip.stop_count,
            'order_count': trip.order_count,
            'max_stops': trip.max_stops,
            'slots_left': trip.slots_left,
            'is_over_capacity': trip.is_over_capacity,
            'estimated_minutes': trip.estimated_minutes,
            'is_locked': trip.is_locked,
            'lock_reason': trip.lock_reason or '',
            'accepts_registration': trip.accepts_registration,
            'registration_deadline': fields.Datetime.to_string(trip.registration_deadline)
            if trip.registration_deadline else '',
            'mine_stop_count': mine_stop_count,
            'hidden_stop_count': hidden_count,
            'waiting_count': trip.pending_registration_count,
        }
        if detail:
            payload['stops'] = [
                self._stop_payload(s, codes, warehouse, show_all) for s in visible_stops
            ]
            payload['waiting'] = [
                {
                    'order_name': reg.sale_order_id.name,
                    'partner_name': reg.partner_id.display_name,
                    'stock_state': reg.stock_state,
                    'is_mine': reg.requested_by_id.id == request.env.user.id,
                }
                for reg in trip.pending_registration_ids
                if show_all or reg.requested_by_id.id == request.env.user.id
            ]
        return payload

    def _registration_payload(self, reg):
        return {
            'id': reg.id,
            'order_id': reg.sale_order_id.id,
            'order_name': reg.sale_order_id.name,
            'partner_name': reg.partner_id.display_name,
            'point_name': reg.point_id.name or '',
            'desired_date': fields.Date.to_string(reg.desired_date),
            'trip_id': reg.trip_id.id,
            'trip_name': reg.trip_id.name or '',
            'state': reg.state,
            'priority': reg.priority,
            'reason': reg.reason or '',
            'dispatcher_note': reg.dispatcher_note or '',
            'stock_state': reg.stock_state,
            'is_waiting_goods': reg.is_waiting_goods,
            'auto_accepted': reg.auto_accepted,
            'create_date': fields.Datetime.to_string(reg.create_date) if reg.create_date else '',
        }

    # ------------------------------------------------------------------
    # Trang
    # ------------------------------------------------------------------
    @http.route('/delivery_plan', type='http', auth='user', methods=['GET'], csrf=False)
    def delivery_plan_page(self, **kwargs):
        # Không có group thì mọi lời gọi API sau đó đều ném AccessError và trang trông như
        # hỏng. Trả lời thẳng bằng một câu người dùng hiểu được.
        if not request.env.user.has_group('hlv_delivery_dispatch.group_dispatch_sale'):
            return request.make_response(
                '<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"/>'
                '<title>Kế hoạch giao hàng</title></head>'
                '<body style="font-family:system-ui;padding:40px;max-width:640px">'
                '<h2>Chưa được cấp quyền</h2>'
                '<p>Tài khoản của bạn chưa có quyền <b>Điều phối — Sale</b> nên chưa xem được '
                'kế hoạch chuyến. Báo quản trị cấp quyền này.</p>'
                '<p><a href="/sale_plan">← Về trang tình trạng đơn</a></p></body></html>',
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )
        return request.render('hlv_delivery_dispatch.dispatch_page', {})

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @http.route('/api/dispatch/config', type='json', auth='user', methods=['POST'])
    def api_config(self, **kwargs):
        warehouses = self._warehouses()
        return _ok(
            warehouses=[{'id': w.id, 'name': w.name} for w in warehouses],
            is_dispatcher=self._is_dispatcher(),
            user_name=request.env.user.name,
            has_saler_code=bool(self._user_saler_codes()),
        )

    @http.route('/api/dispatch/plan_day', type='json', auth='user', methods=['POST'])
    def api_plan_day(self, date=None, warehouse_id=None, **kwargs):
        codes = self._user_saler_codes()
        date = date or fields.Date.to_string(fields.Date.context_today(request.env.user))
        domain = [('date', '=', date), ('state', 'in', ('published', 'closed'))]
        if warehouse_id:
            domain.append(('warehouse_id', '=', int(warehouse_id)))
        plans = request.env['hlv.delivery.plan.day'].search(domain)
        out = []
        for plan in plans:
            trips = plan.trip_ids.filtered(lambda t: t.state != 'cancelled')
            out.append({
                'id': plan.id,
                'date': fields.Date.to_string(plan.date),
                'warehouse_id': plan.warehouse_id.id,
                'warehouse_name': plan.warehouse_id.name,
                'state': plan.state,
                'version': plan.version,
                'note': plan.note or '',
                'published_at': fields.Datetime.to_string(plan.published_at)
                if plan.published_at else '',
                'trips': [self._trip_payload(t, codes) for t in trips.sorted(
                    lambda t: (t.sequence, t.id))],
            })
        return _ok(plans=out, date=date)

    @http.route('/api/dispatch/trip_detail', type='json', auth='user', methods=['POST'])
    def api_trip_detail(self, trip_id=None, **kwargs):
        if not trip_id:
            return _err('Thiếu mã chuyến.')
        # Dùng search chứ không browse: record rule "chỉ thấy chuyến đã công bố" được áp
        # ngay trong search, nên chuyến nháp trả về rỗng thay vì ném AccessError.
        trip = request.env['hlv.delivery.trip'].search([('id', '=', int(trip_id))], limit=1)
        if not trip:
            return _err('Không tìm thấy chuyến, hoặc chuyến chưa được công bố.')
        return _ok(trip=self._trip_payload(trip, self._user_saler_codes(), detail=True))

    @http.route('/api/dispatch/my_orders', type='json', auth='user', methods=['POST'])
    def api_my_orders(self, search='', **kwargs):
        """Đơn của sale đang đăng nhập, để chọn khi đăng ký chuyến.

        Lọc theo đúng quy tắc "đơn của tôi" của /sale_plan, và loại sẵn đơn đã có đăng ký
        đang sống để sale không bấm nhầm hai lần.
        """
        service = request.env['hlv.delivery.planner.service']
        mine_domain = service._get_mine_only_domain()
        if mine_domain is None:
            return _ok(orders=[], note='Tài khoản chưa được khai mã sale MISA.')
        domain = list(mine_domain) + [
            ('state', 'in', ('sale', 'done')),
        ]
        search = (search or '').strip()
        if search:
            domain += ['|', ('name', 'ilike', search), ('partner_id.name', 'ilike', search)]
        orders = request.env['sale.order'].search(domain, order='date_order desc', limit=MAX_ORDER_SEARCH)
        busy = set(request.env['hlv.delivery.trip.registration'].sudo().search([
            ('sale_order_id', 'in', orders.ids),
            ('state', 'in', ('submitted', 'accepted')),
        ]).mapped('sale_order_id').ids)
        snapshots = {
            s.sale_order_id.id: s.stock_status
            for s in request.env['hlv.delivery.planner.snapshot'].sudo().search([
                ('sale_order_id', 'in', orders.ids),
            ])
        }
        return _ok(orders=[
            {
                'id': o.id,
                'name': o.name,
                'partner_name': o.partner_id.display_name,
                'point_name': o.x_delivery_point_id.name or '',
                'has_point': bool(o.x_delivery_point_id),
                'stock_state': snapshots.get(o.id, 'unknown'),
                'blocked': o.x_delivery_blocked,
                'block_reason': o.x_delivery_block_reason or '',
                'already_registered': o.id in busy,
                'trip_name': o.x_trip_id.name or '',
            }
            for o in orders
        ])

    @http.route('/api/dispatch/register', type='json', auth='user', methods=['POST'])
    def api_register(self, order_id=None, trip_id=None, desired_date=None, reason='',
                     priority='0', **kwargs):
        if not order_id:
            return _err('Chưa chọn đơn hàng.')
        order = request.env['sale.order'].browse(int(order_id))
        if not order.exists():
            return _err('Không tìm thấy đơn hàng.')
        codes = self._user_saler_codes()
        if not self._is_dispatcher() and not self._order_is_mine(order, codes):
            return _err('Đơn %s không thuộc mã sale của bạn.' % order.name)
        if not order.partner_id.x_delivery_point_id:
            return _err(
                'Khách "%s" chưa được gắn điểm giao. Báo điều phối gắn điểm trước khi đăng ký.'
                % order.partner_id.display_name
            )
        # search chứ không browse: nếu sale gửi id của chuyến chưa công bố thì record rule
        # trả về rỗng, thay vì ném AccessError khi đọc field.
        trip = request.env['hlv.delivery.trip'].search(
            [('id', '=', int(trip_id))], limit=1,
        ) if trip_id else None
        if trip_id and not trip:
            return _err('Chuyến này không còn mở hoặc chưa được công bố. Tải lại trang.')
        if trip:
            if not trip.accepts_registration:
                if trip.is_locked:
                    return _err('Chuyến "%s" đã bị khoá: %s' % (
                        trip.name, trip.lock_reason or 'điều phối khoá tay'))
                return _err('Chuyến "%s" đã quá hạn đăng ký.' % trip.name)
            desired_date = fields.Date.to_string(trip.date)
        if not desired_date:
            return _err('Chưa chọn ngày mong muốn.')
        vals = {
            'sale_order_id': order.id,
            'desired_date': desired_date,
            'trip_id': trip.id if trip else False,
            'reason': (reason or '').strip(),
            'priority': '1' if str(priority) == '1' else '0',
            'requested_by_id': request.env.user.id,
        }
        try:
            reg = request.env['hlv.delivery.trip.registration'].create(vals)
            reg.action_submit()
        except (UserError, ValidationError) as exc:
            return _err(str(exc))
        return _ok(registration=self._registration_payload(reg))

    @http.route('/api/dispatch/my_registrations', type='json', auth='user', methods=['POST'])
    def api_my_registrations(self, limit=100, **kwargs):
        regs = request.env['hlv.delivery.trip.registration'].search(
            [('requested_by_id', '=', request.env.user.id)],
            order='create_date desc', limit=int(limit or 100),
        )
        return _ok(registrations=[self._registration_payload(r) for r in regs])

    # ------------------------------------------------------------------
    # Thói quen khách — sale phụ trách tự cập nhật
    # ------------------------------------------------------------------
    def _profile_payload(self, profile, task=None):
        return {
            'profile_id': profile.id,
            'point_id': profile.point_id.id,
            'point_name': profile.point_id.name,
            'address': profile.point_id.address or '',
            'zone_id': profile.zone_id.id or profile.point_id.zone_id.id or False,
            'zone_name': (profile.zone_id or profile.point_id.zone_id).name or '',
            'partner_count': profile.point_id.partner_count,
            'default_vehicle_id': profile.default_vehicle_id.id or False,
            'procedure_before': profile.procedure_before or 'none',
            'needs_technician': profile.needs_technician,
            'service_minutes': profile.service_minutes or 0,
            'receiving_from': _hour_to_text(profile.receiving_from),
            'receiving_to': _hour_to_text(profile.receiving_to),
            'payment_method': profile.payment_method or 'none',
            'oversize_note': profile.oversize_note or '',
            'delivery_method': profile.delivery_method or 'company',
            'free_note': profile.free_note or '',
            'completeness': profile.completeness,
            'missing_fields': profile.missing_fields or '',
            'verification_state': profile.verification_state,
            'last_verified_at': fields.Datetime.to_string(profile.last_verified_at)
            if profile.last_verified_at else '',
            'review_due_date': fields.Date.to_string(profile.review_due_date)
            if profile.review_due_date else '',
            'task_id': task.id if task else False,
            'task_state': task.state if task else '',
            'task_deadline': fields.Date.to_string(task.deadline) if task and task.deadline else '',
            'task_note': (task.note or '') if task else '',
            'task_overdue': bool(task and task.is_overdue),
        }

    @http.route('/api/dispatch/my_points', type='json', auth='user', methods=['POST'])
    def api_my_points(self, **kwargs):
        """Khách sale đang phụ trách + việc đang được giao."""
        profiles = request.env['hlv.delivery.partner.profile'].search([
            ('responsible_sale_user_id', '=', request.env.user.id),
        ], order='verification_state, id')
        tasks = request.env['hlv.delivery.profile.task'].search([
            ('assigned_user_id', '=', request.env.user.id),
            ('state', 'in', ('open', 'submitted')),
        ])
        task_by_profile = {t.profile_id.id: t for t in tasks}
        zones = request.env['hlv.delivery.zone'].search([])
        vehicles = request.env['fleet.vehicle'].search([('x_dispatch_enabled', '=', True)])
        return _ok(
            profiles=[
                self._profile_payload(p, task_by_profile.get(p.id)) for p in profiles
            ],
            open_task_count=len(tasks.filtered(lambda t: t.state == 'open')),
            editable_fields=list(SALE_EDITABLE_PROFILE_FIELDS),
            zones=[{'id': z.id, 'name': z.name} for z in zones],
            vehicles=[{'id': v.id, 'name': v.display_name} for v in vehicles],
            options={
                'procedure_before': [
                    ['none', 'Không cần'],
                    ['customs', 'Khai hải quan trước (khu chế xuất)'],
                    ['register', 'Đăng ký trước khi giao'],
                ],
                'payment_method': [
                    ['none', 'Không thu tiền'], ['cod', 'Thu COD'],
                    ['transfer', 'Chuyển khoản sau'],
                ],
                'delivery_method': [
                    ['company', 'Xe công ty giao'], ['pickup', 'Khách tự ghé lấy'],
                    ['express', 'Chuyển phát nhanh'], ['grab', 'Book Grab'],
                ],
            },
        )

    @http.route('/api/dispatch/profile_save', type='json', auth='user', methods=['POST'])
    def api_profile_save(self, profile_id=None, values=None, confirm=False, **kwargs):
        if not profile_id:
            return _err('Thiếu mã bảng thói quen.')
        profile = request.env['hlv.delivery.partner.profile'].search(
            [('id', '=', int(profile_id))], limit=1,
        )
        if not profile:
            return _err('Không tìm thấy bảng thói quen.')
        if not self._is_dispatcher() and profile.responsible_sale_user_id.id != request.env.user.id:
            return _err('Bạn không phụ trách khách này.')

        values = values or {}
        vals = {}
        for name in SALE_EDITABLE_PROFILE_FIELDS:
            if name not in values:
                continue
            raw = values[name]
            if name in M2O_PROFILE_FIELDS:
                vals[name] = int(raw) if raw else False
            elif name in BOOL_PROFILE_FIELDS:
                vals[name] = bool(raw)
            elif name in INT_PROFILE_FIELDS:
                try:
                    vals[name] = int(raw or 0)
                except (TypeError, ValueError):
                    vals[name] = 0
            elif name in TIME_PROFILE_FIELDS:
                vals[name] = _parse_hour(raw)
            else:
                vals[name] = (raw or '') if isinstance(raw, str) else raw
        try:
            if vals:
                profile.write(vals)
            if confirm:
                profile.action_confirm()
                task = request.env['hlv.delivery.profile.task'].search([
                    ('profile_id', '=', profile.id),
                    ('assigned_user_id', '=', request.env.user.id),
                    ('state', '=', 'open'),
                ], limit=1)
                if task:
                    task.action_submit()
        except (UserError, ValidationError) as exc:
            return _err(str(exc))
        profile.invalidate_recordset()
        task = request.env['hlv.delivery.profile.task'].search([
            ('profile_id', '=', profile.id), ('state', 'in', ('open', 'submitted')),
        ], limit=1)
        return _ok(profile=self._profile_payload(profile, task or None))

    @http.route('/api/dispatch/cancel_registration', type='json', auth='user', methods=['POST'])
    def api_cancel_registration(self, registration_id=None, **kwargs):
        if not registration_id:
            return _err('Thiếu mã đăng ký.')
        reg = request.env['hlv.delivery.trip.registration'].browse(int(registration_id))
        if not reg.exists():
            return _err('Không tìm thấy đăng ký.')
        if reg.requested_by_id.id != request.env.user.id and not self._is_dispatcher():
            return _err('Chỉ người đăng ký mới huỷ được.')
        if reg.trip_id and reg.trip_id.state in ('departed', 'done'):
            return _err('Chuyến đã xuất phát, không huỷ được. Liên hệ điều phối.')
        try:
            reg.sudo().action_cancel()
        except (UserError, ValidationError) as exc:
            return _err(str(exc))
        return _ok(registration=self._registration_payload(reg))
