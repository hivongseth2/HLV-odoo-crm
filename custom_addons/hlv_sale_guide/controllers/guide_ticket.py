# -*- coding: utf-8 -*-
"""API cho ngăn Ticket của trang /huong-dan: danh sách, chi tiết + thảo luận, tạo, trả lời.

Đọc/ghi bằng env thường — quyền xem ticket do record rule lo (theo hướng dẫn của ticket).
Tạo và trả lời là POST multipart (có csrf_token) vì kèm file: ảnh dán bằng Ctrl+V, video, PDF…

Đường dẫn nằm ngoài /huong-dan/ để không đụng route /huong-dan/<slug>/… của trang hướng dẫn.
"""

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.ticket_utils import split_quotes

TICKET_ROUTE = "/huong-dan-ticket"
LIST_LIMIT = 500


class GuideTicket(http.Controller):

    @http.route(f"{TICKET_ROUTE}/list", type="json", auth="user", methods=["POST"])
    def ticket_list(self, **kw):
        tickets = self._tickets().search([], limit=LIST_LIMIT)
        counts = tickets._message_counts()
        return [self._ticket_item(ticket, counts.get(ticket.id, 0)) for ticket in tickets]

    @http.route(f"{TICKET_ROUTE}/<int:ticket_id>", type="json", auth="user", methods=["POST"])
    def ticket_detail(self, ticket_id, **kw):
        ticket = self._ticket(ticket_id)
        # sudo sau khi đã đọc được ticket bằng env thường: tin và file đính kèm theo quyền của ticket.
        messages = ticket.sudo().message_ids.filtered(lambda m: m.message_type in ("comment", "email"))
        return {
            **self._ticket_item(ticket, len(messages)),
            "can_set_state": ticket._can_set_state(),
            "messages": [self._message_item(message) for message in messages.sorted("id")],
        }

    @http.route(f"{TICKET_ROUTE}/new", type="http", auth="user", methods=["POST"])
    def ticket_create(self, kind=None, guide_id=None, title=None, body=None, **kw):
        def create():
            ticket = self._tickets().create_from_page(
                kind, int(guide_id) if (guide_id or "").isdigit() else None, title,
                request.httprequest.form.getlist("quotes"), body, self._files(),
            )
            return {"id": ticket.id}
        return self._json_call(create)

    @http.route(f"{TICKET_ROUTE}/<int:ticket_id>/reply", type="http", auth="user", methods=["POST"])
    def ticket_reply(self, ticket_id, body=None, state=None, **kw):
        def reply():
            ticket = self._ticket(ticket_id)
            ticket.reply(body, self._files(), state or None)
            return {"id": ticket.id}
        return self._json_call(reply)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _tickets():
        if request.env.user.share:
            raise AccessError("Chỉ người dùng nội bộ.")
        return request.env["hlv.sale.guide.ticket"]

    def _ticket(self, ticket_id):
        ticket = self._tickets().search([("id", "=", ticket_id)], limit=1)
        if not ticket:
            raise UserError("Không tìm thấy ticket, hoặc bạn không có quyền xem.")
        return ticket

    @staticmethod
    def _files():
        """File đính kèm của request → list (tên, bytes) cho message_post."""
        return [
            (upload.filename or "file", upload.read())
            for upload in request.httprequest.files.getlist("files")
        ]

    @staticmethod
    def _json_call(func):
        """Chạy func, trả JSON. Lỗi người dùng → {"error": thông điệp} thay vì trang lỗi HTML của Odoo."""
        try:
            return request.make_json_response(func())
        except (UserError, AccessError) as exc:
            request.env.cr.rollback()
            return request.make_json_response({"error": str(exc.args[0] if exc.args else exc)}, status=400)

    @staticmethod
    def _ticket_item(ticket, message_count):
        guide = ticket.guide_id
        return {
            "id": ticket.id,
            "name": ticket.name,
            "kind": ticket.kind,
            "state": ticket.state,
            "quotes": split_quotes(ticket.quotes),
            "guide": {"id": guide.id, "name": guide.name, "slug": guide.slug} if guide else None,
            "guide_changed": ticket.guide_changed,
            "guide_version_asked": fields.Datetime.to_string(ticket.guide_published_on),
            "guide_version_now": fields.Datetime.to_string(guide.published_on),
            "author": ticket.create_uid.name,
            "mine": ticket.create_uid == request.env.user,
            "created_on": fields.Datetime.to_string(ticket.create_date),
            "last_message_on": fields.Datetime.to_string(ticket.last_message_on or ticket.create_date),
            "done_by": ticket.done_by_id.name or "",
            "message_count": message_count,
        }

    @staticmethod
    def _message_item(message):
        author = message.author_id
        return {
            "id": message.id,
            "author": author.name or message.email_from or "",
            "avatar": f"/web/image/res.partner/{author.id}/avatar_128" if author else "",
            "mine": author == request.env.user.partner_id,
            "date": fields.Datetime.to_string(message.date),
            # body là trường Html đã được Odoo lọc (sanitize) khi ghi — trang hiển thị thẳng.
            "body": str(message.body or ""),
            "attachments": [
                {
                    "id": att.id,
                    "name": att.name,
                    "mimetype": att.mimetype or "",
                    "size": att.file_size,
                    "url": f"/web/content/{att.id}",
                }
                for att in message.attachment_ids.sorted("id")
            ],
        }

