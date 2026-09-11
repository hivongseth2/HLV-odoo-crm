from odoo import api, fields, models


class HlvDeliveryTripStop(models.Model):
    """Một điểm dừng trong chuyến — có thể chứa nhiều đơn của cùng một khách.

    Đơn vị đếm của điều phối là ĐIỂM, không phải đơn: trung bình 1.48 đơn/điểm và
    28.1% số điểm có từ 2 đơn, nhưng đơn thứ hai cùng khách gần như không tốn thêm
    thời gian (trung vị 0 phút).
    """

    _name = 'hlv.delivery.trip.stop'
    _description = 'Điểm dừng trong chuyến'
    _order = 'trip_id, sequence, id'

    trip_id = fields.Many2one(
        'hlv.delivery.trip', string='Chuyến', required=True, index=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    point_id = fields.Many2one(
        'hlv.delivery.point', string='Điểm giao', required=True, index=True,
    )
    plan_day_id = fields.Many2one(related='trip_id.plan_day_id', store=True, index=True)
    date = fields.Date(related='trip_id.date', store=True, index=True)
    zone_id = fields.Many2one(related='point_id.zone_id', store=True)

    sale_order_ids = fields.Many2many(
        'sale.order', 'hlv_trip_stop_sale_order_rel', 'stop_id', 'order_id',
        string='Đơn hàng',
    )
    order_count = fields.Integer(compute='_compute_order_count', store=True)

    planned_arrival = fields.Datetime(string='Giờ tới dự kiến')
    service_minutes = fields.Integer(
        string='Đứng tại điểm (phút)', compute='_compute_service_minutes',
        store=True, readonly=False,
        help='Lấy theo thói quen khách; sửa được cho từng chuyến.',
    )
    state = fields.Selection(
        [
            ('planned', 'Dự kiến'),
            ('done', 'Đã giao'),
            ('skipped', 'Bỏ qua'),
            ('failed', 'Giao hụt'),
        ],
        default='planned', required=True, index=True,
    )
    skip_reason = fields.Char(string='Lý do bỏ/hụt')
    note = fields.Char()

    # Dùng ở giai đoạn đối chiếu kế hoạch với thực tế — để đo lại định mức thời gian
    # thay vì giữ nguyên con số đo một lần hồi 01/06→10/09.
    actual_arrival = fields.Datetime(string='Giờ tới thực tế')
    actual_depart = fields.Datetime(string='Giờ rời thực tế')

    # Không dùng related qua one2many (profile_ids) — tính tay cho rõ ràng.
    procedure_before = fields.Selection(
        [
            ('none', 'Không cần'),
            ('customs', 'Khai hải quan trước'),
            ('register', 'Đăng ký trước khi giao'),
        ],
        string='Thủ tục', compute='_compute_profile_info', store=True,
    )
    needs_technician = fields.Boolean(
        string='Cần kỹ thuật', compute='_compute_profile_info', store=True,
    )

    @api.depends('sale_order_ids')
    def _compute_order_count(self):
        for stop in self:
            stop.order_count = len(stop.sale_order_ids)

    @api.depends('point_id')
    def _compute_service_minutes(self):
        for stop in self:
            profile = stop.point_id.profile_ids[:1]
            stop.service_minutes = (profile.service_minutes if profile else 0) or 0

    @api.depends('point_id', 'point_id.profile_ids.procedure_before',
                 'point_id.profile_ids.needs_technician')
    def _compute_profile_info(self):
        for stop in self:
            profile = stop.point_id.profile_ids[:1]
            stop.procedure_before = profile.procedure_before if profile else 'none'
            stop.needs_technician = profile.needs_technician if profile else False

    def action_done(self):
        self.write({'state': 'done', 'actual_depart': fields.Datetime.now()})
        return True

    def action_skip(self):
        self.write({'state': 'skipped'})
        return True
