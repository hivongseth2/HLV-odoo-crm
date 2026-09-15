from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import pickup_maps, pickup_metrics, pickup_qr

PARAM_MAX_OPTIMIZE = 'hlv_purchase_pickup.max_optimize_per_run'
DEFAULT_MAX_OPTIMIZE = 5


class HlvPickupRun(models.Model):
    """Một chuyến đi nhận hàng: một người, một ngày, một danh sách đơn mua.

    Chuyến là đơn vị đo. Mọi con số của module — di chuyển bao lâu, đứng ở nhà cung cấp bao
    lâu, chết bao nhiêu thời gian — đều suy ra từ bốn mốc bấm tay trong chuyến này, không
    có field nào cho gõ tay số phút.
    """

    _name = 'hlv.pickup.run'
    _description = 'Chuyến đi nhận hàng'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(required=True, copy=False, default='Mới', readonly=True)
    date = fields.Date(
        string='Ngày đi', required=True, index=True, tracking=True,
        default=fields.Date.context_today,
    )
    driver_user_id = fields.Many2one(
        'res.users', string='Người đi nhận', index=True, tracking=True,
        help='Trang /pickup chỉ hiện chuyến của chính người đang đăng nhập.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất phát', required=True, tracking=True,
        default=lambda self: self.env['stock.warehouse'].search([], limit=1),
        help='Nơi bắt đầu chuyến — dùng làm điểm gốc khi tính đường đi và giờ dự kiến.',
    )
    company_id = fields.Many2one(related='warehouse_id.company_id', store=True, index=True)
    session = fields.Selection(
        [
            ('morning', 'Sáng'),
            ('afternoon', 'Chiều'),
            ('full', 'Cả ngày'),
        ],
        string='Ca', default='morning', required=True, index=True, tracking=True,
        help='Một ngày thường có chuyến sáng và chuyến chiều. Không có trường này thì ở màn '
             'hình chọn chuyến, hai chuyến cùng ngày chỉ khác nhau mỗi con số cuối mã chuyến '
             '— người đi nhận rất dễ mở nhầm.',
    )
    vehicle_note = fields.Char(
        string='Xe', help='Ghi tay biển số hoặc loại xe. Chuyến đi nhận thường mượn xe nên '
                          'không gắn cứng vào đội xe.',
    )
    note = fields.Text()

    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('assigned', 'Đã giao'),
            ('departed', 'Đang đi'),
            ('done', 'Hoàn tất'),
            ('cancelled', 'Huỷ'),
        ],
        default='draft', required=True, index=True, tracking=True,
    )

    stop_ids = fields.One2many('hlv.pickup.stop', 'run_id', string='Điểm nhận')
    line_ids = fields.One2many('hlv.pickup.line', 'run_id', string='Đơn mua hàng')
    stop_count = fields.Integer(compute='_compute_counts', store=True, string='Số điểm')
    line_count = fields.Integer(compute='_compute_counts', store=True, string='Số đơn')
    received_line_count = fields.Integer(compute='_compute_counts', store=True, string='Đã nhận')
    done_stop_count = fields.Integer(compute='_compute_counts', store=True, string='Điểm đã xong')

    # --- Mốc thực tế --------------------------------------------------------
    depart_at = fields.Datetime(string='Xuất phát lúc', readonly=True, copy=False, tracking=True)
    returned_at = fields.Datetime(string='Về kho lúc', readonly=True, copy=False)
    total_travel_minutes = fields.Integer(
        string='Tổng di chuyển (phút)', compute='_compute_totals', store=True,
    )
    total_service_minutes = fields.Integer(
        string='Tổng nhận hàng (phút)', compute='_compute_totals', store=True,
    )
    total_minutes = fields.Integer(
        string='Tổng chuyến (phút)', compute='_compute_totals', store=True,
    )
    idle_minutes = fields.Integer(
        string='Thời gian chết (phút)', compute='_compute_totals', store=True,
        help='Tổng chuyến trừ đi di chuyển và nhận hàng: ăn trưa, đổ xăng, chờ không rõ lý do.',
    )

    # --- Dự kiến từ Google --------------------------------------------------
    planned_depart_at = fields.Datetime(
        string='Dự kiến xuất phát',
        help='Mốc để tính giờ dự kiến tới từng điểm. Không phải mốc đo — mốc đo là "Xuất '
             'phát lúc" do người đi nhận bấm.',
    )
    planned_total_minutes = fields.Integer(string='Dự kiến cả chuyến (phút)', readonly=True)
    planned_km = fields.Float(string='Dự kiến (km)', digits=(8, 1), readonly=True)
    point_no_coords_count = fields.Integer(
        string='Điểm thiếu toạ độ', compute='_compute_point_no_coords_count',
        help='Điểm thiếu toạ độ thì không hiện trên bản đồ và không tính được thứ tự đi.',
    )
    optimize_count = fields.Integer(
        string='Số lần tối ưu', readonly=True, copy=False,
        help='Mỗi lần bấm là một lượt gọi Google có tính tiền. Có trần để một chuyến bị bấm '
             'nghịch không đốt hết hạn mức của cả tháng.',
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('stop_ids', 'stop_ids.state', 'line_ids', 'line_ids.state')
    def _compute_counts(self):
        for run in self:
            run.stop_count = len(run.stop_ids)
            run.line_count = len(run.line_ids)
            run.done_stop_count = len(run.stop_ids.filtered(
                lambda s: s.state in ('done', 'skipped', 'failed')
            ))
            run.received_line_count = len(run.line_ids.filtered(
                lambda l: l.state in ('received', 'partial')
            ))

    @api.depends('stop_ids.point_id.has_coords')
    def _compute_point_no_coords_count(self):
        for run in self:
            run.point_no_coords_count = len(
                run.stop_ids.mapped('point_id').filtered(lambda p: not p.has_coords)
            )

    @api.depends('depart_at', 'returned_at', 'stop_ids.arrived_at', 'stop_ids.done_at',
                 'stop_ids.sequence')
    def _compute_totals(self):
        for run in self:
            timings = pickup_metrics.compute_run_timings(
                run.depart_at, run.returned_at,
                [{
                    'key': stop.id,
                    'sequence': stop.sequence,
                    'arrived_at': stop.arrived_at,
                    'done_at': stop.done_at,
                } for stop in run.stop_ids],
            )
            run.total_travel_minutes = timings['total_travel_minutes']
            run.total_service_minutes = timings['total_service_minutes']
            run.total_minutes = timings['total_minutes'] or 0
            run.idle_minutes = timings['idle_minutes'] or 0

    # ------------------------------------------------------------------
    # Tạo
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get('name') or values['name'] == 'Mới':
                values['name'] = self.env['ir.sequence'].next_by_code('hlv.pickup.run') or 'Mới'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Xếp đơn vào chuyến
    # ------------------------------------------------------------------
    def add_purchase_orders(self, orders):
        """Xếp các đơn mua hàng vào chuyến, tự gom theo nhà cung cấp.

        Gom theo ĐIỂM chứ không theo đơn: ba đơn của cùng một nhà máy chỉ sinh ra một điểm
        dừng. Đơn đã có trong chuyến thì bỏ qua, không tạo dòng trùng.
        Trả về số dòng đơn đã thêm.
        """
        self.ensure_one()
        if self.state in ('done', 'cancelled'):
            raise UserError('Chuyến "%s" đã kết thúc nên không thêm đơn được.' % self.name)

        Point = self.env['hlv.pickup.point']
        Line = self.env['hlv.pickup.line']
        existing = set(self.line_ids.mapped('purchase_order_id').ids)
        stop_by_point = {stop.point_id.id: stop for stop in self.stop_ids}
        added = 0

        for order in orders:
            if order.id in existing:
                continue
            point = Point.find_or_create_for_partner(order.partner_id)
            stop = stop_by_point.get(point.id)
            if not stop:
                stop = self.env['hlv.pickup.stop'].create({
                    'run_id': self.id,
                    'point_id': point.id,
                    'partner_id': order.partner_id.id,
                    'sequence': (len(stop_by_point) + 1) * 10,
                })
                stop_by_point[point.id] = stop
            Line.create(dict(Line.snapshot_values(order), stop_id=stop.id))
            added += 1
        return added

    def action_remove_empty_stops(self):
        """Xoá các điểm không còn đơn nào — sau khi quản lý gỡ bớt đơn khỏi chuyến."""
        for run in self:
            run.stop_ids.filtered(
                lambda s: not s.line_ids and s.state == 'pending'
            ).unlink()
        return True

    # ------------------------------------------------------------------
    # Tối ưu đường đi
    # ------------------------------------------------------------------
    def action_optimize_route(self):
        """Hỏi Google thứ tự đi ngắn nhất rồi ghi lại thứ tự kế hoạch và giờ dự kiến."""
        return self._fetch_route(optimize=True)

    def action_refresh_eta(self):
        """Giữ nguyên thứ tự đang có, chỉ lấy lại thời gian từng chặng và giờ dự kiến tới.

        Dùng khi quản lý đã tự sắp tay: tối ưu lại sẽ đảo mất thứ tự vừa sắp.
        """
        return self._fetch_route(optimize=False)

    def _fetch_route(self, optimize):
        """Gọi Google cho các điểm CHƯA TỚI của chuyến rồi ghi kết quả.

        Chỉ đụng tới điểm chưa tới. Điểm đã đi rồi mà bị đảo chỗ thì thứ tự kế hoạch không
        còn khớp với thực tế và mọi so sánh kế hoạch ↔ thực tế thành vô nghĩa.
        """
        self.ensure_one()
        limit = self._max_optimize()
        if self.optimize_count >= limit:
            raise UserError(
                'Chuyến này đã gọi Google %d lần (trần %d). Mỗi lần là một lượt có tính phí '
                '— sửa thứ tự tay nếu cần đổi tiếp.' % (self.optimize_count, limit)
            )

        origin = self._origin_place()
        pending = self.stop_ids.filtered(lambda s: s.state == 'pending').sorted(
            lambda s: (s.sequence, s.id)
        )
        if not pending:
            raise UserError('Chuyến không còn điểm nào chưa tới.')
        if optimize and len(pending) < 2:
            raise UserError('Phải còn ít nhất 2 điểm chưa tới thì mới có gì để sắp lại.')

        missing = pending.filtered(lambda s: not pickup_maps.place_of_point(s.point_id))
        if missing:
            raise UserError(
                'Các điểm sau chưa có toạ độ lẫn địa chỉ nên không tính đường được: %s'
                % ', '.join(missing.mapped('point_id.name'))
            )

        result = pickup_maps.route_legs(
            self.env, origin, [pickup_maps.place_of_point(s.point_id) for s in pending],
            optimize=optimize,
        )
        ordered = [pending[index] for index in result['order']]
        self._apply_route(ordered, result['legs'])
        self.write({
            'optimize_count': self.optimize_count + 1,
            'planned_total_minutes': result['total_minutes'],
            'planned_km': result['total_km'],
        })
        return True

    def _apply_route(self, ordered_stops, legs):
        """Ghi thứ tự, thời gian dự kiến từng chặng và giờ dự kiến tới từng điểm.

        legs[0] là chặng từ kho tới điểm đầu, legs[i] là chặng từ điểm i-1 tới điểm i. Chặng
        cuối (quay về kho) có trong legs nhưng không gắn vào điểm nào.
        """
        base = self.planned_depart_at or self.depart_at
        running = base
        # Điểm đã đi giữ nguyên thứ tự đầu danh sách để số thứ tự không nhảy lung tung.
        offset = len(self.stop_ids) - len(ordered_stops)

        for index, stop in enumerate(ordered_stops):
            leg = legs[index] if index < len(legs) else None
            values = {'sequence': (offset + index + 1) * 10}
            if leg:
                values['planned_travel_minutes'] = leg['minutes']
                values['planned_km'] = leg['km']
                if running:
                    running = running + timedelta(
                        minutes=leg['minutes'] + (stop.point_id.median_service_minutes or 0)
                    )
                    # Giờ dự kiến TỚI điểm = giờ rời điểm trước + thời gian chặng. Phải trừ
                    # lại phần đứng tại chính điểm này vừa cộng ở trên.
                    values['planned_arrival'] = running - timedelta(
                        minutes=stop.point_id.median_service_minutes or 0
                    )
            stop.write(values)

    def _origin_place(self):
        partner = self.warehouse_id.partner_id
        place = pickup_maps.place_of_partner(partner)
        if not place:
            raise UserError(
                'Kho "%s" chưa có toạ độ lẫn địa chỉ nên không biết chuyến bắt đầu từ đâu.'
                % self.warehouse_id.name
            )
        return place

    @api.model
    def _max_optimize(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_MAX_OPTIMIZE)
        try:
            return int(raw) if raw else DEFAULT_MAX_OPTIMIZE
        except (TypeError, ValueError):
            return DEFAULT_MAX_OPTIMIZE

    # ------------------------------------------------------------------
    # Vòng đời
    # ------------------------------------------------------------------
    def action_assign(self):
        for run in self:
            if not run.driver_user_id:
                raise UserError('Chọn người đi nhận trước khi giao chuyến "%s".' % run.name)
            if not run.stop_ids:
                raise UserError('Chuyến "%s" chưa có điểm nào.' % run.name)
            run.write({'state': 'assigned'})
        return True

    def action_back_to_draft(self):
        self.filtered(lambda r: r.state in ('assigned', 'cancelled')).write({'state': 'draft'})
        return True

    def mark_departed(self, when=None):
        """Người đi nhận bấm "Xuất phát". Bấm lại lần hai không dời mốc."""
        self.ensure_one()
        if self.state in ('done', 'cancelled'):
            raise UserError('Chuyến "%s" đã kết thúc.' % self.name)
        if self.depart_at:
            return False
        self.write({'depart_at': when or fields.Datetime.now(), 'state': 'departed'})
        return True

    def mark_finished(self, when=None):
        """Kết thúc chuyến. Điểm chưa tới bị đánh dấu bỏ qua kèm lý do mặc định.

        Không im lặng để lại điểm ở trạng thái "chưa tới": chuyến đã đóng mà điểm vẫn treo
        thì báo cáo không biết nên đếm điểm đó vào đâu.
        """
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError('Chuyến "%s" đã huỷ.' % self.name)
        when = when or fields.Datetime.now()
        for stop in self.stop_ids.filtered(lambda s: s.state == 'pending'):
            stop.mark_skipped('Chuyến kết thúc khi chưa tới điểm này.')
        self.write({'returned_at': when, 'state': 'done'})
        return True

    def action_depart(self):
        for run in self:
            run.mark_departed()
        return True

    def action_finish(self):
        for run in self:
            run.mark_finished()
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    # ------------------------------------------------------------------
    # Toạ độ của các điểm trong chuyến
    # ------------------------------------------------------------------
    def action_geocode_points(self):
        """Tra toạ độ cho các điểm trong chuyến còn thiếu.

        Không ném UserError giữa chừng: UserError làm Odoo rollback cả transaction, nên các
        điểm đã tra xong trước đó sẽ mất trắng. Gặp lỗi thì dừng vòng lặp và báo bằng thông
        báo, giữ lại phần đã làm được.
        """
        self.ensure_one()
        points = self.stop_ids.mapped('point_id').filtered(lambda p: not p.has_coords)
        if not points:
            return self._notify('Mọi điểm trong chuyến đã có toạ độ.', 'success')

        no_address = points.filtered(lambda p: not p.address)
        done = 0
        error_message = ''
        for point in points - no_address:
            try:
                point._geocode_once()
                done += 1
            except UserError as error:
                error_message = str(error)
                break

        parts = ['Đã tra %d điểm.' % done] if done else ['Chưa tra được điểm nào.']
        if done:
            parts.append('Toạ độ đang ở trạng thái CHỜ DUYỆT — vào Điểm nhận hàng để duyệt '
                         'trước khi dùng.')
        if no_address:
            parts.append('Chưa khai địa chỉ nên không tra được: %s.'
                         % ', '.join(no_address.mapped('name')))
        if error_message:
            parts.append(error_message)
        return self._notify(' '.join(parts), 'warning' if (no_address or error_message) else 'success')

    def _notify(self, message, kind):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Toạ độ điểm nhận',
                'message': message,
                'type': kind,
                'sticky': kind != 'success',
            },
        }

    # ------------------------------------------------------------------
    # In lịch + mã QR
    # ------------------------------------------------------------------
    def pickup_page_url(self):
        """Địa chỉ mở thẳng chuyến này trên trang /pickup. Dùng trong mã QR của tờ lịch in."""
        self.ensure_one()
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return pickup_qr.pickup_page_url(base, self.id)

    def qr_image_src(self):
        """Đường dẫn ảnh QR để nhúng vào báo cáo. Gọi thẳng từ QWeb nên không đặt tên _riêng."""
        self.ensure_one()
        return pickup_qr.qr_image_src(self.pickup_page_url())

    def action_open_stops(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điểm nhận — %s' % self.name,
            'res_model': 'hlv.pickup.stop',
            'view_mode': 'list,form',
            'domain': [('run_id', '=', self.id)],
        }
