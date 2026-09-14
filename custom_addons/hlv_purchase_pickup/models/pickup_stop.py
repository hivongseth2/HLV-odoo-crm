from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_m

from ..services import pickup_metrics

PARAM_GPS_FAR_METERS = 'hlv_purchase_pickup.gps_far_meters'
DEFAULT_GPS_FAR_METERS = 500


class HlvPickupStop(models.Model):
    """Một lần ghé nhà cung cấp trong chuyến — chứa mọi đơn nhận tại đó.

    Đơn vị đếm là ĐIỂM chứ không phải đơn: tới một nhà cung cấp lấy ba đơn cùng lúc tốn
    gần đúng bằng lấy một đơn. Đo theo đơn sẽ ra định mức "mỗi đơn 7 phút" hoàn toàn vô
    nghĩa khi đem đi dự kiến chuyến sau.
    """

    _name = 'hlv.pickup.stop'
    _description = 'Điểm nhận hàng trong chuyến'
    _order = 'run_id, sequence, id'

    run_id = fields.Many2one(
        'hlv.pickup.run', string='Chuyến', required=True, index=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Thứ tự kế hoạch', default=10)
    point_id = fields.Many2one(
        'hlv.pickup.point', string='Điểm nhận', required=True, index=True,
    )
    partner_id = fields.Many2one('res.partner', string='Nhà cung cấp', index=True)
    date = fields.Date(related='run_id.date', store=True, index=True)
    driver_user_id = fields.Many2one(related='run_id.driver_user_id', store=True, index=True)

    line_ids = fields.One2many('hlv.pickup.line', 'stop_id', string='Đơn nhận tại đây')
    line_count = fields.Integer(compute='_compute_line_stats', store=True, string='Số đơn')
    pending_line_count = fields.Integer(compute='_compute_line_stats', string='Đơn chưa xử lý')

    state = fields.Selection(
        [
            ('pending', 'Chưa tới'),
            ('arrived', 'Đang ở đây'),
            ('done', 'Đã nhận xong'),
            ('skipped', 'Bỏ qua'),
            ('failed', 'Không nhận được'),
        ],
        default='pending', required=True, index=True,
    )
    skip_reason = fields.Char(string='Lý do bỏ/hụt')
    note = fields.Char(string='Ghi chú')

    # --- Mốc thực tế --------------------------------------------------------
    arrived_at = fields.Datetime(string='Tới lúc', readonly=True, copy=False)
    done_at = fields.Datetime(string='Rời lúc', readonly=True, copy=False)
    is_estimated = fields.Boolean(
        string='Mốc suy ra', readonly=True, copy=False,
        help='Người đi nhận quên bấm một mốc nên hệ thống phải suy. Các dòng này bị LOẠI '
             'khỏi thống kê định mức: một điểm quên bấm sẽ kéo trung vị xuống và làm mọi '
             'dự kiến sau đó ngắn hơn thực tế.',
    )

    actual_sequence = fields.Integer(
        string='Thứ tự đi thật', compute='_compute_timings', store=True,
        help='Người đi nhận đảo điểm là chuyện thường. Mọi phép trừ thời gian đều theo thứ '
             'tự này, theo thứ tự kế hoạch sẽ ra số phút âm.',
    )
    travel_minutes = fields.Integer(
        string='Di chuyển (phút)', compute='_compute_timings', store=True,
        help='Từ lúc rời điểm trước (hoặc lúc xuất phát) tới lúc bấm đã tới điểm này.',
    )
    service_minutes = fields.Integer(
        string='Nhận hàng (phút)', compute='_compute_timings', store=True,
        help='Từ lúc bấm đã tới tới lúc bấm đã nhận xong.',
    )
    chain_broken = fields.Boolean(
        string='Mốc gãy', compute='_compute_timings', store=True,
        help='Không tính được thời gian di chuyển: thiếu mốc gốc, hoặc mốc bấm ngược thứ tự.',
    )

    # --- Dự kiến từ Google --------------------------------------------------
    planned_travel_minutes = fields.Integer(string='Dự kiến đi (phút)', readonly=True)
    planned_km = fields.Float(string='Dự kiến (km)', digits=(8, 1), readonly=True)
    planned_arrival = fields.Datetime(string='Dự kiến tới', readonly=True)
    travel_gap_minutes = fields.Integer(
        string='Lệch dự kiến (phút)', compute='_compute_travel_gap', store=True,
        help='Thực tế trừ dự kiến. Dương là đi lâu hơn Google đoán — số này tích lại cho '
             'biết Google sai bao nhiêu ở khu công nghiệp để hiệu chỉnh giờ dự kiến.',
    )

    # --- GPS lúc bấm "đã tới" -----------------------------------------------
    gps_lat = fields.Float(string='GPS vĩ độ', digits=(10, 7), readonly=True)
    gps_lng = fields.Float(string='GPS kinh độ', digits=(10, 7), readonly=True)
    gps_accuracy_m = fields.Integer(string='Sai số GPS (m)', readonly=True)
    gps_distance_m = fields.Integer(
        string='Lệch điểm (m)', compute='_compute_gps_distance', store=True,
    )
    gps_far = fields.Boolean(
        string='Bấm ở xa điểm', compute='_compute_gps_distance', store=True,
        help='Chỉ là CẢNH BÁO để quản lý xem lại, không chặn thao tác. GPS trong nhà xưởng '
             'lệch vài trăm mét là chuyện bình thường.',
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('line_ids', 'line_ids.state')
    def _compute_line_stats(self):
        for stop in self:
            stop.line_count = len(stop.line_ids)
            stop.pending_line_count = len(stop.line_ids.filtered(lambda l: l.state == 'pending'))

    @api.depends('arrived_at', 'done_at', 'sequence', 'run_id.depart_at', 'run_id.returned_at',
                 'run_id.stop_ids.arrived_at', 'run_id.stop_ids.done_at',
                 'run_id.stop_ids.sequence')
    def _compute_timings(self):
        """Gọi thẳng công thức ở ``pickup_metrics`` — không có phép trừ thời gian nào ở đây.

        Phải tính trên TOÀN BỘ điểm của chuyến chứ không chỉ các bản ghi trong ``self``:
        thời gian di chuyển của một điểm phụ thuộc vào mốc rời của điểm liền trước nó.
        """
        for run in self.run_id:
            stops = run.stop_ids | self.filtered(lambda s: s.run_id == run)
            timings = pickup_metrics.compute_run_timings(
                run.depart_at, run.returned_at,
                [{
                    'key': stop.id,
                    'sequence': stop.sequence,
                    'arrived_at': stop.arrived_at,
                    'done_at': stop.done_at,
                } for stop in stops],
            )
            position = {key: index + 1 for index, key in enumerate(timings['order'])}
            for stop in stops & self:
                values = timings['stops'].get(stop.id) or {}
                stop.actual_sequence = position.get(stop.id, 0)
                stop.travel_minutes = values.get('travel_minutes') or 0
                stop.service_minutes = values.get('service_minutes') or 0
                stop.chain_broken = values.get('chain_broken', False)

        # Điểm chưa gắn chuyến (đang tạo dở trên form) vẫn phải có giá trị, nếu không Odoo
        # báo lỗi "compute không gán giá trị".
        for stop in self.filtered(lambda s: not s.run_id):
            stop.actual_sequence = 0
            stop.travel_minutes = 0
            stop.service_minutes = 0
            stop.chain_broken = False

    @api.depends('travel_minutes', 'planned_travel_minutes', 'chain_broken')
    def _compute_travel_gap(self):
        for stop in self:
            if stop.chain_broken or not stop.planned_travel_minutes or not stop.travel_minutes:
                stop.travel_gap_minutes = 0
            else:
                stop.travel_gap_minutes = stop.travel_minutes - stop.planned_travel_minutes

    @api.depends('gps_lat', 'gps_lng', 'point_id.latitude', 'point_id.longitude')
    def _compute_gps_distance(self):
        threshold = self._gps_far_meters()
        for stop in self:
            distance = haversine_m(
                (stop.gps_lat, stop.gps_lng),
                (stop.point_id.latitude, stop.point_id.longitude),
            )
            stop.gps_distance_m = distance or 0
            stop.gps_far = bool(distance and distance > threshold)

    @api.model
    def _gps_far_meters(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_GPS_FAR_METERS)
        try:
            return int(raw) if raw else DEFAULT_GPS_FAR_METERS
        except (TypeError, ValueError):
            return DEFAULT_GPS_FAR_METERS

    # ------------------------------------------------------------------
    # Thao tác của người đi nhận
    # ------------------------------------------------------------------
    def mark_arrived(self, when=None, gps=None):
        """Ghi mốc TỚI điểm.

        when: datetime giờ bấm trên máy người dùng (không phải giờ máy chủ nhận request —
        điện thoại mất sóng thì hai giờ đó lệch nhau rất xa).
        gps: dict ``{'lat', 'lng', 'accuracy'}`` hoặc None.

        Bấm lại lần hai trên cùng một điểm KHÔNG ghi đè mốc cũ: mốc đầu tiên mới là lúc
        thật sự tới nơi.
        """
        self.ensure_one()
        self._check_run_open()
        if self.arrived_at:
            return False

        values = {'arrived_at': when or fields.Datetime.now(), 'state': 'arrived'}
        if gps:
            values.update({
                'gps_lat': gps.get('lat') or 0.0,
                'gps_lng': gps.get('lng') or 0.0,
                'gps_accuracy_m': int(gps.get('accuracy') or 0),
            })
        self.write(values)
        if self.run_id.state == 'assigned':
            self.run_id.write({'state': 'departed'})
        return True

    def mark_done(self, when=None):
        """Ghi mốc RỜI điểm — coi như đã nhận xong mọi thứ lấy được ở đây.

        Quên bấm "đã tới" thì suy mốc tới bằng chính mốc rời và bật cờ ``is_estimated``:
        giữ lại chuyến để còn đi tiếp, nhưng đánh dấu để thống kê không dùng dòng này.
        Các đơn còn ``pending`` được coi là CHƯA CÓ HÀNG chứ không phải đã nhận — đoán theo
        hướng có lợi sẽ tạo ra dữ liệu nhận hàng sai.
        """
        self.ensure_one()
        self._check_run_open()
        if self.done_at:
            return False

        when = when or fields.Datetime.now()
        values = {'done_at': when, 'state': 'done'}
        if not self.arrived_at:
            values.update({'arrived_at': when, 'is_estimated': True})
        self.write(values)

        pending = self.line_ids.filtered(lambda l: l.state == 'pending')
        if pending:
            pending.write({
                'state': 'not_ready',
                'note': 'Tự đánh dấu khi rời điểm — người đi nhận chưa xác nhận đơn này.',
            })
        return True

    def mark_skipped(self, reason, failed=False):
        """Bỏ qua điểm (chưa tới) hoặc tới nhưng không nhận được hàng.

        reason bắt buộc: một điểm bị bỏ mà không ai biết vì sao thì lần sau vẫn xếp vào
        chuyến và lại bị bỏ.
        """
        self.ensure_one()
        self._check_run_open()
        if not (reason or '').strip():
            raise UserError('Phải ghi lý do khi bỏ qua điểm "%s".' % self.point_id.name)
        self.write({
            'state': 'failed' if failed else 'skipped',
            'skip_reason': reason.strip(),
        })
        self.line_ids.filtered(lambda l: l.state == 'pending').write({
            'state': 'not_ready', 'note': reason.strip(),
        })
        return True

    def _check_run_open(self):
        if self.run_id.state in ('done', 'cancelled'):
            raise UserError(
                'Chuyến "%s" đã kết thúc nên không ghi nhận thêm được.' % self.run_id.name
            )

    # --- Nút trên form backend ---------------------------------------------
    def action_arrive(self):
        for stop in self:
            stop.mark_arrived()
        return True

    def action_done(self):
        for stop in self:
            stop.mark_done()
        return True

    def action_reset_marks(self):
        """Xoá mốc để bấm lại — dành cho quản lý khi người đi nhận bấm nhầm điểm.

        Không mở cho người đi nhận: sửa được mốc của chính mình thì số liệu đo hết giá trị.
        """
        self.write({
            'arrived_at': False, 'done_at': False, 'is_estimated': False,
            'state': 'pending', 'gps_lat': 0.0, 'gps_lng': 0.0, 'gps_accuracy_m': 0,
        })
        return True
