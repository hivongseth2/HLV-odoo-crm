# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.osv import expression

from .zalo_utils import IMAGE_MIMETYPES, MESSAGE_KINDS, clean_id, clip, message_kind, ts_to_utc

TEXT_MAX = 20000
TITLE_MAX = 255
URL_MAX = 2000
MEDIA_STATES = [
    ("none", "Không có"),
    ("waiting", "Chờ máy nghe gửi"),
    ("done", "Đã nhận"),
    ("failed", "Máy nghe không tải được"),
]


class ZaloMessage(models.Model):
    """Một tin trong nhóm Zalo, máy nghe gửi lên. Chỉ đọc — Odoo không gửi tin nào vào Zalo."""

    _name = "hlv.zalo.message"
    _description = "Tin nhắn nhóm Zalo"
    _order = "sent_at desc, id desc"
    _rec_name = "body"

    msg_id = fields.Char(string="Mã tin Zalo", required=True, index=True, readonly=True)
    group_id = fields.Many2one("hlv.zalo.group", string="Nhóm", required=True, index=True, ondelete="cascade",
                               readonly=True)
    partner_id = fields.Many2one(related="group_id.partner_id", string="NCC", store=True, index=True)
    member_id = fields.Many2one("hlv.zalo.member", string="Người gửi", index=True, readonly=True)
    member_kind = fields.Selection(related="member_id.kind", string="Là")
    is_self = fields.Boolean(string="Tài khoản nghe gửi", readonly=True)
    sent_at = fields.Datetime(string="Lúc", index=True, readonly=True)
    kind = fields.Selection(MESSAGE_KINDS, string="Loại", readonly=True)
    msg_type = fields.Char(string="msgType gốc", readonly=True)
    body = fields.Text(string="Nội dung", readonly=True)
    # Tin trả lời (trích tin khác): giữ mã + chữ tin được trích, gắn bản ghi nếu tin đó đã có trong Odoo.
    quote_msg_id = fields.Char(string="Mã tin được trích", index=True, readonly=True)
    quote_text = fields.Text(string="Trích", readonly=True)
    quote_sender = fields.Char(string="Người viết tin được trích", readonly=True)
    quote_message_id = fields.Many2one("hlv.zalo.message", string="Trả lời tin", readonly=True, ondelete="set null")
    mention_ids = fields.Many2many("hlv.zalo.member", string="Nhắc tới", readonly=True)
    media_title = fields.Char(string="Tên file", readonly=True)
    media_url = fields.Char(string="Link Zalo gốc", readonly=True,
                            help="Link CDN Zalo — hết hạn sau một thời gian, file thật nằm ở Đính kèm.")
    media_state = fields.Selection(MEDIA_STATES, string="File", default="none", readonly=True)
    attachment_ids = fields.Many2many("ir.attachment", string="Đính kèm", readonly=True)
    reaction_ids = fields.One2many("hlv.zalo.reaction", "message_id", string="Thả cảm xúc")
    ai_read = fields.Boolean(string="AI đã đọc", compute="_compute_ai_read", search="_search_ai_read",
                             help="Tin nằm trước mốc AI đã đọc tới của nhóm.")

    _sql_constraints = [
        ("msg_id_unique", "unique(msg_id)", "Tin Zalo này đã có."),
    ]

    @api.depends("group_id.ai_last_message_id")
    def _compute_ai_read(self):
        for message in self:
            message.ai_read = bool(message.id) and message.id <= message.group_id.ai_last_message_id

    def _search_ai_read(self, operator, value):
        # Mốc nằm trên từng nhóm: "đã đọc" = OR theo nhóm (cùng nhóm và id ≤ mốc của nhóm đó).
        groups = self.env["hlv.zalo.group"].with_context(active_test=False).search([("ai_last_message_id", ">", 0)])
        read = expression.OR([[("group_id", "=", g.id), ("id", "<=", g.ai_last_message_id)] for g in groups]) \
            if groups else expression.FALSE_DOMAIN
        positive = (operator == "=") == bool(value)
        return read if positive else ["!"] + read

    def _image_attachments(self):
        """File ảnh máy nghe đã tải về cho các tin này (ảnh đầu tiên mỗi tin) — rỗng nếu chưa về / không phải ảnh."""
        return self.mapped(lambda m: m.attachment_ids.filtered(lambda a: a.mimetype in IMAGE_MIMETYPES)[:1])

    @api.depends("member_id.name", "body", "kind", "media_title")
    def _compute_display_name(self):
        kinds = dict(MESSAGE_KINDS)
        for message in self:
            text = (message.body or message.media_title or f"[{kinds.get(message.kind, '')}]").replace("\n", " ")
            message.display_name = f"{message.member_id.name or '?'}: {text[:60]}"

    # ------------------------------------------------------------------ nhận từ máy nghe
    @api.model
    def _ingest(self, messages, reactions):
        """Ghi một lô tin + thả cảm xúc máy nghe gửi lên (đã sudo). Gửi trùng (máy nghe gửi lại sau khi rớt mạng,
        lấy bù tin cũ) thì bỏ qua theo mã tin. Trả số liệu cho máy nghe + danh sách mã tin cần gửi file."""
        stats = {"stored": 0, "duplicate": 0, "skipped": 0, "invalid": 0, "reactions": 0}
        valid = [m for m in messages if isinstance(m, dict) and clean_id(m.get("msg_id")) and clean_id(m.get("group_id"))]
        stats["invalid"] = len(messages) - len(valid)
        known = set(self.search([("msg_id", "in", [clean_id(m["msg_id"]) for m in valid])]).mapped("msg_id"))
        groups = {}
        created = self.browse()
        for raw in valid:
            msg_id = clean_id(raw["msg_id"])
            if msg_id in known:
                stats["duplicate"] += 1
                continue
            group = self._ingest_group(raw, groups)
            if not group.enabled:
                group.skipped_count += 1
                stats["skipped"] += 1
                continue
            created |= self.create(self._message_vals(raw, group))
            known.add(msg_id)
        stats["stored"] = len(created)
        self._link_quotes(created)
        stats["reactions"] = self.env["hlv.zalo.reaction"]._ingest(reactions)
        waiting = self.search([("media_state", "=", "waiting"), ("msg_id", "in", [clean_id(m["msg_id"]) for m in valid])])
        return dict(stats, media_wanted=waiting.mapped("msg_id"))

    def _ingest_group(self, raw, cache):
        group_key = clean_id(raw["group_id"])
        if group_key not in cache:
            cache[group_key] = self.env["hlv.zalo.group"]._get_or_create(group_key, clip(raw.get("group_name"), 255))
        return cache[group_key]

    def _message_vals(self, raw, group):
        sent_at = ts_to_utc(raw.get("ts")) or fields.Datetime.now()
        member = self.env["hlv.zalo.member"]._get_or_create(
            clean_id(raw.get("sender_uid")) or "?", clip(raw.get("sender_name"), 255), group,
        )
        if not member.last_seen_at or member.last_seen_at < sent_at:
            member.last_seen_at = sent_at
        if not group.last_message_at or group.last_message_at < sent_at:
            group.last_message_at = sent_at
        attachment = raw.get("attachment") if isinstance(raw.get("attachment"), dict) else {}
        media_url = clip(attachment.get("href"), URL_MAX)
        quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
        mention_uids = [clean_id(uid) for uid in raw.get("mentions") or [] if clean_id(uid)]
        return {
            "msg_id": clean_id(raw["msg_id"]),
            "group_id": group.id,
            "member_id": member.id,
            "is_self": bool(raw.get("is_self")),
            "sent_at": sent_at,
            "kind": message_kind(raw.get("msg_type"), bool(media_url)),
            "msg_type": clip(raw.get("msg_type"), 64),
            "body": clip(raw.get("text"), TEXT_MAX),
            "quote_msg_id": clean_id(quote.get("msg_id")) or False,
            "quote_text": clip(quote.get("text"), TEXT_MAX) or False,
            "quote_sender": clip(quote.get("sender_name"), 255) or False,
            "mention_ids": [(6, 0, self.env["hlv.zalo.member"].search([("zalo_uid", "in", mention_uids)]).ids)],
            "media_title": clip(attachment.get("title"), TITLE_MAX) or False,
            "media_url": media_url or False,
            "media_state": "waiting" if media_url else "none",
        }

    def _link_quotes(self, created):
        """Gắn tin trả lời với tin được trích, theo cả hai chiều: lấy bù tin cũ có thể tới SAU tin trả lời nó."""
        if not created:
            return
        for message in created.filtered("quote_msg_id"):
            message.quote_message_id = self.search([("msg_id", "=", message.quote_msg_id)], limit=1)
        orphans = self.search([("quote_msg_id", "in", created.mapped("msg_id")), ("quote_message_id", "=", False)])
        by_id = {message.msg_id: message for message in created}
        for message in orphans:
            message.quote_message_id = by_id[message.quote_msg_id]

    @api.model
    def _attach_media(self, msg_id, filename, data, mimetype):
        """File máy nghe đã tải từ Zalo cho tin msg_id. Trả False nếu không có tin đó (nhóm chưa bật / mã sai)."""
        message = self.search([("msg_id", "=", clean_id(msg_id))], limit=1)
        if not message:
            return False
        attachment = self.env["ir.attachment"].create({
            "name": filename or message.media_title or f"zalo-{message.msg_id}",
            "datas": base64.b64encode(data),
            "mimetype": mimetype or False,
            "res_model": self._name,
            "res_id": message.id,
        })
        message.write({"attachment_ids": [(4, attachment.id)], "media_state": "done"})
        return True

    @api.model
    def _mark_media_failed(self, msg_id):
        """Máy nghe báo không tải được file (link Zalo hết hạn / quá cỡ)."""
        self.search([("msg_id", "=", clean_id(msg_id)), ("media_state", "=", "waiting")]).media_state = "failed"
