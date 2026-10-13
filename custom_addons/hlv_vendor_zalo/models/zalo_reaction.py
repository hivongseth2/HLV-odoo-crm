# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .zalo_utils import clean_id, clip, reaction_label, ts_to_utc


class ZaloReaction(models.Model):
    """Thả cảm xúc vào một tin (tim, like…) — nhóm hay dùng thả tim để "duyệt". Zalo gửi kèm mã tin đích; tin đích
    chưa có trong Odoo (nhóm chưa bật, tin trước khi có máy nghe) thì bỏ qua."""

    _name = "hlv.zalo.reaction"
    _description = "Thả cảm xúc nhóm Zalo"
    _order = "reacted_at desc, id desc"

    message_id = fields.Many2one("hlv.zalo.message", string="Tin", required=True, index=True, ondelete="cascade")
    member_id = fields.Many2one("hlv.zalo.member", string="Người thả", index=True)
    icon = fields.Char(string="Mã cảm xúc")
    label = fields.Char(string="Cảm xúc", compute="_compute_label")
    reacted_at = fields.Datetime(string="Lúc")

    @api.depends("icon")
    def _compute_label(self):
        for reaction in self:
            reaction.label = reaction_label(reaction.icon)

    @api.model
    def _ingest(self, reactions):
        """Ghi thả cảm xúc vào tin đã lưu; trùng (cùng tin, người, biểu tượng, lúc) thì bỏ. Trả số bản ghi mới."""
        Message = self.env["hlv.zalo.message"]
        created = 0
        for raw in reactions or []:
            if not isinstance(raw, dict):
                continue
            message = Message.search([("msg_id", "=", clean_id(raw.get("target_msg_id")))], limit=1)
            if not message:
                continue
            member = self.env["hlv.zalo.member"]._get_or_create(
                clean_id(raw.get("sender_uid")) or "?", clip(raw.get("sender_name"), 255), message.group_id,
            )
            vals = {
                "message_id": message.id,
                "member_id": member.id,
                "icon": clip(raw.get("icon"), 32),
                "reacted_at": ts_to_utc(raw.get("ts")) or fields.Datetime.now(),
            }
            if not self.search_count([(key, "=", value) for key, value in vals.items()]):
                self.create(vals)
                created += 1
        return created
