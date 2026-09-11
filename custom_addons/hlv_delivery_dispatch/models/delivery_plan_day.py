import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvDeliveryPlanDay(models.Model):
    """Kế hoạch giao hàng của một ngày, một kho.

    Cần lớp này chứ không publish từng chuyến lẻ: sale phải thấy một bản chốt nhất
    quán, còn điều phối cần sửa nháp thoải mái mà sale chưa thấy gì. ``version`` tăng
    mỗi lần publish lại để sale biết kế hoạch đã đổi.
    """

    _name = 'hlv.delivery.plan.day'
    _description = 'Kế hoạch giao hàng theo ngày'
    _inherit = ['mail.thread']
    _order = 'date desc, warehouse_id'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today, tracking=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, index=True, tracking=True,
        domain="[('x_dispatch_enabled', '=', True)]",
    )
    company_id = fields.Many2one(related='warehouse_id.company_id', store=True, index=True)
    state = fields.Selection(
        [('draft', 'Nháp'), ('published', 'Đã công bố'), ('closed', 'Đã đóng')],
        default='draft', required=True, index=True, tracking=True,
    )
    version = fields.Integer(default=0, readonly=True, tracking=True)
    published_by_id = fields.Many2one('res.users', string='Người công bố', readonly=True)
    published_at = fields.Datetime(string='Công bố lúc', readonly=True)
    note = fields.Text(string='Ghi chú cho sale')

    trip_ids = fields.One2many('hlv.delivery.trip', 'plan_day_id', string='Chuyến')
    trip_count = fields.Integer(compute='_compute_counts')
    stop_count = fields.Integer(compute='_compute_counts')
    order_count = fields.Integer(compute='_compute_counts')

    vehicle_assignment_ids = fields.One2many(
        'hlv.delivery.plan.vehicle', 'plan_day_id', string='Đội xe hôm nay',
    )

    over_trip_limit = fields.Boolean(compute='_compute_counts', string='Vượt số chuyến/ngày')

    _sql_constraints = [
        ('date_warehouse_uniq', 'unique(date, warehouse_id)',
         'Mỗi kho chỉ có một kế hoạch cho mỗi ngày.'),
    ]

    @api.depends('date', 'warehouse_id')
    def _compute_name(self):
        for plan in self:
            if plan.date and plan.warehouse_id:
                plan.name = 'Kế hoạch %s — %s' % (
                    fields.Date.to_string(plan.date), plan.warehouse_id.name,
                )
            else:
                plan.name = 'Kế hoạch mới'

    @api.depends('trip_ids', 'trip_ids.stop_ids', 'trip_ids.order_count',
                 'warehouse_id.x_dispatch_max_trips_per_day')
    def _compute_counts(self):
        for plan in self:
            trips = plan.trip_ids.filtered(lambda t: t.state != 'cancelled')
            plan.trip_count = len(trips)
            plan.stop_count = sum(trips.mapped('stop_count'))
            plan.order_count = sum(trips.mapped('order_count'))
            limit = plan.warehouse_id.x_dispatch_max_trips_per_day or 0
            plan.over_trip_limit = bool(limit) and plan.trip_count > limit

    @api.model
    def get_or_create(self, date, warehouse):
        """Lấy kế hoạch của ngày/kho, tạo nháp nếu chưa có."""
        plan = self.search([
            ('date', '=', date), ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if not plan:
            plan = self.create({'date': date, 'warehouse_id': warehouse.id})
        return plan

    # ------------------------------------------------------------------
    # Công bố
    # ------------------------------------------------------------------
    def action_publish(self):
        for plan in self:
            trips = plan.trip_ids.filtered(lambda t: t.state in ('draft', 'planned'))
            if not plan.trip_ids.filtered(lambda t: t.state != 'cancelled'):
                raise UserError('Kế hoạch %s chưa có chuyến nào để công bố.' % plan.name)
            trips.write({'state': 'published'})
            plan.write({
                'state': 'published',
                'version': plan.version + 1,
                'published_by_id': self.env.user.id,
                'published_at': fields.Datetime.now(),
            })
            plan._notify_published()
        return True

    def action_back_to_draft(self):
        """Rút kế hoạch về nháp — sale không còn thấy cho tới khi publish lại."""
        for plan in self:
            plan.trip_ids.filtered(lambda t: t.state == 'published').write({'state': 'planned'})
            plan.state = 'draft'
        return True

    def action_close(self):
        self.write({'state': 'closed'})
        return True

    def _notify_published(self):
        """Bắn bus + web push cho sale. Dùng lại hạ tầng của hlv_sale_delivery_planning."""
        self.ensure_one()
        payload = {
            'plan_day_id': self.id,
            'date': fields.Date.to_string(self.date),
            'warehouse_id': self.warehouse_id.id,
            'warehouse_name': self.warehouse_id.name,
            'version': self.version,
            'trip_count': self.trip_count,
            'stop_count': self.stop_count,
        }
        bus = self.env['bus.bus'].sudo()
        bus._sendone('sale_plan_public_channel', 'dispatch_trip_published', payload)
        bus._sendone('delivery_planner_channel', 'dispatch_trip_published', payload)
        self._push_webpush_to_sales(payload)

    def _push_webpush_to_sales(self, payload):
        """Push cho các sale có đơn nằm trong kế hoạch này."""
        self.ensure_one()
        user_ids = set()
        for trip in self.trip_ids:
            user_ids |= set(trip._interested_sale_user_ids())
        if not user_ids:
            return 0
        try:
            from odoo.addons.hlv_sale_delivery_planning.controllers.sale_plan_controller import (
                _send_sale_plan_webpush,
            )
        except Exception:
            _logger.warning('Không import được _send_sale_plan_webpush — bỏ qua web push')
            return 0
        subs = self.env['hlv.sale.plan.web.push.subscription'].sudo().search([
            ('active', '=', True), ('user_id', 'in', list(user_ids)),
        ])
        return _send_sale_plan_webpush(self.env, subs, {
            'type': 'dispatch_trip_published',
            'title': 'Kế hoạch giao ngày %s đã công bố' % fields.Date.to_string(self.date),
            'body': '%s chuyến · %s điểm — %s' % (
                payload['trip_count'], payload['stop_count'], self.warehouse_id.name,
            ),
            'url': '/delivery_plan?date=%s' % fields.Date.to_string(self.date),
            'tag': 'dispatch-plan-%s-%s' % (self.id, self.version),
        })

    def action_open_trips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Chuyến — %s' % self.name,
            'res_model': 'hlv.delivery.trip',
            'view_mode': 'list,form',
            'domain': [('plan_day_id', '=', self.id)],
            'context': {'default_plan_day_id': self.id},
        }


class HlvDeliveryPlanVehicle(models.Model):
    """Đội xe của một ngày.

    Xe KHÔNG cố định theo tuyến — đổi theo ngày, nên việc phân công nằm ở đây chứ
    không nằm trên cụm tuyến. Đây cũng là nơi thấy được ràng buộc "tài xế bỏ Kim Long
    sang lái xe tải ⇒ tối đa 4 chuyến/ngày".
    """

    _name = 'hlv.delivery.plan.vehicle'
    _description = 'Phân công xe theo ngày'
    _order = 'plan_day_id, id'

    plan_day_id = fields.Many2one(
        'hlv.delivery.plan.day', required=True, index=True, ondelete='cascade',
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe', required=True,
        domain="[('x_dispatch_enabled', '=', True)]",
    )
    driver_user_id = fields.Many2one('res.users', string='Tài xế')
    driver_display_name = fields.Char(
        related='driver_user_id.dispatch_driver_name', string='Tên tài xế',
    )
    available = fields.Boolean(string='Chạy hôm nay', default=True)
    note = fields.Char()
    vehicle_warning = fields.Char(compute='_compute_vehicle_warning')

    @api.depends('vehicle_id', 'vehicle_id.state_id')
    def _compute_vehicle_warning(self):
        for row in self:
            state_name = (row.vehicle_id.state_id.name or '').lower()
            if state_name and any(k in state_name for k in ('bảo dưỡng', 'sửa', 'repair', 'maintenance')):
                row.vehicle_warning = 'Xe đang ở trạng thái "%s"' % row.vehicle_id.state_id.name
            else:
                row.vehicle_warning = False
