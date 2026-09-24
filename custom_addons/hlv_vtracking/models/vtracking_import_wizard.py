import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import vtracking_sync
from ..services.vtracking_client import VTrackingError

_logger = logging.getLogger(__name__)

# Dùng khi người nhập không chọn dòng xe. `fleet.vehicle.model_id` là bắt buộc, mà đội xe
# mới dựng thì chưa khai dòng xe nào — không có đường lùi này thì màn nhập bế tắc ngay
# lần dùng đầu tiên.
FALLBACK_BRAND = 'Chưa rõ'
FALLBACK_MODEL = 'Chưa phân loại'


class HlvVtrackingImportWizard(models.TransientModel):
    """Tạo xe trong Đội xe từ danh sách xe có trên tài khoản vTracking.

    Chống trùng bằng **biển số đã chuẩn hoá** (``plate_key``), không bằng chuỗi thô:
    vTracking trả ``60D-00750`` còn Odoo có thể đang lưu ``60D00750`` — so chuỗi thô sẽ
    tạo ra xe thứ hai cho cùng một chiếc.
    """

    _name = 'hlv.vtracking.import.wizard'
    _description = 'Nhập xe từ vTracking'

    line_ids = fields.One2many(
        'hlv.vtracking.import.line', 'wizard_id', string='Xe trên vTracking',
    )
    model_id = fields.Many2one(
        'fleet.vehicle.model', string='Dòng xe áp cho xe tạo mới',
        help='Để trống thì dùng dòng "%s / %s" (tạo tự động). Sửa lại trên từng xe sau '
             'khi nhập cũng được.' % (FALLBACK_BRAND, FALLBACK_MODEL),
    )
    enable_tracking = fields.Boolean(
        string='Bật theo dõi cho xe tạo mới', default=True,
        help='Tắt thì xe được tạo nhưng chưa đồng bộ vị trí, chưa hiện trên bản đồ và '
             'chưa trả ra API.',
    )
    new_count = fields.Integer(compute='_compute_counts', string='Chưa có trong Odoo')
    exists_count = fields.Integer(compute='_compute_counts', string='Đã có')
    selected_count = fields.Integer(compute='_compute_counts', string='Đang chọn')

    @api.depends('line_ids.state', 'line_ids.to_create')
    def _compute_counts(self):
        for wizard in self:
            lines = wizard.line_ids
            wizard.new_count = len(lines.filtered(lambda l: l.state == 'new'))
            wizard.exists_count = len(lines.filtered(lambda l: l.state == 'exists'))
            wizard.selected_count = len(lines.filtered(lambda l: l.to_create and l.state == 'new'))

    # ------------------------------------------------------------------
    # Mở màn hình
    # ------------------------------------------------------------------
    @api.model
    def action_open_import(self):
        """Gọi vTracking, dựng wizard đã điền sẵn danh sách, rồi mở form.

        Gọi mạng ở đây chứ không ở ``default_get``: lỗi kết nối cần hiện thành một câu
        đọc được, còn lỗi trong default_get thì Odoo nuốt thành hộp thoại trống.
        """
        wizard = self.create({})
        wizard._load_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nhập xe từ vTracking',
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reload(self):
        """Tải lại danh sách từ vTracking, giữ nguyên lựa chọn dòng xe."""
        self.ensure_one()
        self._load_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _load_lines(self):
        """Dựng lại các dòng từ phản hồi vTracking, đánh dấu xe nào Odoo đã có."""
        self.ensure_one()
        try:
            remote = vtracking_sync.fetch_remote_vehicles(self.env, self.env.company)
        except VTrackingError as exc:
            raise UserError(str(exc)) from exc
        if not remote:
            raise UserError(
                'vTracking không trả về xe nào cho tài khoản này. Kiểm tra lại API key, '
                'hoặc bật "Lấy cả xe công ty con" nếu xe nằm ở công ty con.'
            )

        existing = self._existing_by_plate_key([item['plate_key'] for item in remote])
        self.line_ids.unlink()
        self.line_ids = [
            fields.Command.create(self._line_values(item, existing)) for item in remote
        ]
        return True

    def _existing_by_plate_key(self, plate_keys):
        """dict {plate_key: fleet.vehicle} cho các biển số đang hỏi.

        Tìm theo ``plate_key`` nên xe khai ``60D-00750`` trong Odoo vẫn khớp với
        ``60D00750`` của vTracking. Xe đã lưu trữ (archived) cũng tính là đã có: tạo
        thêm một xe nữa rồi mới phát hiện bản cũ nằm trong thùng lưu trữ còn tệ hơn.
        """
        keys = [key for key in plate_keys if key]
        if not keys:
            return {}
        vehicles = self.env['fleet.vehicle'].sudo().with_context(active_test=False).search([
            ('plate_key', 'in', keys),
        ])
        result = {}
        for vehicle in vehicles:
            result.setdefault(vehicle.plate_key, vehicle)
        return result

    @api.model
    def _line_values(self, item, existing):
        vehicle = existing.get(item['plate_key'])
        return {
            'license_plate': item['license_plate'],
            'plate_key': item['plate_key'],
            'vtracking_id': item['vtracking_id'],
            'vehicle_name': item['vehicle_name'] or '',
            'org_name': item['org_name'] or '',
            'remote_status': item['status'] or '',
            'existing_vehicle_id': vehicle.id if vehicle else False,
            'state': 'exists' if vehicle else 'new',
            # Mặc định tick sẵn xe chưa có: đó là việc người dùng vào đây để làm.
            'to_create': not vehicle,
        }

    # ------------------------------------------------------------------
    # Chọn nhanh
    # ------------------------------------------------------------------
    def action_select_all_new(self):
        self.ensure_one()
        self.line_ids.filtered(lambda l: l.state == 'new').to_create = True
        return self._reopen()

    def action_unselect_all(self):
        self.ensure_one()
        self.line_ids.to_create = False
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Tạo xe
    # ------------------------------------------------------------------
    def action_create_vehicles(self):
        """Tạo xe cho các dòng đang tick, rồi mở danh sách xe vừa tạo."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.to_create and l.state == 'new')
        if not lines:
            raise UserError('Chưa chọn xe nào để tạo.')

        model = self.model_id or self._fallback_model()
        # Kiểm lại lần cuối ngay trước khi ghi: wizard có thể đã mở từ lâu và người khác
        # vừa tạo chính chiếc xe đó. Danh sách dựng lúc mở không còn là sự thật.
        existing = self._existing_by_plate_key(lines.mapped('plate_key'))

        created = self.env['fleet.vehicle']
        skipped = []
        seen_keys = set()
        for line in lines:
            key = line.plate_key
            if not key:
                skipped.append('%s (biển số không đọc được)' % line.license_plate)
                continue
            if key in existing:
                skipped.append('%s (đã có: %s)' % (
                    line.license_plate, existing[key].display_name,
                ))
                continue
            if key in seen_keys:
                skipped.append('%s (trùng trong chính danh sách)' % line.license_plate)
                continue
            seen_keys.add(key)
            created |= line._create_vehicle(model, self.enable_tracking)

        if skipped:
            _logger.info('Nhập xe vTracking: bỏ qua %s xe — %s', len(skipped), '; '.join(skipped))
        if not created:
            raise UserError(
                'Không tạo được xe nào. Lý do: %s' % '; '.join(skipped)
            )

        if self.enable_tracking:
            # Một request cho cả đội, điền vị trí cho xe vừa tạo. Lỗi ở bước này không
            # được làm hỏng việc đã tạo xe — xe cứ tồn tại, lượt đồng bộ sau sẽ điền.
            try:
                vtracking_sync.sync_vehicles(self.env, self.env.company)
            except VTrackingError as exc:
                _logger.warning('Nhập xe vTracking: tạo xong nhưng chưa lấy được vị trí: %s', exc)

        return self._created_action(created, skipped)

    def _fallback_model(self):
        """Dòng xe mặc định, tạo nếu chưa có.

        Dùng ``sudo`` vì người nhập xe không nhất thiết có quyền tạo dữ liệu nền của Đội
        xe, mà thiếu dòng xe thì không tạo nổi phương tiện.
        """
        Model = self.env['fleet.vehicle.model'].sudo()
        model = Model.search([('name', '=', FALLBACK_MODEL)], limit=1)
        if model:
            return model
        Brand = self.env['fleet.vehicle.model.brand'].sudo()
        brand = Brand.search([('name', '=', FALLBACK_BRAND)], limit=1)
        if not brand:
            brand = Brand.create({'name': FALLBACK_BRAND})
        return Model.create({'name': FALLBACK_MODEL, 'brand_id': brand.id})

    def _created_action(self, created, skipped):
        """Mở danh sách xe vừa tạo, kèm câu tóm tắt nếu có xe bị bỏ qua."""
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Xe vừa tạo từ vTracking',
            'res_model': 'fleet.vehicle',
            'domain': [('id', 'in', created.ids)],
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('hlv_vtracking.view_fleet_vehicle_vtracking_list').id, 'list'),
                (self.env.ref('hlv_vtracking.view_fleet_vehicle_vtracking_form').id, 'form'),
            ],
            'target': 'current',
        }
        if skipped:
            action['context'] = {'vtracking_skipped': skipped}
        return action


class HlvVtrackingImportLine(models.TransientModel):
    """Một xe trên vTracking, kèm kết luận Odoo đã có chưa."""

    _name = 'hlv.vtracking.import.line'
    _description = 'Dòng nhập xe từ vTracking'
    _order = 'state desc, license_plate'

    wizard_id = fields.Many2one(
        'hlv.vtracking.import.wizard', required=True, ondelete='cascade', index=True,
    )
    license_plate = fields.Char(string='Biển số', readonly=True)
    plate_key = fields.Char(string='Khoá biển số', readonly=True)
    vtracking_id = fields.Char(string='Mã vTracking', readonly=True)
    vehicle_name = fields.Char(string='Tên xe trên vTracking', readonly=True)
    org_name = fields.Char(string='Đơn vị', readonly=True)
    remote_status = fields.Char(string='Trạng thái', readonly=True)
    existing_vehicle_id = fields.Many2one('fleet.vehicle', string='Xe đã có', readonly=True)
    state = fields.Selection(
        [('new', 'Chưa có trong Odoo'), ('exists', 'Đã có')],
        string='Tình trạng', readonly=True, required=True,
    )
    to_create = fields.Boolean(string='Tạo')

    def _create_vehicle(self, model, enable_tracking):
        """Tạo một ``fleet.vehicle`` từ dòng này.

        Chỉ ghi những gì định danh xe (biển số, mã vTracking, cờ theo dõi). Vị trí do
        lượt đồng bộ ngay sau đó điền, để phép ánh xạ dữ liệu vTracking -> field Odoo chỉ
        tồn tại ở MỘT chỗ là ``vtracking_sync._vehicle_values``.
        """
        self.ensure_one()
        vehicle = self.env['fleet.vehicle'].create({
            'model_id': model.id,
            'license_plate': self.license_plate,
            'vtracking_id': self.vtracking_id,
            'vtracking_enabled': enable_tracking,
        })
        return vehicle
