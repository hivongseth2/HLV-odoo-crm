# -*- coding: utf-8 -*-
"""API cho agent ghi hình chạy tại kho.

Agent chỉ gọi RA, Odoo không bao giờ gọi vào máy kho — nhờ vậy không có cổng nào
mở ở phía kho, không dính chuyện mixed content hay Private Network Access của
trình duyệt. Đổi lại lệnh start/stop có độ trễ đúng bằng chu kỳ poll.

Các route ở đây auth='public' vì agent không phải một user Odoo. Thứ duy nhất
chặn người lạ là cặp station_key + agent_token, nên mọi route đều phải đi qua
_station_from_request() trước khi làm bất cứ việc gì.
"""
import logging
import os
import threading

from odoo import fields, http
from odoo.http import request
from werkzeug.wrappers import Response

from odoo.addons.custom_barcode_scan_redirect.controllers._shared import (
    _bg_upload_to_drive, _file_path,
)

_logger = logging.getLogger(__name__)

# Agent gửi từng khúc; giữ nhỏ để một khúc hỏng không phải làm lại cả file.
MAX_CHUNK_MB = 8
ALLOWED_EXT = {'.mp4', '.mkv'}


def _station_from_request(params):
    """Tra bàn đóng gói từ station_key + token trong payload.

    Trả về recordset một bàn, hoặc recordset rỗng nếu không khớp.
    """
    return request.env['hlv.pack.station'].sudo()._authenticate(
        params.get('station_key'), params.get('token'),
    )


def _agent_upload_path(recording_id):
    return _file_path('agentrec_%d' % int(recording_id))


