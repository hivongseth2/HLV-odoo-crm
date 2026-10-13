# -*- coding: utf-8 -*-
"""Cửa nhận tin của máy nghe Zalo (chạy ngoài Odoo). Chỉ nhận, không bao giờ gửi gì ngược vào Zalo.

POST /api/zalo-listener/events  JSON {"listener", "status", "messages": [...], "reactions": [...]}
POST /api/zalo-listener/media   multipart msg_id + file   (hoặc msg_id + failed=1 khi không tải được)
Cả hai cần header X-API-Key = khoá trong Cài đặt → Hỏi giá NCC.
"""

import json

from odoo import http
from odoo.addons.misa_fetch_po_button.utils.api_key import api_key_matches
from odoo.http import request

from ..models.res_config_settings import INGEST_KEY_PARAM


# Một lô quá lớn là máy nghe gửi sai — chặn để một request không giữ transaction quá lâu.
MAX_BATCH = 500
MAX_MEDIA_BYTES = 25 * 1024 * 1024


class ZaloIngest(http.Controller):

    def _authorized(self):
        expected = request.env["ir.config_parameter"].sudo().get_param(INGEST_KEY_PARAM)
        return api_key_matches(request.httprequest.headers.get("X-API-Key"), expected)

    @staticmethod
    def _json(data, status=200):
        return request.make_json_response(data, status=status)

    @http.route("/api/zalo-listener/events", type="http", auth="public", methods=["POST"], csrf=False,
                save_session=False)
    def events(self, **_kwargs):
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, status=401)
        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            return self._json({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return self._json({"ok": False, "error": "invalid_json"}, status=400)
        messages = payload.get("messages") or []
        reactions = payload.get("reactions") or []
        if not isinstance(messages, list) or not isinstance(reactions, list) or len(messages) + len(reactions) > MAX_BATCH:
            return self._json({"ok": False, "error": "bad_batch", "max": MAX_BATCH}, status=400)
        env = request.env(su=True)
        env["hlv.zalo.listener"]._report(payload.get("listener"), payload.get("status"))
        result = env["hlv.zalo.message"]._ingest(messages, reactions)
        return self._json(dict(result, ok=True))

    @http.route("/api/zalo-listener/media", type="http", auth="public", methods=["POST"], csrf=False,
                save_session=False)
    def media(self, msg_id=None, failed=None, **_kwargs):
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, status=401)
        env = request.env(su=True)
        if failed:
            env["hlv.zalo.message"]._mark_media_failed(msg_id)
            return self._json({"ok": True})
        upload = request.httprequest.files.get("file")
        if not msg_id or not upload:
            return self._json({"ok": False, "error": "missing_file"}, status=400)
        data = upload.read(MAX_MEDIA_BYTES + 1)
        if len(data) > MAX_MEDIA_BYTES:
            env["hlv.zalo.message"]._mark_media_failed(msg_id)
            return self._json({"ok": False, "error": "too_large", "max": MAX_MEDIA_BYTES}, status=413)
        stored = env["hlv.zalo.message"]._attach_media(msg_id, upload.filename, data, upload.mimetype)
        # Không có tin (nhóm chưa bật / đã xoá): trả ok để máy nghe khỏi gửi lại mãi.
        return self._json({"ok": True, "stored": stored})
