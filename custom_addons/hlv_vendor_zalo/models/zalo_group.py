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
    ai_last_message_id = fields.Integer(string="AI đọc tới tin #", readonly=True)
    ai_pending_count = fields.Integer(string="Tin chờ AI đọc", compute="_compute_ai_status",
                                      help="Tin phía NCC (không phải nhân viên mình) tới sau lượt AI đọc gần nhất.")
    ai_last_run_id = fields.Many2one("hlv.zalo.ai.run", string="AI đọc gần nhất", compute="_compute_ai_status")
    ai_run_ids = fields.One2many("hlv.zalo.ai.run", "group_id", string="Nhật ký AI")
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

    def _ai_pending_domain(self):
        """Tin phía NCC sau mốc AI đã đọc — có tin như vậy thì cron mới gọi AI cho nhóm."""
        self.ensure_one()
        return [("group_id", "=", self.id), ("id", ">", self.ai_last_message_id),
                ("is_self", "=", False), ("member_id.kind", "!=", "staff")]

    @api.depends("ai_last_message_id", "message_ids", "ai_run_ids")
    def _compute_ai_status(self):
        Message = self.env["hlv.zalo.message"]
        for group in self:
            group.ai_pending_count = Message.search_count(group._ai_pending_domain()) if group.id else 0
            group.ai_last_run_id = group.ai_run_ids[:1]

    def action_ai_read_now(self):
        """AI đọc nhóm ngay (không chờ cron) rồi mở dòng nhật ký của lượt đó. Người bấm chỉ cần sửa được nhóm (thu
        mua); nhật ký / đề xuất là dữ liệu hệ thống ghi — không nhóm quyền nào được tạo tay — nên chạy sudo như cron."""
        self.ensure_one()
        self.check_access("write")
        run = self.env["hlv.zalo.ai"].sudo()._read_group_now(self.sudo())
        return {"type": "ir.actions.act_window", "res_model": "hlv.zalo.ai.run", "res_id": run.id,
                "view_mode": "form", "target": "current"}

    def action_open_ai_runs(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_zalo.action_zalo_ai_run")
        action["domain"] = [("group_id", "=", self.id)]
        return action

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
