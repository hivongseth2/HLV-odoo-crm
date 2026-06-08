# -*- coding: utf-8 -*-
"""Video recording upload routes (single + chunked + finish)."""
from odoo import http
from odoo.http import request
from werkzeug.utils import secure_filename
from werkzeug.wrappers import Response
from werkzeug.exceptions import BadRequest, NotFound, UnsupportedMediaType, RequestEntityTooLarge
from tempfile import NamedTemporaryFile
import logging
import os
import uuid
import json
import time
import threading

from ._shared import (
    ALLOWED_MIME, MAX_UPLOAD_MB, STREAM_DIR,
    _meta_path, _uploading_meta_path, _file_path, _bg_upload_to_drive,
)

_logger = logging.getLogger(__name__)


class RecordingController(http.Controller):

    # ===================== Fallback: upload 1 phát (nếu cần) =====================
    @http.route('/pack_scan/upload_video', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_pack_video(self, **kwargs):
        httpreq = request.httprequest

        picking_id = httpreq.form.get('picking_id')
        if not picking_id: raise BadRequest("Missing picking_id")
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists(): raise NotFound("Picking not found")

        file = httpreq.files.get('file')
        if not file: raise BadRequest("No file")

        mimetype = (file.mimetype or 'application/octet-stream').split(';', 1)[0]
        if mimetype not in ALLOWED_MIME:
            raise UnsupportedMediaType(f"Unsupported mimetype: {mimetype}")

        data = file.read()
        size_mb = len(data) / 1024 / 1024
        if size_mb > MAX_UPLOAD_MB:
            raise RequestEntityTooLarge(f"File too large: {size_mb:.1f}MB > {MAX_UPLOAD_MB}MB")

        safe_name = secure_filename(file.filename or f"{picking.name}_PACK.webm").replace('__', '_')
        ext = os.path.splitext(safe_name)[1] or ('.webm' if mimetype == 'video/webm' else '')
        with NamedTemporaryFile(prefix='pack_', suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            t = threading.Thread(target=_bg_upload_to_drive, args=(request.db, int(picking_id), tmp_path, mimetype), daemon=True)
            t.start()
        except Exception:
            try: os.remove(tmp_path)
            except Exception: pass
            return Response("UPLOAD_FAILED", status=500, content_type='text/plain; charset=utf-8')

        return Response("OK", status=200, content_type='text/plain; charset=utf-8')

    # ===================== Streaming theo CHUNK =====================
    @http.route('/pack_scan/start_upload', type='json', auth='user', csrf=False)
    def start_upload(self, **kw):
        picking_id = int(kw.get('picking_id') or 0)
        if picking_id:
            picking = request.env['stock.picking'].sudo().browse(picking_id).exists()
            if picking:
                picking.with_user(request.env.user).mark_pack_actual_started(user=request.env.user)
        ext = (kw.get('ext') or 'webm').strip('.')
        mimetype = kw.get('mimetype') or 'video/webm'
        upload_id = uuid.uuid4().hex
        meta = {
            'picking_id': picking_id,
            'mimetype': mimetype,
            'ext': ext,
            'created': int(time.time()),
            'last_index': -1,
            'path': _file_path(upload_id),
        }
        with open(_meta_path(upload_id), 'w', encoding='utf-8') as f:
            json.dump(meta, f)

        _logger.info("START_UPLOAD id=%s pick=%s path=%s mimetype=%s",
                    upload_id, picking_id, meta['path'], mimetype)

        return {'upload_id': upload_id}

    @http.route('/pack_scan/upload_chunk', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_chunk(self, **kw):
        httpreq = request.httprequest
        upload_id = httpreq.form.get('upload_id') or ''
        index = int(httpreq.form.get('index') or -1)
        file = httpreq.files.get('chunk')
        if not upload_id or index < 0 or not file:
            return Response("bad request", status=400)

        meta_file = _meta_path(upload_id)
        if not os.path.exists(meta_file):
            _logger.warning("UPLOAD_CHUNK no_session id=%s idx=%s", upload_id, index)
            return Response("no session", status=404)

        meta = json.loads(open(meta_file, 'r', encoding='utf-8').read())
        expected = meta.get('last_index', -1) + 1
        if index != expected:
            _logger.warning("UPLOAD_CHUNK out_of_order id=%s idx=%s expected=%s", upload_id, index, expected)
            return Response("out_of_order", status=409)

        chunk = file.read()
        with open(meta['path'], 'ab') as out:
            out.write(chunk)

        meta['last_index'] = index
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f)

        _logger.info("UPLOAD_CHUNK ok id=%s idx=%s size=%s last=%s",
                    upload_id, index, len(chunk), meta['last_index'])

        return Response("OK", status=200, content_type='text/plain')

    @http.route('/pack_scan/finish_upload', type='json', auth='user', csrf=False)
    def finish_upload(self, **kw):
        params = dict(kw or {})
        if not params and request.httprequest.data:
            try:
                raw = json.loads(request.httprequest.data.decode('utf-8'))
                if isinstance(raw, dict):
                    params = raw.get('params') or raw
            except Exception:
                pass
        if not params:
            params = request.httprequest.form or {}

        upload_id = params.get('upload_id') or params.get('uploadId') or ''
        picking_id = int(params.get('picking_id') or 0)

        _logger.info("FINISH_UPLOAD recv: upload_id=%s picking_id=%s", upload_id, picking_id)

        if not upload_id:
            _logger.warning("FINISH_UPLOAD missing upload_id")
            return {'ok': False, 'msg': 'missing upload_id'}

        meta_file = _meta_path(upload_id)
        if not os.path.exists(meta_file):
            _logger.info("FINISH_UPLOAD already_finished id=%s", upload_id)
            return {'ok': True, 'msg': 'already finished or no session'}

        claimed_meta_file = _uploading_meta_path(upload_id)
        try:
            os.replace(meta_file, claimed_meta_file)
        except FileNotFoundError:
            _logger.info("FINISH_UPLOAD already_claimed id=%s", upload_id)
            return {'ok': True, 'msg': 'already claimed'}

        meta = json.loads(open(claimed_meta_file, 'r', encoding='utf-8').read())
        filepath = meta['path']
        mimetype = meta.get('mimetype') or 'video/webm'
        picking_id = int(meta.get('picking_id') or picking_id or 0)

        if not os.path.exists(filepath):
            _logger.warning("FINISH_UPLOAD missing_file id=%s file=%s", upload_id, filepath)
            try: os.remove(claimed_meta_file)
            except: pass
            return {'ok': False, 'msg': 'missing upload file'}

        _logger.info("FINISH_UPLOAD id=%s pick=%s file=%s size=%s",
                    upload_id, picking_id, filepath,
                    (os.path.getsize(filepath) if os.path.exists(filepath) else -1))

        t = threading.Thread(target=_bg_upload_to_drive,
                            args=(request.db, picking_id, filepath, mimetype),
                            daemon=True)
        t.start()

        try: os.remove(claimed_meta_file)
        except: pass
        return {'ok': True}
