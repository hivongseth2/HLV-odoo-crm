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

        # Mở lại cùng một phiếu (F5, quay lại giữa chừng) thì dùng tiếp phiên
        # đang chạy thay vì đẻ thêm file trùng.
        running = self.search([
            ('picking_id', '=', picking.id),
            ('state', 'in', ('pending', 'recording')),
        ])
        if running:
            return running

        return self.create([
            {'picking_id': picking.id, 'camera_id': camera.id}
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
        recordings.write({'state': 'stopping', 'stopped_at': fields.Datetime.now()})
        return recordings

    # ------------------------------------------------------------------
    # Agent gọi vào
    # ------------------------------------------------------------------
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
