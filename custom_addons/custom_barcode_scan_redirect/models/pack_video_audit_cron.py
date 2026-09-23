# -*- coding: utf-8 -*-
"""Đối soát hằng ngày: phiếu PACK đã đóng gói xong mà không có video."""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Ghi chú video do _bg_upload_to_drive đăng lên chatter luôn chứa chuỗi này.
# Dò theo nội dung ghi chú thay vì thêm một field mới, để đối soát được cả dữ
# liệu của những phiếu đã đóng gói từ trước khi có cron này.
VIDEO_NOTE_MARKER = 'Video đóng gói'
AUDIT_NOTE_MARKER = 'KHÔNG CÓ VIDEO ĐÓNG GÓI'


class PackVideoAuditCron(models.AbstractModel):
    _name = 'custom.barcode.scan.redirect.video.audit'
    _description = "Pack Video - Daily Audit For Missing Recordings"

    def _cron_audit_missing_videos(self, lookback_hours=24):
        """Lưới an toàn cuối cùng.

        Cổng chặn ở màn hình đóng gói bắt được camera chết lúc bắt đầu, watchdog
        bắt được lúc đang quay — nhưng cả hai đều chạy trong trình duyệt. Máy
        treo, mất mạng giữa chừng, upload Drive hỏng lặng lẽ thì không ai biết.
        Cron này rà ngược từ kết quả: phiếu đã xong mà chatter không có ghi chú
        video nghĩa là thiếu bằng chứng, bất kể hỏng ở khâu nào.
        """
        until = fields.Datetime.now()
        since = until - timedelta(hours=lookback_hours)

        pickings = self.env['stock.picking'].sudo().search([
            ('picking_type_id.sequence_code', 'like', 'PACK'),
            ('state', '=', 'done'),
            ('date_done', '>=', since),
            ('date_done', '<', until),
        ])
        if not pickings:
            return

        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'stock.picking'),
            ('res_id', 'in', pickings.ids),
            '|',
            ('body', 'ilike', VIDEO_NOTE_MARKER),
            ('body', 'ilike', AUDIT_NOTE_MARKER),
        ])
        already_handled = set(messages.mapped('res_id'))

        missing = pickings.filtered(lambda p: p.id not in already_handled)
        if not missing:
            _logger.info("PACK_VIDEO_AUDIT ok: %d/%d phiếu đều có video (%dh gần nhất)",
                         len(pickings), len(pickings), lookback_hours)
            return

        body = Markup(
            '⚠️ <b>{marker}</b><br/>'
            'Phiếu này đã đóng gói xong nhưng không tìm thấy ghi chú video trên chatter. '
            'Nếu khách khiếu nại đơn này thì không có bằng chứng. '
            'Kiểm tra OBS và kết nối Google Drive ở máy đóng gói.'
        ).format(marker=AUDIT_NOTE_MARKER)
        for picking in missing:
            try:
                picking.message_post(
                    body=body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
            except Exception:
                _logger.exception("PACK_VIDEO_AUDIT không đăng được ghi chú lên %s", picking.name)

        _logger.warning(
            "PACK_VIDEO_AUDIT %d/%d phiếu PACK thiếu video trong %dh gần nhất: %s",
            len(missing), len(pickings), lookback_hours,
            ', '.join(missing.mapped('name')),
        )
