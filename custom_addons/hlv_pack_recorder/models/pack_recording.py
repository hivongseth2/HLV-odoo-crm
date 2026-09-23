# -*- coding: utf-8 -*-
"""Một lần ghi hình: một phiếu đóng gói x một camera = một file."""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Agent im lặng quá lâu thì coi như máy tắt / service chết giữa chừng. Không để
# phiếu treo ở trạng thái "đang ghi" mãi, vì lúc đối soát sẽ tưởng là có video.
STALE_AFTER_MINUTES = 20

# Trần an toàn cho ffmpeg, phòng khi lệnh stop không bao giờ tới được agent.
DEFAULT_MAX_SECONDS = 30 * 60

# Màn hình đóng gói báo còn sống mỗi 10 giây. Quá ngưỡng này không thấy tin tức
# nghĩa là nhân viên đã đóng tab / bấm Back mà không bấm Hoàn tất. Để rộng hơn
# chu kỳ báo vài lần, vì F5 hay mạng chớp cũng tạo ra khoảng lặng ngắn — dừng
# vội là cắt đôi video của một phiếu đang đóng dở.
HEARTBEAT_TIMEOUT_SECONDS = 60


class HlvPackRecording(models.Model):
    _name = 'hlv.pack.recording'
    _description = "Video đóng gói theo camera"
    _order = 'id desc'

    picking_id = fields.Many2one(
        'stock.picking', string="Phiếu đóng gói",
        required=True, ondelete='cascade', index=True,
    )
    camera_id = fields.Many2one('hlv.pack.camera', string="Camera", required=True, ondelete='restrict')
    station_id = fields.Many2one(
        related='camera_id.station_id', store=True, index=True, string="Bàn đóng gói",
    )

    state = fields.Selection(
        [
            ('pending', "Chờ agent nhận"),
            ('recording', "Đang ghi"),
            ('stopping', "Chờ agent dừng"),
            ('uploading', "Đang tải lên"),
            ('done', "Xong"),
            ('failed', "Hỏng"),
        ],
        default='pending', required=True, index=True,
    )

    requested_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    started_at = fields.Datetime(readonly=True, help="Lúc agent báo đã chạy ffmpeg.")
    stopped_at = fields.Datetime(readonly=True)
    max_seconds = fields.Integer(default=DEFAULT_MAX_SECONDS, readonly=True)

    last_heartbeat = fields.Datetime(
        readonly=True,
        help="Lần cuối màn hình đóng gói báo còn mở. Dùng để biết nhân viên đã bỏ đi hay chưa.",
    )
    drive_link = fields.Char(readonly=True)
    size_mb = fields.Float(readonly=True, digits=(10, 1))
    error_note = fields.Text(readonly=True)

    # ------------------------------------------------------------------
    # Vòng đời, gọi từ màn hình đóng gói
    # ------------------------------------------------------------------
    @api.model
    def start_for_picking(self, picking, station):
        """Tạo yêu cầu ghi cho mọi camera của một bàn.

        picking: recordset stock.picking đang đóng gói.
        station: recordset hlv.pack.station của máy đang thao tác.
        Trả về: recordset các bản ghi vừa tạo. Biên: bàn không có camera nào
            đang bật -> trả recordset rỗng, không tạo gì và không báo lỗi, để
            việc đóng gói không bị chặn vì cấu hình thiếu.
        """
        if not picking or not station:
            return self.browse()

        cameras = station.camera_ids.filtered('active')
        if not cameras:
            _logger.warning("PACK_REC bàn %s chưa khai camera nào", station.name)
            return self.browse()

        now = fields.Datetime.now()

        # Một bàn chỉ đóng một phiếu tại một thời điểm. Nhân viên bỏ phiếu cũ
        # giữa chừng để mở phiếu khác thì đóng sổ phiếu cũ ngay, đừng để ffmpeg
        # của nó chạy tiếp tới hết trần 30 phút.
        others = self.search([
            ('station_id', '=', station.id),
            ('picking_id', '!=', picking.id),
            ('state', 'in', ('pending', 'recording')),
        ])
        if others:
            for picking_left in others.mapped('picking_id'):
                self.stop_for_picking(picking_left)

        # Mở lại cùng một phiếu (F5, bấm Back rồi vào lại) thì dùng tiếp phiên
        # đang chạy thay vì đẻ thêm file trùng cho cùng một đơn.
        running = self.search([
            ('picking_id', '=', picking.id),
            ('state', 'in', ('pending', 'recording')),
        ])
        if running:
            running.write({'last_heartbeat': now})
            return running

        return self.create([
            {'picking_id': picking.id, 'camera_id': camera.id, 'last_heartbeat': now}
            for camera in cameras
        ])

    @api.model
    def stop_for_picking(self, picking):
        """Đánh dấu mọi bản ghi đang chạy của phiếu là cần dừng.

        Agent sẽ thấy lệnh dừng ở lần poll kế tiếp. Trả về recordset đã đổi.
        """
        if not picking:
            return self.browse()
        recordings = self.search([
            ('picking_id', '=', picking.id),
            ('state', 'in', ('pending', 'recording')),
        ])

        # Bản còn 'pending' nghĩa là agent chưa từng nhận lệnh, nên KHÔNG có
        # ffmpeg nào để dừng. Đẩy sang 'stopping' là kẹt vĩnh viễn chờ một agent
        # không tồn tại — đánh hỏng ngay để người dùng biết liền thay vì đợi cron.
        never_started = recordings.filtered(lambda r: r.state == 'pending')
        if never_started:
            never_started.mark_failed(
                'agent không nhận lệnh trước khi phiếu kết thúc — '
                'agent chưa chạy, sai token, hoặc không kết nối được Odoo')

        running = recordings - never_started
        running.write({'state': 'stopping', 'stopped_at': fields.Datetime.now()})
        return running

    # ------------------------------------------------------------------
    # Agent gọi vào
    # ------------------------------------------------------------------
    @api.model
    def touch_heartbeat(self, picking):
        """Màn hình đóng gói báo nó vẫn đang mở.

        Trả về số bản ghi được cập nhật; 0 nghĩa là phiếu này không có bản ghi
        nào đang chạy (đã xong, hoặc bàn chưa khai camera).
        """
        if not picking:
            return 0
        running = self.search([
            ('picking_id', '=', picking.id),
            ('state', 'in', ('pending', 'recording')),
        ])
        running.write({'last_heartbeat': fields.Datetime.now()})
        return len(running)

    @api.model
    def reconcile_abandoned(self, station):
        """Đóng sổ những phiếu mà màn hình đóng gói đã biến mất.

        Nhân viên đóng tab, bấm Back, hoặc máy treo giữa chừng thì không có ai
        gửi lệnh dừng. Không dùng beforeunload của trình duyệt để làm việc này:
        F5 cũng kích hoạt beforeunload, mà F5 giữa chừng thì phải quay TIẾP chứ
        không phải cắt đôi video thành hai file.

        Trả về recordset vừa bị đóng sổ.
        """
        deadline = fields.Datetime.now() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
        abandoned = self.search([
            ('station_id', '=', station.id),
            ('state', 'in', ('pending', 'recording')),
            ('last_heartbeat', '<', deadline),
        ])
        for picking in abandoned.mapped('picking_id'):
            _logger.info("PACK_REC đóng sổ %s: màn hình đóng gói đã rời đi", picking.name)
            self.stop_for_picking(picking)
        return abandoned

    def mark_started(self):
        self.filtered(lambda r: r.state == 'pending').write({
            'state': 'recording',
            'started_at': fields.Datetime.now(),
        })

    def mark_failed(self, reason):
        self.write({'state': 'failed', 'error_note': reason or 'không rõ'})
        for rec in self:
            _logger.warning("PACK_REC hỏng %s/%s: %s",
                            rec.picking_id.name, rec.camera_id.code, reason)

    def to_command(self, action):
        """Gói bản ghi thành lệnh gửi cho agent.

        Chỉ đưa mã camera, không bao giờ đưa URL hay mật khẩu.
        """
        self.ensure_one()
        cmd = {'action': action, 'recording_id': self.id, 'camera_code': self.camera_id.code}
        if action == 'start':
            cmd['max_seconds'] = self.max_seconds or DEFAULT_MAX_SECONDS
            cmd['label'] = '%s_%s' % (
                (self.picking_id.name or '').replace('/', '_'), self.camera_id.code,
            )
        return cmd

    # ------------------------------------------------------------------
    # Lưới an toàn
    # ------------------------------------------------------------------
    @api.model
    def _cron_fail_stale(self):
        """Bản ghi kẹt quá lâu thì đánh hỏng, đừng để tưởng nhầm là có video.

        Agent chết giữa chừng, máy mất điện, mạng đứt — mọi trường hợp đều dẫn
        tới một bản ghi nằm mãi ở 'recording'. Cron đối soát bên
        custom_barcode_scan_redirect chỉ nhìn chatter, nên chỗ này phải tự dọn.
        """
        deadline = fields.Datetime.now() - timedelta(minutes=STALE_AFTER_MINUTES)
        stuck = self.search([
            ('state', 'in', ('pending', 'recording', 'stopping', 'uploading')),
            ('requested_at', '<', deadline),
        ])
        if not stuck:
            return
        stuck.mark_failed("agent không phản hồi trong %d phút" % STALE_AFTER_MINUTES)
        for rec in stuck:
            rec.picking_id.message_post(
                body=Markup(
                    "⚠️ Không nhận được video camera <b>{cam}</b> (bàn {station}): "
                    "agent không phản hồi."
                ).format(cam=rec.camera_id.name or '', station=rec.station_id.name or ''),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
