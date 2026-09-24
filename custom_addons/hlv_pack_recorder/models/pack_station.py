# -*- coding: utf-8 -*-
"""Bàn đóng gói: một máy tính, một bộ camera, một agent ghi hình."""
import secrets
from datetime import timedelta

from odoo import api, fields, models

# Agent poll 2 giây một lần. Quá ngưỡng này không thấy tin tức thì coi như nó
# không chạy — để rộng gấp nhiều lần chu kỳ poll vì mạng chớp là chuyện thường.
AGENT_ALIVE_WINDOW_SECONDS = 120

# Mã cài đặt chỉ sống đủ lâu để người ta đi từ máy tính văn phòng ra bàn đóng gói.
ENROLL_CODE_TTL_MINUTES = 30

# Bỏ 0/O/1/I: người đọc mã qua điện thoại hoặc chép tay hay nhầm mấy ký tự này.
ENROLL_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _random_enroll_code():
    """Sinh mã 8 ký tự dạng XXXX-XXXX cho dễ đọc."""
    raw = ''.join(secrets.choice(ENROLL_ALPHABET) for _ in range(8))
    return '%s-%s' % (raw[:4], raw[4:])


class HlvPackStation(models.Model):
    _name = 'hlv.pack.station'
    _description = "Bàn đóng gói"
    _order = 'warehouse_id, name'

    name = fields.Char("Tên bàn", required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Kho", required=True)
    active = fields.Boolean(default=True)

    station_key = fields.Char(
        "Mã máy", required=True, copy=False, index=True,
        default=lambda self: self._default_station_key(),
        help="Trình duyệt trên máy đóng gói lưu mã này và gửi kèm mỗi lần mở phiếu. "
             "Đặt một lần bằng /pack_recorder/set_station?key=<mã>.",
    )
    # Để trong group_system: token là thứ duy nhất chặn người lạ gọi API agent.
    agent_token = fields.Char(
        "Token agent", required=True, copy=False, groups='base.group_system',
        default=lambda self: secrets.token_urlsafe(32),
        help="Agent gửi kèm token này mỗi lần gọi. Sinh lại token là agent cũ mất quyền ngay.",
    )

    camera_ids = fields.One2many('hlv.pack.camera', 'station_id', string="Camera")
    camera_count = fields.Integer(compute='_compute_camera_count')

    agent_last_seen = fields.Datetime(
        "Agent gọi lần cuối", readonly=True,
        help="Agent im quá lâu nghĩa là máy tắt hoặc service chết — phiếu đóng gói ở bàn này sẽ không có video.",
    )
    agent_version = fields.Char(readonly=True)

    enroll_code = fields.Char(
        "Mã cài đặt", copy=False, readonly=True,
        help="Mã dùng một lần để máy đóng gói tự lấy cấu hình. Hết hạn sau %d phút."
             % ENROLL_CODE_TTL_MINUTES,
    )
    enroll_code_expiry = fields.Datetime(readonly=True, copy=False)
    setup_command = fields.Char(compute='_compute_setup_command')
    agent_status = fields.Selection(
        [
            ('never', "Chưa bao giờ gọi"),
            ('alive', "Đang chạy"),
            ('dead', "Đã ngừng"),
        ],
        string="Tình trạng agent", compute='_compute_agent_status',
        help="Bàn không có agent đang chạy thì phiếu đóng gói ở đó sẽ KHÔNG có video "
             "từ agent. Luồng quay bằng trình duyệt vẫn hoạt động bình thường.",
    )

    @api.depends('agent_last_seen')
    def _compute_agent_status(self):
        # Non-stored nên tính lại mỗi lần đọc — đúng thứ cần, vì kết quả phụ
        # thuộc thời điểm hiện tại chứ không chỉ phụ thuộc dữ liệu.
        for station in self:
            if not station.agent_last_seen:
                station.agent_status = 'never'
            else:
                station.agent_status = 'alive' if station.is_agent_alive() else 'dead'

    @api.depends('station_key')
    def _compute_setup_command(self):
        """Lệnh PowerShell dán một phát trên máy đóng gói.

        Gán biến môi trường trước rồi mới tải script, để script khỏi phải hỏi
        địa chỉ Odoo — dán một dòng là xong, người cài chỉ còn gõ mã cài đặt.
        """
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        for station in self:
            station.setup_command = (
                "$env:HLV_ODOO_URL='%s'; irm %s/pack_agent/download/setup | iex" % (base, base)
            )

    _sql_constraints = [
        ('station_key_uniq', 'unique(station_key)', "Mã máy phải là duy nhất."),
    ]

    @api.model
    def _default_station_key(self):
        return 'BAN-%s' % secrets.token_hex(3).upper()

    @api.depends('camera_ids')
    def _compute_camera_count(self):
        for station in self:
            station.camera_count = len(station.camera_ids)

    def action_generate_enroll_code(self):
        """Sinh mã cài đặt dùng một lần cho máy đóng gói.

        Người cài chỉ cần gõ mã ngắn này thay vì chép tay station_key và token.
        Mã hết hạn sau ENROLL_CODE_TTL_MINUTES và dùng xong là huỷ ngay, nên lộ
        ra ngoài cũng không thành cửa sau lâu dài.
        """
        self.ensure_one()
        self.write({
            'enroll_code': _random_enroll_code(),
            'enroll_code_expiry': fields.Datetime.now() + timedelta(
                minutes=ENROLL_CODE_TTL_MINUTES),
        })

    @api.model
    def consume_enroll_code(self, code):
        """Đổi mã cài đặt lấy thông tin bàn, và huỷ mã ngay sau đó.

        code: chuỗi người cài gõ vào, không phân biệt hoa thường và dấu gạch.
        Trả về: recordset một bàn nếu mã đúng và còn hạn, rỗng nếu sai/hết hạn.
        """
        normalised = (code or '').strip().upper().replace('-', '')
        if len(normalised) < 8:
            return self.browse()
        station = self.sudo().search([
            ('enroll_code', '!=', False),
            ('enroll_code_expiry', '>', fields.Datetime.now()),
        ]).filtered(lambda s: secrets.compare_digest(
            (s.enroll_code or '').replace('-', ''), normalised))
        if not station:
            return self.browse()
        station = station[0]
        # Dùng một lần: huỷ ngay để mã bị chụp màn hình cũng vô dụng.
        station.write({'enroll_code': False, 'enroll_code_expiry': False})
        return station

    def is_agent_deployed(self):
        """Bàn này đã từng có agent chạy chưa.

        Khác hẳn is_agent_alive(): "chưa bao giờ chạy" nghĩa là bàn chưa tới lượt
        cài đặt — không phải sự cố. Còn "từng chạy rồi im" là hỏng thật, phải kêu.
        """
        self.ensure_one()
        return bool(self.agent_last_seen)

    def is_agent_alive(self):
        """Agent của bàn này có đang chạy không.

        Trả về True nếu nó gọi vào trong vòng AGENT_ALIVE_WINDOW_SECONDS giây.
        Biên: chưa bao giờ gọi (agent_last_seen rỗng) -> False.
        """
        self.ensure_one()
        if not self.agent_last_seen:
            return False
        return self.agent_last_seen >= fields.Datetime.now() - timedelta(
            seconds=AGENT_ALIVE_WINDOW_SECONDS)

    def action_reset_token(self):
        """Sinh token mới. Agent đang chạy sẽ bị từ chối cho tới khi cập nhật token."""
        for station in self:
            station.agent_token = secrets.token_urlsafe(32)

    @api.model
    def _authenticate(self, station_key, token):
        """Tra bàn đóng gói từ cặp mã máy + token của agent.

        station_key: chuỗi mã máy agent gửi lên.
        token: chuỗi token agent gửi lên.
        Trả về: recordset một bàn nếu khớp, recordset rỗng nếu sai hoặc thiếu.
            So sánh bằng compare_digest để không lộ token qua thời gian phản hồi.
        """
        if not station_key or not token:
            return self.browse()
        station = self.sudo().search([('station_key', '=', station_key)], limit=1)
        if not station:
            return self.browse()
        if not secrets.compare_digest(str(station.agent_token or ''), str(token)):
            return self.browse()
        return station
