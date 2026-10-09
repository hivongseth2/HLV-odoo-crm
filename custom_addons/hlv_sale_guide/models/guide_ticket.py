# -*- coding: utf-8 -*-
"""Ticket về hướng dẫn: câu hỏi, hoặc yêu cầu chỉnh sửa, mở từ ngăn bên trái của /huong-dan.

Thảo luận và file đính kèm dùng chatter của mail (mail.thread) thay vì tự làm bảng tin nhắn:
người hỏi và nhóm Quản lý hướng dẫn được theo dõi nên nhận thông báo Odoo khi có tin mới, quản
lý trả lời được cả trong backend, ảnh/video lưu thành ir.attachment như mọi chatter khác.
"""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import plaintext2html

from .ticket_utils import check_uploads, clean_quote, ticket_title

MANAGER_GROUP = "hlv_sale_guide.group_guide_manager"
STATE_EVENTS = {"done": "✔ Đã đánh dấu: đã xử lý", "open": "↺ Đã mở lại ticket"}


class SaleGuideTicket(models.Model):
    _name = "hlv.sale.guide.ticket"
    _description = "Ticket hướng dẫn"
    _inherit = ["mail.thread"]
    # "open" > "done" theo chữ cái nên state desc là ticket chưa xử lý lên đầu.
    _order = "state desc, last_message_on desc, id desc"
    # Ai đọc được ticket là được thảo luận. Sửa ticket (tiêu đề, trạng thái) vẫn cần quyền ghi —
    # người dùng thường chỉ có đọc + tạo, đổi trạng thái đi qua set_state() có kiểm quyền riêng.
    _mail_post_access = "read"

    name = fields.Char(string="Tiêu đề", required=True)
    kind = fields.Selection(
        [("question", "Câu hỏi"), ("request", "Yêu cầu chỉnh sửa")],
        string="Loại", required=True, default="question",
    )
    state = fields.Selection(
        [("open", "Chưa xử lý"), ("done", "Đã xử lý")],
        string="Trạng thái", required=True, default="open", readonly=True, index=True,
    )
    guide_id = fields.Many2one(
        "hlv.sale.guide", string="Hướng dẫn", ondelete="set null", index=True,
        help="Để trống: câu hỏi / yêu cầu chung, VD xin thêm hướng dẫn mới.",
    )
    quote = fields.Text(
        string="Đoạn được đánh dấu",
        help="Đoạn người hỏi bôi đen trong hướng dẫn; bấm vào trên trang /huong-dan là nhảy tới đoạn đó.",
    )
    done_by_id = fields.Many2one("res.users", string="Xử lý bởi", readonly=True)
    done_on = fields.Datetime(string="Xử lý lúc", readonly=True)
    last_message_on = fields.Datetime(string="Trao đổi gần nhất", readonly=True, default=fields.Datetime.now)

    @api.model
    def create_from_page(self, kind, guide_id, title, quote, body, files):
        """Tạo ticket từ trang /huong-dan kèm tin đầu tiên.

        files: list (tên, bytes). Trả ticket mới. Thiếu cả nội dung lẫn file → UserError.
        """
        body = (body or "").strip()
        if not body and not files:
            raise UserError(_("Hãy viết câu hỏi / yêu cầu, hoặc dán ảnh vào."))
        # search thay vì browse: áp quyền xem hướng dẫn ("Chỉ cho nhóm") của người hỏi.
        guide = self.env["hlv.sale.guide"].search([("id", "=", guide_id)], limit=1) if guide_id else None
        # mail_create_nolog: không ghi tin "đã tạo" — tin đầu tiên của người hỏi đã nói điều đó.
        ticket = self.with_context(mail_create_nolog=True).create({
            "kind": kind if kind in ("question", "request") else "question",
            "guide_id": guide.id if guide else False,
            "name": ticket_title(title, body, guide.name if guide else _("Ticket không tiêu đề")),
            "quote": clean_quote(quote) or False,
        })
        # sudo: thêm người khác làm người theo dõi cần quyền ghi, người tạo ticket không có.
        managers = self.env.ref(MANAGER_GROUP).sudo().users.filtered("active")
        ticket.sudo().message_subscribe(partner_ids=managers.partner_id.ids)
        ticket._post(body, files)
        return ticket

    def reply(self, body, files, state=None):
        """Thêm một tin vào thảo luận; state ("done" / "open") thì đổi trạng thái luôn.

        Không có nội dung, file, cũng không đổi trạng thái → UserError.
        """
        self.ensure_one()
        body = (body or "").strip()
        event = self.set_state(state) if state and state != self.state else None
        if not body and not files and not event:
            raise UserError(_("Tin nhắn đang trống."))
        self._post(body, files, event)

    def set_state(self, state):
        """Đổi trạng thái, trả dòng sự kiện để ghi vào thảo luận. Chỉ người hỏi hoặc quản lý."""
        self.ensure_one()
        if state not in STATE_EVENTS:
            raise UserError(_("Trạng thái không hợp lệ."))
        if not self._can_set_state():
            raise AccessError(_("Chỉ người hỏi hoặc quản lý hướng dẫn được đổi trạng thái ticket."))
        done = state == "done"
        # sudo: người hỏi không có quyền ghi ticket — quyền đã kiểm ở _can_set_state.
        self.sudo().write({
            "state": state,
            "done_by_id": self.env.user.id if done else False,
            "done_on": fields.Datetime.now() if done else False,
        })
        return STATE_EVENTS[state]

    def _can_set_state(self):
        self.ensure_one()
        return self.create_uid == self.env.user or self.env.user.has_group(MANAGER_GROUP)

    def _post(self, body, files, event=None):
        """Ghi một tin vào chatter: dòng sự kiện (nếu có) + nội dung chữ + file đính kèm."""
        try:
            check_uploads([len(content) for _name, content in files])
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        html = Markup()
        if event:
            html += Markup('<p class="hlv-ticket-event"><b>%s</b></p>') % event
        if body:
            html += plaintext2html(body)
        self.message_post(
            body=html, message_type="comment", subtype_xmlid="mail.mt_comment", attachments=files,
        )
        # Người đã tham gia thảo luận thì nhận thông báo các tin sau (không cần quyền ghi khi tự theo dõi).
        self.message_subscribe(partner_ids=self.env.user.partner_id.ids)
        self.sudo().write({"last_message_on": fields.Datetime.now()})

    def _message_counts(self):
        """{id ticket: số tin thảo luận} cho self, một truy vấn."""
        groups = self.env["mail.message"].sudo()._read_group(
            [("model", "=", self._name), ("res_id", "in", self.ids), ("message_type", "=", "comment")],
            ["res_id"], ["__count"],
        )
        return dict(groups)

    def action_mark_done(self):
        for ticket in self:
            ticket.reply("", [], "done")

    def action_reopen(self):
        for ticket in self:
            ticket.reply("", [], "open")

    def action_open_page(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"/huong-dan?t={self.id}", "target": "new"}
