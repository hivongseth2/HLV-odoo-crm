import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km
from odoo.addons.hlv_vtracking.tools.vtracking_route import (
    estimate_route, format_minutes, route_params,
)
from odoo.addons.hlv_vtracking.services.plan_payload import SESSION_LABELS

_logger = logging.getLogger(__name__)



class HlvVtrackingPlan(models.Model):
    """Kế hoạch giao hàng của MỘT xe trong MỘT buổi của MỘT ngày.

    Đơn vị là (xe, ngày, buổi) chứ không phải (ngày) chung: người điều phối làm việc theo
    đầu xe — "sáng mai xe 60D-00750 chạy những phiếu nào". Kế hoạch cả ngày là một buổi
    đặc biệt (``full_day``) chứ không phải một cấp riêng, để không phải hỏi "kế hoạch ngày
    và kế hoạch buổi cái nào đè cái nào".

    Đây là BẢN DỰ THẢO. Số liệu thực tế (nhận đơn nào, giao lúc mấy giờ) sẽ do
    ``hlv_barcode_shipper`` cung cấp ở bước sau — các ô ``actual_*`` đã khai sẵn và đang
    để trống có chủ ý.
    """

    _name = 'hlv.vtracking.plan'
    _description = 'Kế hoạch giao hàng'
    _inherit = ['mail.thread']
    _order = 'date desc, session, vehicle_id'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        required=True, index=True, tracking=True, default=fields.Date.context_today,
    )
    session = fields.Selection(
        [(key, label) for key, label in SESSION_LABELS.items()],
        string='Buổi', default='morning', required=True, index=True, tracking=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe', required=True, index=True, tracking=True,
        domain="[('vtracking_enabled', '=', True)]",
    )
    driver_id = fields.Many2one(
        related='vehicle_id.driver_id', string='Tài xế theo Đội xe', store=True, readonly=True,
    )
    start_place_id = fields.Many2one(
        'hlv.vtracking.place', string='Xuất phát từ', tracking=True,
        domain="[('has_coords', '=', True)]",
        help='Thường là kho. Quãng đường tính từ đây tới điểm đầu tiên rồi lần lượt qua '
             'các điểm; để trống thì chỉ tính từ điểm giao đầu tiên trở đi.',
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('confirmed', 'Đã chốt'),
            ('done', 'Xong'),
            ('cancelled', 'Huỷ'),
        ],
        default='draft', required=True, index=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company,
    )
    note = fields.Text()

    line_ids = fields.One2many('hlv.vtracking.plan.line', 'plan_id', string='Phiếu giao')
    line_count = fields.Integer(compute='_compute_totals', store=True, string='Số phiếu')
    amount_total = fields.Monetary(
        compute='_compute_totals', store=True, string='Tổng tiền',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    # --- Quãng đường và thời gian -------------------------------------------
    distance_km = fields.Float(
        compute='_compute_route', store=True, string='Quãng đường (km)', digits=(10, 1),
        help='Đường CHIM BAY nối các điểm theo thứ tự ghé, nhân hệ số đường bộ. Không '
             'phải quãng đường Google Maps — dùng để so các phương án với nhau, không '
             'dùng để hứa với khách.',
    )
    drive_minutes = fields.Integer(compute='_compute_route', store=True, string='Thời gian chạy (phút)')
    service_minutes = fields.Integer(compute='_compute_route', store=True, string='Thời gian giao (phút)')
    total_minutes = fields.Integer(compute='_compute_route', store=True, string='Tổng thời gian (phút)')
    duration_display = fields.Char(compute='_compute_route', store=True, string='Dự kiến')
    missing_coords_count = fields.Integer(
        compute='_compute_route', store=True, string='Điểm thiếu toạ độ',
        help='Phiếu chưa tra được toạ độ thì không tính được vào quãng đường — con số km '
             'đang thiếu phần của chúng.',
    )

    # --- Thực tế (chờ hlv_barcode_shipper) ----------------------------------
    # Khai sẵn để màn hình và API có chỗ đọc ngay từ bây giờ; điền vào là việc của bước
    # nối với module shipper. Đừng suy số thực tế từ kế hoạch — đó là hai nguồn khác nhau,
    # trộn vào nhau thì không còn đối chiếu được nữa.
    actual_line_count = fields.Integer(string='Số phiếu đã giao', readonly=True, copy=False)
    actual_amount_total = fields.Monetary(
        string='Tiền đã giao', readonly=True, copy=False, currency_field='currency_id',
    )
    actual_distance_km = fields.Float(
        string='Km thực chạy', readonly=True, copy=False, digits=(10, 1),
        help='Sẽ lấy từ lịch sử GPS của xe trong khung giờ của kế hoạch.',
    )
    actual_start_at = fields.Datetime(string='Xuất phát thực tế', readonly=True, copy=False)
    actual_end_at = fields.Datetime(string='Về thực tế', readonly=True, copy=False)
    has_actual_data = fields.Boolean(compute='_compute_has_actual_data')

    _sql_constraints = [
        ('vehicle_date_session_uniq', 'unique(vehicle_id, date, session, company_id)',
         'Xe này đã có kế hoạch cho buổi đó rồi. Mở kế hoạch có sẵn ra sửa thay vì tạo mới.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('vehicle_id', 'date', 'session')
    def _compute_name(self):
        for plan in self:
            parts = [
                plan.vehicle_id.license_plate or plan.vehicle_id.display_name or 'Chưa chọn xe',
                SESSION_LABELS.get(plan.session, ''),
                fields.Date.to_string(plan.date) if plan.date else '',
            ]
            plan.name = ' · '.join(part for part in parts if part)

    @api.depends('line_ids', 'line_ids.amount')
    def _compute_totals(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)
            plan.amount_total = sum(plan.line_ids.mapped('amount'))

    @api.depends('line_ids', 'line_ids.sequence', 'line_ids.latitude', 'line_ids.longitude',
                 'start_place_id', 'company_id.vtracking_avg_speed_kmh',
                 'company_id.vtracking_minutes_per_stop', 'company_id.vtracking_road_factor')
    def _compute_route(self):
        """Quãng đường và thời gian dự kiến của cả kế hoạch.

        Phép tính nằm ở ``tools/vtracking_route`` — API cho AI và màn hình này phải ra
        cùng một con số cho cùng một chuyến.
        """
        for plan in self:
            estimate = estimate_route(plan._route_start(), plan._route_stops(), plan._route_params())
            plan.missing_coords_count = estimate['missing_coords_count']
            plan.distance_km = estimate['distance_km']
            plan.drive_minutes = estimate['drive_minutes']
            plan.service_minutes = estimate['service_minutes']
            plan.total_minutes = estimate['total_minutes']
            plan.duration_display = format_minutes(estimate['total_minutes'])

    def _ordered_lines(self):
        """Các dòng theo đúng thứ tự ghé."""
        self.ensure_one()
        return self.line_ids.sorted(lambda line: (line.sequence, line.id))

    def _route_start(self):
        """Toạ độ điểm xuất phát, hoặc None nếu chưa chọn / chưa có toạ độ."""
        self.ensure_one()
        place = self.start_place_id
        return (place.latitude, place.longitude) if place.has_coords else None

    def _route_stops(self):
        """Toạ độ từng điểm theo thứ tự ghé; None cho điểm chưa tra được toạ độ."""
        self.ensure_one()
        return [
            (line.latitude, line.longitude) if line.latitude and line.longitude else None
            for line in self._ordered_lines()
        ]

    def _route_params(self):
        """Định mức tính lộ trình của công ty sở hữu kế hoạch."""
        self.ensure_one()
        company = self.company_id
        return route_params(
            company.vtracking_avg_speed_kmh,
            company.vtracking_minutes_per_stop,
            company.vtracking_road_factor,
        )

    @api.depends('actual_line_count', 'actual_start_at')
    def _compute_has_actual_data(self):
        for plan in self:
            plan.has_actual_data = bool(plan.actual_line_count or plan.actual_start_at)

    @api.constrains('line_ids')
    def _check_vehicle_enabled(self):
        for plan in self:
            if plan.line_ids and not plan.vehicle_id.vtracking_enabled:
                raise ValidationError(
                    'Xe %s chưa bật "Theo dõi vTracking" nên không đối chiếu được với GPS. '
                    'Bật cờ đó ở V-Tracking > Xe theo dõi trước khi xếp phiếu.'
                    % plan.vehicle_id.display_name
                )

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_confirm(self):
        for plan in self:
            if not plan.line_ids:
                raise UserError('Kế hoạch "%s" chưa có phiếu nào.' % plan.name)
        self.write({'state': 'confirmed'})
        return True

    def action_back_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_done(self):
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_refresh_lines(self):
        """Đọc lại địa chỉ, tiền và toạ độ từ phiếu.

        Cần nút này vì dòng kế hoạch chụp lại số liệu lúc xếp: phiếu sửa tiền hay sửa địa
        chỉ sau đó thì kế hoạch không tự biết. Chụp lại chứ không đọc thẳng để con số trên
        kế hoạch đã chốt không đổi sau lưng người điều phối.
        """
        self.mapped('line_ids')._sync_from_source()
        return True

    def action_add_documents(self):
        """Mở hộp thoại xếp thêm phiếu/đơn vào chính kế hoạch này."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Xếp thêm vào %s' % self.name,
            'res_model': 'hlv.vtracking.plan.add.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id, 'default_mode': 'existing'},
        }

    def action_resequence_by_distance(self):
        """Sắp thứ tự ghé theo kiểu "đi tới điểm gần nhất chưa ghé".

        Không phải lời giải tối ưu cho bài toán người giao hàng, chỉ là điểm khởi đầu đỡ
        tệ hơn thứ tự nhập tay. Người điều phối vẫn kéo tay lại được.
        """
        for plan in self:
            remaining = list(plan.line_ids.filtered(lambda line: line.latitude and line.longitude))
            if not remaining:
                continue
            if plan.start_place_id and plan.start_place_id.has_coords:
                current = (plan.start_place_id.latitude, plan.start_place_id.longitude)
            else:
                first = remaining.pop(0)
                first.sequence = 10
                current = (first.latitude, first.longitude)
            step = 20
            while remaining:
                nearest = min(
                    remaining,
                    key=lambda line: haversine_km(current, (line.latitude, line.longitude)) or 9e9,
                )
                nearest.sequence = step
                current = (nearest.latitude, nearest.longitude)
                remaining.remove(nearest)
                step += 10
            # Phiếu thiếu toạ độ dồn xuống cuối: không biết ở đâu thì không xếp vào giữa
            # tuyến được, để cuối cho người điều phối tự quyết.
            for line in plan.line_ids.filtered(lambda l: not (l.latitude and l.longitude)):
                line.sequence = step
                step += 10
        return True

    def action_open_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Phiếu trong %s' % self.name,
            'res_model': 'hlv.vtracking.plan.line',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }
