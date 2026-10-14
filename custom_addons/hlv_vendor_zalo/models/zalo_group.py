# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ZaloGroup(models.Model):
    """Nhóm Zalo máy nghe đang ở trong. Tự tạo khi có tin đầu tiên; chỉ nhóm được bật "Ghi tin" mới lưu nội dung —
    tài khoản nghe có thể bị mời vào nhóm không liên quan, không lưu tin của họ."""

    _name = "hlv.zalo.group"
    _description = "Nhóm Zalo (máy nghe)"
    _order = "enabled desc, last_message_at desc, id desc"

    name = fields.Char(string="Tên nhóm", required=True)
    zalo_group_id = fields.Char(string="Mã nhóm Zalo", required=True, index=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner", string="Nhà cung cấp", index=True,
        domain="[('is_company', '=', True)]",
        help="NCC của nhóm. Tin trong nhóm hiện ở nút \"Tin Zalo\" trên báo giá của NCC này.",
    )
    enabled = fields.Boolean(
        string="Ghi tin", default=False,
        help="Bật thì lưu tin nhắn, ảnh, file của nhóm. Tắt: chỉ đếm số tin bỏ qua.",
    )
    active = fields.Boolean(default=True)
    note = fields.Text(string="Ghi chú")
    message_ids = fields.One2many("hlv.zalo.message", "group_id", string="Tin nhắn")
    message_count = fields.Integer(string="Số tin đã lưu", compute="_compute_message_count")
    last_message_at = fields.Datetime(string="Tin gần nhất", readonly=True)
    # Mốc AI đã đọc tới (id tin) — cron chỉ gọi AI khi có tin mới từ phía NCC sau mốc này (models/zalo_ai.py).
    ai_last_message_id = fields.Integer(string="AI đọc tới tin", readonly=True)
    skipped_count = fields.Integer(
        string="Tin bỏ qua", readonly=True,
        help="Số tin tới khi nhóm chưa bật \"Ghi tin\" — không lưu nội dung.",
    )

    _sql_constraints = [
        ("zalo_group_id_unique", "unique(zalo_group_id)", "Mỗi nhóm Zalo chỉ có một bản ghi."),
    ]

    @api.depends("message_ids")
    def _compute_message_count(self):
        counts = dict(self.env["hlv.zalo.message"]._read_group(
            [("group_id", "in", self.ids)], ["group_id"], ["__count"],
        ))
        for group in self:
            group.message_count = counts.get(group, 0)

    @api.model
    def _get_or_create(self, zalo_group_id, name):
        """Nhóm theo mã Zalo; chưa có thì tạo (tắt "Ghi tin"). Tên nhóm đổi trên Zalo thì cập nhật theo."""
        group = self.with_context(active_test=False).search([("zalo_group_id", "=", zalo_group_id)], limit=1)
        if not group:
            return self.create({"zalo_group_id": zalo_group_id, "name": name or zalo_group_id})
        if name and group.name != name:
            group.name = name
        return group

    def action_open_messages(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_zalo.action_zalo_message")
        action["domain"] = [("group_id", "=", self.id)]
        action["context"] = {"default_group_id": self.id}
        return action
