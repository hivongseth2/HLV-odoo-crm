import logging

from odoo import api, fields, models

from .dispatch_utils import split_codes

_logger = logging.getLogger(__name__)

# 10 cột nghiệp vụ của bảng thói quen khách. Dùng để tính độ đầy và sinh việc cho sale.
PROFILE_BUSINESS_FIELDS = [
    ('zone_id', 'Cụm tuyến'),
    ('default_vehicle_id', 'Xe mặc định'),
    ('procedure_before', 'Thủ tục trước khi giao'),
    ('needs_technician', 'Cần kỹ thuật lắp đặt'),
    ('service_minutes', 'Thời gian tại điểm'),
    ('receiving_from', 'Giờ nhận hàng'),
    ('payment_method', 'Thanh toán'),
    ('oversize_note', 'Hàng quá khổ'),
    ('delivery_method', 'Hình thức giao'),
    ('free_note', 'Ghi chú tự do'),
]


class HlvDeliveryPartnerProfile(models.Model):
    """Thói quen khách — gắn vào ĐIỂM, không gắn vào từng mã khách.

    Ba mã Odoo của cùng một nhà máy phải dùng chung một bộ thói quen, nếu không sẽ
    có chuyện đơn này biết phải khai hải quan trước còn đơn kia thì không.

    Dữ liệu nền hiện gần như rỗng: trong 86 ghim trên bản đồ chỉ có 3 ghim ghi chú
    thói quen. Vì vậy nhóm field "phân công sale" bên dưới phải có ngay từ đầu —
    thêm sau sẽ phải migrate lại toàn bộ profile đã điền.
    """

    _name = 'hlv.delivery.partner.profile'
    _description = 'Thói quen giao hàng của khách'
    _inherit = ['mail.thread']
    _rec_name = 'point_id'
    _order = 'point_id'

    point_id = fields.Many2one(
        'hlv.delivery.point', string='Điểm giao', required=True, index=True,
        ondelete='cascade', tracking=True,
    )
    active = fields.Boolean(default=True)

    # --- 10 cột nghiệp vụ ---------------------------------------------------
    zone_id = fields.Many2one(
        'hlv.delivery.zone', string='Cụm tuyến', tracking=True,
        help='Để trống thì lấy theo cụm của điểm giao.',
    )
    default_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe mặc định', tracking=True,
        domain="[('x_dispatch_enabled', '=', True)]",
    )
    procedure_before = fields.Selection(
        [
            ('none', 'Không cần'),
            ('customs', 'Khai hải quan trước (khu chế xuất)'),
            ('register', 'Đăng ký trước khi giao'),
        ],
        string='Thủ tục trước khi giao', default='none', tracking=True,
        help='Cột này từng cứu được một chuyến: đơn bị chặn thủ tục mà phát hiện sớm thì '
             'tài xế lấp bằng điểm khác thay vì chạy không.',
    )
    needs_technician = fields.Boolean(
        string='Cần kỹ thuật lắp đặt', tracking=True,
        help='VD Posco VST: đi chuyến riêng không phải vì khách mà vì 2 máy Karcher công '
             'nghiệp cần kỹ thuật lắp đặt.',
    )
    service_minutes = fields.Integer(
        string='Thời gian tại điểm (phút)', tracking=True,
        help='Để 0 thì dùng định mức chung của cụm.',
    )
    receiving_from = fields.Float(string='Nhận hàng từ', tracking=True, help='Giờ dạng 8.5 = 8h30')
    receiving_to = fields.Float(string='Nhận hàng đến', tracking=True)
    payment_method = fields.Selection(
        [('none', 'Không thu tiền'), ('cod', 'Thu COD'), ('transfer', 'Chuyển khoản sau')],
        string='Thanh toán', default='none', tracking=True,
    )
    oversize_note = fields.Char(string='Hàng quá khổ', tracking=True)
    delivery_method = fields.Selection(
        [
            ('company', 'Xe công ty giao'),
            ('pickup', 'Khách tự ghé lấy'),
            ('express', 'Chuyển phát nhanh'),
            ('grab', 'Book Grab'),
        ],
        string='Hình thức giao', default='company', tracking=True,
    )
    free_note = fields.Text(string='Ghi chú tự do', tracking=True)

    # --- Phân công sale (nền cho việc giao sale cập nhật thói quen) ----------
    responsible_sale_user_id = fields.Many2one(
        'res.users', string='Sale phụ trách', tracking=True, index=True,
    )
    responsible_source = fields.Selection(
        [('auto', 'Máy suy'), ('manual', 'Gán tay')],
        string='Nguồn phân công', default='auto', required=True,
        help='Cron chỉ cập nhật lại các profile để "Máy suy". Gán tay thì không bị đè.',
    )
    responsible_conflict = fields.Boolean(
        string='Phân công mập mờ', readonly=True,
        help='Nhiều tài khoản cùng khớp mã sale, hoặc các mã khách trong điểm thuộc nhiều sale '
             'khác nhau. Máy không đoán bừa — điều phối chọn tay.',
    )
    verification_state = fields.Selection(
        [('draft', 'Chưa điền'), ('confirmed', 'Đã xác nhận'), ('expired', 'Hết hạn')],
        string='Tình trạng xác nhận', default='draft', required=True, index=True, tracking=True,
    )
    last_verified_by_id = fields.Many2one('res.users', string='Người xác nhận', readonly=True)
    last_verified_at = fields.Datetime(string='Xác nhận lúc', readonly=True)
    review_due_date = fields.Date(string='Hạn soát lại')

    # --- Độ đầy dữ liệu -----------------------------------------------------
    filled_count = fields.Integer(compute='_compute_completeness', store=True)
    completeness = fields.Float(
        compute='_compute_completeness', store=True, string='Độ đầy (%)',
    )
    missing_fields = fields.Char(compute='_compute_completeness', store=True, string='Còn thiếu')

    _sql_constraints = [
        ('point_uniq', 'unique(point_id)', 'Mỗi điểm giao chỉ có một bảng thói quen.'),
    ]

    @api.depends(*([f[0] for f in PROFILE_BUSINESS_FIELDS] + ['receiving_to', 'verification_state']))
    def _compute_completeness(self):
        total = len(PROFILE_BUSINESS_FIELDS)
        for profile in self:
            missing = []
            filled = 0
            for field_name, label in PROFILE_BUSINESS_FIELDS:
                value = profile[field_name]
                # 'none'/False là giá trị mặc định, coi như CHƯA điền — mục đích của cột này
                # là biết chỗ nào người thật đã xác nhận, không phải chỗ nào có giá trị.
                if field_name == 'procedure_before':
                    is_filled = bool(value) and value != 'none'
                elif field_name == 'needs_technician':
                    is_filled = profile.verification_state == 'confirmed'
                elif field_name == 'receiving_from':
                    is_filled = bool(profile.receiving_from or profile.receiving_to)
                elif field_name == 'payment_method':
                    is_filled = bool(value) and value != 'none'
                else:
                    is_filled = bool(value)
                if is_filled:
                    filled += 1
                else:
                    missing.append(label)
            profile.filled_count = filled
            profile.completeness = round(100.0 * filled / total, 1) if total else 0.0
            profile.missing_fields = ', '.join(missing)

    def action_confirm(self):
        self.write({
            'verification_state': 'confirmed',
            'last_verified_by_id': self.env.user.id,
            'last_verified_at': fields.Datetime.now(),
        })
        return True

    # ------------------------------------------------------------------
    # Suy sale phụ trách
    # ------------------------------------------------------------------
    @api.model
    def _user_ids_by_saler_code(self):
        """Bảng tra mã sale MISA (viết hoa) -> danh sách user.

        Một tài khoản có thể khai nhiều mã (chuỗi phân tách bởi dấu phẩy), và một mã
        về lý thuyết có thể thuộc nhiều tài khoản.
        """
        mapping = {}
        users = self.env['res.users'].sudo().search([('active', '=', True)])
        for user in users:
            for code in split_codes(getattr(user, 'x_misa_saler_codes', '') or ''):
                mapping.setdefault(code.upper(), []).append(user.id)
        return mapping

    def _guess_responsible_user(self, code_map=None):
        """Suy sale phụ trách từ mã sale của đơn gần nhất tại điểm.

        Trả về (user_id hoặc False, conflict). Không đoán bừa khi mập mờ: gán sai nghĩa là
        sale khác có quyền sửa thói quen khách không phải của mình.
        """
        self.ensure_one()
        if code_map is None:
            code_map = self._user_ids_by_saler_code()
        partner_ids = self.point_id.partner_ids.ids
        if not partner_ids:
            return False, False
        order = self.env['sale.order'].sudo().search(
            [('partner_id', 'in', partner_ids)], order='date_order desc, id desc', limit=1,
        )
        if not order:
            return False, False
        code = (getattr(order, 'x_studio_misa_saler_code', '') or '').strip()
        if not code:
            return False, False
        candidates = code_map.get(code.upper(), [])
        if len(candidates) == 1:
            return candidates[0], False
        if len(candidates) > 1:
            return False, True
        return False, False

    @api.model
    def _ensure_profiles_for_points(self, limit=200):
        """Tạo bảng thói quen rỗng cho điểm chưa có.

        Cần bước này thì cron giao việc mới có chỗ bám: điểm không có profile thì không
        có sale phụ trách, mà không có sale phụ trách thì không ai được giao việc điền.
        """
        points = self.env['hlv.delivery.point'].search([
            ('has_profile', '=', False), ('active', '=', True),
        ], limit=limit)
        for point in points:
            point.get_or_create_profile()
        return len(points)

    @api.model
    def cron_compute_responsible_sale(self, limit=500):
        """Cập nhật sale phụ trách cho các profile để "Máy suy"."""
        self._ensure_profiles_for_points()
        profiles = self.search([('responsible_source', '=', 'auto')], limit=limit)
        if not profiles:
            return 0
        code_map = self._user_ids_by_saler_code()
        changed = 0
        for profile in profiles:
            user_id, conflict = profile._guess_responsible_user(code_map)
            vals = {}
            if profile.responsible_sale_user_id.id != (user_id or False):
                vals['responsible_sale_user_id'] = user_id or False
            if profile.responsible_conflict != conflict:
                vals['responsible_conflict'] = conflict
            if vals:
                profile.write(vals)
                changed += 1
        _logger.info('Phân công sale: cập nhật %s/%s profile', changed, len(profiles))
        return changed

    @api.model
    def cron_expire_verification(self):
        """Profile quá hạn soát lại thì chuyển sang 'Hết hạn' để lọt vào backlog."""
        today = fields.Date.context_today(self)
        expired = self.search([
            ('verification_state', '=', 'confirmed'),
            ('review_due_date', '!=', False),
            ('review_due_date', '<', today),
        ])
        if expired:
            expired.write({'verification_state': 'expired'})
        return len(expired)