class PackAgentApi(http.Controller):

    @http.route('/pack_agent/poll', type='json', auth='public', csrf=False, methods=['POST'])
    def poll(self, **kw):
        """Agent hỏi có việc gì không, đồng thời báo nó đang ghi những gì.

        Nhận: station_key, token, active_ids (danh sách recording_id agent đang
            thực sự chạy ffmpeg), agent_version.
        Trả: danh sách lệnh start/stop.

        active_ids là cơ chế tự chữa: bản ghi nào Odoo tưởng đang chạy mà agent
        không báo thì đánh hỏng ngay, thay vì để treo tới lúc cron dọn.
        """
        station = _station_from_request(kw)
        if not station:
            return {'ok': False, 'error': 'auth'}

        station.write({
            'agent_last_seen': fields.Datetime.now(),
            'agent_version': (kw.get('agent_version') or '')[:64],
        })

        Recording = request.env['hlv.pack.recording'].sudo()
        active_ids = set(int(i) for i in (kw.get('active_ids') or []) if str(i).isdigit())

        # Lệnh dừng trước: nếu một phiếu vừa xong, ưu tiên đóng file lại.
        to_stop = Recording.search([
            ('station_id', '=', station.id), ('state', '=', 'stopping'),
        ])
        commands = [rec.to_command('stop') for rec in to_stop]

        to_start = Recording.search([
            ('station_id', '=', station.id), ('state', '=', 'pending'),
        ])
        commands += [rec.to_command('start') for rec in to_start]
        to_start.mark_started()

        # Agent bảo nó không chạy cái này -> nó đã chết hoặc ffmpeg tắt ngang.
        orphans = Recording.search([
            ('station_id', '=', station.id), ('state', '=', 'recording'),
        ]).filtered(lambda r: r.id not in active_ids and r.id not in to_start.ids)
        if orphans:
            orphans.mark_failed("agent báo không còn chạy tiến trình ghi")

        # Chiều ngược lại: agent đang chạy ffmpeg cho bản ghi mà Odoo đã đóng sổ
        # (bị đánh hỏng lúc kết thúc phiếu vì lệnh start tới trễ). Bảo nó dừng,
        # không thì tiến trình đó chạy tới hết max_seconds mới thôi.
        stale_active = active_ids - set(to_stop.ids)
        if stale_active:
            zombies = Recording.browse(sorted(stale_active)).exists().filtered(
                lambda r: r.state in ('done', 'failed'))
            for zombie in zombies:
                commands.append(zombie.to_command('stop'))

        return {
            'ok': True,
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
            'commands': commands,
        }

    @http.route('/pack_agent/upload_chunk', type='http', auth='public', csrf=False, methods=['POST'])
    def upload_chunk(self, **kw):
        """Nhận một khúc file từ agent và nối vào file tạm trên server."""
        form = request.httprequest.form
        station = _station_from_request(form)
        if not station:
            return Response('auth', status=403)

        try:
            recording_id = int(form.get('recording_id') or 0)
            index = int(form.get('index') or -1)
        except (TypeError, ValueError):
            return Response('bad params', status=400)
        if not recording_id or index < 0:
            return Response('bad params', status=400)

        recording = request.env['hlv.pack.recording'].sudo().browse(recording_id).exists()
        if not recording or recording.station_id != station:
            return Response('unknown recording', status=404)

        chunk = request.httprequest.files.get('chunk')
        if not chunk:
            return Response('no chunk', status=400)
        data = chunk.read()
        if len(data) > MAX_CHUNK_MB * 1024 * 1024:
            return Response('chunk too large', status=413)

        path = _agent_upload_path(recording_id)
        # index 0 mở file mới: agent gửi lại từ đầu sau khi lỗi thì ghi đè, không nối tiếp rác.
        with open(path, 'wb' if index == 0 else 'ab') as out:
            out.write(data)

        if recording.state != 'uploading':
            recording.write({'state': 'uploading'})
        return Response('OK', status=200, content_type='text/plain')

    @http.route('/pack_agent/upload_done', type='json', auth='public', csrf=False, methods=['POST'])
    def upload_done(self, **kw):
        """Agent báo đã gửi hết file; đẩy lên Drive và ghi chú vào phiếu."""
        station = _station_from_request(kw)
        if not station:
            return {'ok': False, 'error': 'auth'}

        try:
            recording_id = int(kw.get('recording_id') or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'bad recording_id'}

        recording = request.env['hlv.pack.recording'].sudo().browse(recording_id).exists()
        if not recording or recording.station_id != station:
            return {'ok': False, 'error': 'unknown recording'}

        ext = (kw.get('ext') or '.mp4').lower()
        if ext not in ALLOWED_EXT:
            return {'ok': False, 'error': 'ext not allowed'}

        path = _agent_upload_path(recording_id)
        if not os.path.exists(path):
            recording.mark_failed("không thấy file tạm trên server")
            return {'ok': False, 'error': 'missing file'}

        size_mb = os.path.getsize(path) / 1024 / 1024
        recording.write({'size_mb': size_mb})
        if size_mb < 0.05:
            recording.mark_failed("file rỗng — ffmpeg không ghi được gì")
            try:
                os.remove(path)
            except OSError:
                pass
            return {'ok': False, 'error': 'empty file'}

        # Đổi đuôi cho khớp định dạng agent gửi lên, rồi giao cho cùng một hàm
        # upload Drive mà luồng quay bằng trình duyệt đang dùng.
        final_path = os.path.splitext(path)[0] + ext
        if final_path != path:
            os.replace(path, final_path)

        mimetype = 'video/mp4' if ext == '.mp4' else 'video/x-matroska'
        # Đẩy Drive ở luồng nền: file 150MB mà đẩy đồng bộ thì agent hết timeout
        # trước khi Odoo kịp trả lời, rồi agent gửi lại từ đầu. _bg_upload_to_drive
        # tự ghi chú thất bại lên chatter của phiếu nếu Drive hỏng.
        threading.Thread(
            target=_bg_upload_to_drive,
            args=(request.db, recording.picking_id.id, final_path, mimetype),
            kwargs={'name_suffix': recording.camera_id.code or ''},
            daemon=True,
        ).start()
        recording.write({'state': 'done'})
        _logger.info("PACK_REC xong %s/%s %.1fMB",
                     recording.picking_id.name, recording.camera_id.code, size_mb)
        return {'ok': True}

    @http.route('/pack_agent/report_failure', type='json', auth='public', csrf=False, methods=['POST'])
    def report_failure(self, **kw):
        """Agent tự báo hỏng (ffmpeg chết, camera không kết nối được...)."""
        station = _station_from_request(kw)
        if not station:
            return {'ok': False, 'error': 'auth'}
        try:
            recording_id = int(kw.get('recording_id') or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'bad recording_id'}
        recording = request.env['hlv.pack.recording'].sudo().browse(recording_id).exists()
        if not recording or recording.station_id != station:
            return {'ok': False, 'error': 'unknown recording'}
        recording.mark_failed((kw.get('reason') or '')[:500])
        return {'ok': True}
