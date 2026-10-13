# -*- coding: utf-8 -*-
from odoo import api, fields, models

MEMBER_KINDS = [
    ("unknown", "Chưa rõ"),
    ("vendor", "Người của NCC"),
    ("staff", "Nhân viên mình"),
]


class ZaloMember(models.Model):
    """Người gửi tin trong các nhóm (theo uid Zalo). Đánh dấu ai là người của NCC, ai là nhân viên mình — giai đoạn
    sau dùng để biết câu nào là sale hỏi, câu nào là NCC trả lời."""

    _name = "hlv.zalo.member"
    _description = "Thành viên nhóm Zalo"
    _order = "kind, name"

    name = fields.Char(string="Tên Zalo", required=True)
    zalo_uid = fields.Char(string="UID Zalo", required=True, index=True, readonly=True)
    kind = fields.Selection(MEMBER_KINDS, string="Là", required=True, default="unknown")
    partner_id = fields.Many2one(
        "res.partner", string="NCC", index=True,
        help="Người của NCC: NCC họ đại diện (thường trùng NCC của nhóm).",
    )
    user_id = fields.Many2one("res.users", string="Tài khoản Odoo", help="Nhân viên mình: tài khoản Odoo của họ.")
    group_ids = fields.Many2many("hlv.zalo.group", string="Có mặt ở nhóm", readonly=True)
    last_seen_at = fields.Datetime(string="Gửi tin gần nhất", readonly=True)

    _sql_constraints = [
        ("zalo_uid_unique", "unique(zalo_uid)", "Mỗi người Zalo chỉ có một bản ghi."),
    ]

    @api.model
    def _get_or_create(self, zalo_uid, name, group):
        """Người gửi theo uid; chưa có thì tạo (Chưa rõ). Ghi nhận có mặt ở nhóm; đổi tên Zalo thì cập nhật."""
        member = self.search([("zalo_uid", "=", zalo_uid)], limit=1)
        if not member:
            return self.create({"zalo_uid": zalo_uid, "name": name or zalo_uid, "group_ids": [(4, group.id)]})
        vals = {}
        if name and member.name != name:
            vals["name"] = name
        if group not in member.group_ids:
            vals["group_ids"] = [(4, group.id)]
        if vals:
            member.write(vals)
        return member
