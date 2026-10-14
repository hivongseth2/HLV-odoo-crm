# -*- coding: utf-8 -*-
"""System prompt cho Claude kiểm map nhầm — sửa trên Odoo, không cần nâng cấp module.

Một bản ghi duy nhất. Bản mặc định là data/prompt_defaults/match_system_prompt.md: tạo khi cài, nâng cấp
module KHÔNG ghi đè bản đã sửa (muốn lấy bản mặc định mới thì bấm "Về bản mặc định"). Mỗi lần sửa lưu
bản cũ vào lịch sử để quay lại được — prompt hỏng là mọi lần kiểm sau kết luận sai.

Sửa prompt là phiên bản mới: vân tay cặp đổi theo (match_payload.pair_fingerprint), nên lần kiểm sau hỏi
lại AI mọi cặp thay vì dùng lại kết luận theo prompt cũ — lần đó tốn tiền như lần kiểm đầu.
Cùng cách làm với prompt trợ lý tạo mã (hlv_product_agent/models/product_agent_prompt.py).
"""

from odoo import _, api, fields, models
from odoo.tools import file_open

from ..services.match_payload import prompt_version
from .shopee_product_check_line import LINK_EDITOR_GROUP

DEFAULT_FILE = "hlv_shopee_product_check/data/prompt_defaults/match_system_prompt.md"


class HlvShopeeCheckPrompt(models.Model):
    _name = "hlv.shopee.check.prompt"
    _description = "Prompt AI kiểm map nhầm Shopee"

    name = fields.Char("Tên", required=True, default="Prompt AI kiểm map nhầm Shopee")
    content = fields.Text("Nội dung", required=True)
    version = fields.Char("Phiên bản", compute="_compute_version",
                          help="Đổi khi nội dung đổi; lần kiểm sau hỏi lại AI mọi cặp theo bản mới.")
    revision_ids = fields.One2many("hlv.shopee.check.prompt.revision", "prompt_id", string="Lịch sử sửa")
    # Quản lý bán hàng ngoài nhóm chỉ được đọc (ir.model.access): khoá ô trên form thay vì để gõ rồi lỗi khi lưu.
    can_edit = fields.Boolean(compute="_compute_can_edit")

    @api.depends("content")
    def _compute_version(self):
        for prompt in self:
            prompt.version = prompt_version(prompt.content)

    @api.depends_context("uid")
    def _compute_can_edit(self):
        can_edit = self.env.user.has_group(LINK_EDITOR_GROUP) or self.env.user.has_group("base.group_system")
        for prompt in self:
            prompt.can_edit = can_edit

    @api.model
    def _default_content(self):
        # file_open của Odoo 18 không nhận encoding: đọc byte rồi tự giải mã UTF-8 (prompt tiếng Việt có dấu).
        with file_open(DEFAULT_FILE, "rb") as handle:
            return handle.read().decode("utf-8").strip() + "\n"

    @api.model
    def _ensure_default(self):
        """Tạo bản ghi từ file mặc định nếu chưa có. Gọi từ data XML mỗi lần cài / nâng cấp."""
        if not self.sudo().search_count([]):
            self.sudo().create({"content": self._default_content()})

    @api.model
    def current(self):
        """(nội dung, phiên bản) prompt đang dùng. Bản ghi bị xoá / trống thì dùng file mặc định."""
        content = self.sudo().search([], limit=1).content or self._default_content()
        return content, prompt_version(content)

    @api.model
    def action_open(self):
        """Menu mở thẳng form của bản ghi duy nhất."""
        self._ensure_default()
        return {
            "type": "ir.actions.act_window",
            "name": _("Prompt AI kiểm map nhầm"),
            "res_model": self._name,
            "res_id": self.search([], limit=1).id,
            "view_mode": "form",
        }

    def write(self, vals):
        if "content" in vals:
            changed = self.filtered(lambda prompt: (prompt.content or "") != (vals["content"] or ""))
            self.env["hlv.shopee.check.prompt.revision"].sudo().create([
                {"prompt_id": prompt.id, "content": prompt.content} for prompt in changed
            ])
        return super().write(vals)

    def action_reset_default(self):
        """Đưa về bản mặc định đi kèm module (bản đang dùng vẫn còn trong lịch sử)."""
        for prompt in self:
            prompt.content = self._default_content()


class HlvShopeeCheckPromptRevision(models.Model):
    _name = "hlv.shopee.check.prompt.revision"
    _description = "Bản cũ của prompt AI kiểm map nhầm Shopee"
    _order = "id desc"

    prompt_id = fields.Many2one("hlv.shopee.check.prompt", required=True, ondelete="cascade", index=True)
    content = fields.Text("Nội dung", readonly=True)

    def action_restore(self):
        """Quay lại bản này. Bản đang dùng tự được lưu vào lịch sử (qua write)."""
        self.ensure_one()
        self.prompt_id.content = self.content
