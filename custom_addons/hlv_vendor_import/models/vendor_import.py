# -*- coding: utf-8 -*-
"""Một lần nhập file Excel của NCC — việc của người bên mình (thu mua), NCC không phải làm gì.

Luồng: tải file → đọc theo mẫu của NCC (lần đầu: đề xuất mẫu, người dùng xem lại cột) → mỗi dòng: mã NCC
đã nhớ thì khớp luôn, chưa nhớ thì dò ứng viên rộng → Claude duyệt ứng viên (chạy nền) → người dùng xác
nhận → áp dụng: nhớ mã đã xác nhận, thay bảng tồn kho NCC.
"""

import base64

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.review_payload import VERDICT_MATCH, VERDICT_NONE, VERDICT_PROBABLE
from ..services.xlsx_grid import GridError, read_grid
from .import_utils import code_key, extract_rows, split_prefixes, stock_text

STATES = [
    ("draft", "Mới"),
    ("mapping", "Xem lại cột"),
    ("review", "Đang xác nhận"),
    ("done", "Đã áp dụng"),
]
AI_STATES = [
    ("none", "Chưa chạy"),
    ("queued", "Chờ chạy"),
    ("running", "Đang duyệt"),
    ("done", "Xong"),
    ("failed", "Lỗi"),
]


class HlvVendorImport(models.Model):
    _name = "hlv.vendor.import"
    _description = "Nhập file NCC"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Số", readonly=True, copy=False, default="Mới")
    # Chỉ công ty / cá nhân đứng riêng: mã NCC đã nhớ và tồn kho gắn theo NCC, chọn người liên hệ là tách đôi dữ liệu.
    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, tracking=True,
                                 domain="[('parent_id', '=', False)]")
    profile_id = fields.Many2one("hlv.vendor.import.profile", "Mẫu file",
                                 domain="[('partner_id', '=', partner_id)]")
    file = fields.Binary("File Excel", attachment=True, copy=False)
    file_name = fields.Char("Tên file", copy=False)
    user_id = fields.Many2one("res.users", "Người nhập", default=lambda self: self.env.user, readonly=True)
    state = fields.Selection(STATES, "Trạng thái", default="draft", required=True, tracking=True, copy=False)
    ai_state = fields.Selection(AI_STATES, "AI duyệt", default="none", required=True, copy=False)
    ai_error = fields.Char("Lỗi AI", readonly=True, copy=False)
    # Thời điểm luồng nền cầm việc / báo còn sống: cron vớt lại lần nhập "đang duyệt" quá lâu (luồng chết).
    ai_claimed_at = fields.Datetime(readonly=True, copy=False)
    applied_at = fields.Datetime("Áp dụng lúc", readonly=True, copy=False)
    applied_by = fields.Many2one("res.users", "Người áp dụng", readonly=True, copy=False)
    line_ids = fields.One2many("hlv.vendor.import.line", "import_id", "Dòng", copy=False)

    # Sửa mẫu ngay trên lần nhập (bước "Xem lại cột"), khỏi mở mẫu riêng.
    profile_header_row = fields.Integer(related="profile_id.header_row", readonly=False)
    profile_header_rows = fields.Selection(related="profile_id.header_rows", readonly=False)
    profile_sheet_name = fields.Char(related="profile_id.sheet_name", readonly=False)
    profile_code_prefixes = fields.Char(related="profile_id.code_prefixes", readonly=False)
    profile_brand = fields.Char(related="profile_id.brand", readonly=False)
    profile_column_ids = fields.One2many(related="profile_id.column_ids", readonly=False)

    line_count = fields.Integer("Số dòng", compute="_compute_counts")
    alias_count = fields.Integer("Khớp theo mã đã nhớ", compute="_compute_counts")
    ai_pending_count = fields.Integer("Chờ AI", compute="_compute_counts")
    match_count = fields.Integer("AI: khớp", compute="_compute_counts")
    probable_count = fields.Integer("AI: có thể", compute="_compute_counts")
    none_count = fields.Integer("Không có sản phẩm", compute="_compute_counts")
    todo_count = fields.Integer("Chưa xác nhận", compute="_compute_counts")
    confirmed_count = fields.Integer("Đã xác nhận có sản phẩm", compute="_compute_counts")

    @api.depends("line_ids.ai_state", "line_ids.ai_verdict", "line_ids.decision", "line_ids.match_source")
    def _compute_counts(self):
        for record in self:
            lines = record.line_ids
            record.line_count = len(lines)
            record.alias_count = len(lines.filtered(lambda line: line.match_source == "alias"))
            record.ai_pending_count = len(lines.filtered(lambda line: line.ai_state == "pending"))
            record.match_count = len(lines.filtered(lambda line: line.ai_verdict == VERDICT_MATCH))
            record.probable_count = len(lines.filtered(lambda line: line.ai_verdict == VERDICT_PROBABLE))
            record.none_count = len(lines.filtered(lambda line: line.ai_verdict == VERDICT_NONE))
            record.todo_count = len(lines.filtered(lambda line: line.decision == "pending"))
            record.confirmed_count = len(lines.filtered(lambda line: line.decision == "confirmed"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Mới") == "Mới":
                vals["name"] = self.env["ir.sequence"].next_by_code("hlv.vendor.import") or "Mới"
        return super().create(vals_list)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        self.profile_id = self.env["hlv.vendor.import.profile"].search(
            [("partner_id", "=", self.partner_id.id)], limit=1) if self.partner_id else False

    # =========================================================================
    # Đọc file
    # =========================================================================
    def _grid(self):
        self.ensure_one()
        if not self.file:
            raise UserError("Chưa tải file Excel lên.")
        try:
            return read_grid(base64.b64decode(self.file), self.profile_id.sheet_name)[1]
        except GridError as error:
            raise UserError(str(error))

    def action_read_file(self):
        """Đọc file. Lần đầu của NCC hoặc NCC đổi mẫu: dừng ở bước xem lại cột; đúng mẫu: đọc luôn."""
        self.ensure_one()
        if self.state == "done":
            raise UserError("Lần nhập này đã áp dụng. Tạo lần nhập mới cho file mới.")
        grid = self._grid()
        if not self.profile_id:
            self.profile_id = self.env["hlv.vendor.import.profile"].propose(self.partner_id, grid)
            self.state = "mapping"
            self.message_post(body="Lần đầu nhận file của NCC này: đã đề xuất mẫu file, xem lại các cột "
                                   "rồi bấm \"Đọc theo mẫu này\".")
            return True
        if not self.profile_id.matches(grid):
            self.profile_id.refresh_columns(grid)
            self.state = "mapping"
            self.message_post(body="Tiêu đề cột khác lần trước (NCC đổi mẫu?): đã đề xuất lại, xem lại các cột.")
            return True
        return self._load(grid)

    def action_refresh_columns(self):
        """Đổi dòng tiêu đề / sheet xong thì đề xuất lại cột theo chỗ mới."""
        self.ensure_one()
        self.profile_id.refresh_columns(self._grid())
        return True

    def action_confirm_columns(self):
        self.ensure_one()
        grid = self._grid()
        if not self.profile_id.matches(grid):
            # Người dùng đổi dòng tiêu đề / sheet mà chưa đề xuất lại: cột đang gán là của chỗ cũ.
            self.profile_id.refresh_columns(grid)
            self.message_post(body="Dòng tiêu đề vừa đổi: đã đề xuất lại cột theo chỗ mới, xem lại rồi bấm lại.")
            return True
        return self._load(grid)

    def _load(self, grid):
        """Tạo các dòng từ lưới theo mẫu, khớp mã đã nhớ, dò ứng viên, xếp hàng AI."""
        if self.ai_state in ("queued", "running"):
            raise UserError("AI đang duyệt các dòng cũ, đợi xong rồi đọc lại file.")
        profile = self.profile_id
        rows = extract_rows(grid, profile.first_data_index(), profile.column_specs())
        if not rows:
            raise UserError("Không đọc được dòng hàng nào dưới dòng tiêu đề %s." % profile.header_row)
        prefixes = split_prefixes(profile.code_prefixes)
        self.line_ids.unlink()
        lines = self.env["hlv.vendor.import.line"].create([{
            "import_id": self.id,
            "row_no": row["row"],
            "vendor_code": row["code"],
            "code_key": code_key(row["code"], prefixes) or False,
            "vendor_name": row["name"],
            "name_alt": row["name_alt"],
            "uom_name": row["uom"],
            "stock": row["stock"],
            "stock_display": stock_text(row["stock"]),
            "stock_total": sum(row["stock"].values()),
        } for row in rows])
        self.write({"state": "review", "ai_state": "none", "ai_error": False})
        self._match(lines, prefixes)
        return True

    def _match(self, lines, prefixes):
        """Mã đã nhớ → khớp luôn; còn lại dò ứng viên; không ứng viên nào → "không có", khỏi hỏi AI."""
        keys = {key for key in lines.mapped("code_key") if key}
        known = self.env["hlv.vendor.product.alias"].lookup(self.partner_id, keys)
        for line in lines:
            product = known.get(line.code_key)
            if product:
                line.write({"product_id": product.id, "decision": "confirmed", "match_source": "alias",
                            "ai_state": "skipped"})
                continue
            candidates = line.find_candidates(prefixes, self.profile_id.brand)
            if candidates:
                line.write({"candidate_ids": [(6, 0, candidates.ids)], "ai_state": "pending"})
            else:
                line.write({"ai_state": "skipped", "ai_verdict": VERDICT_NONE,
                            "ai_reason": "Không tìm thấy sản phẩm nào gần mã / tên này."})
        if lines.filtered(lambda line: line.ai_state == "pending"):
            self.env["hlv.vendor.import.ai"].queue(self)

    # =========================================================================
    # Duyệt / áp dụng
    # =========================================================================
    def action_run_ai(self):
        """Chạy lại AI cho các dòng còn chờ (sau lỗi API / mạng)."""
        self.ensure_one()
        if not self.line_ids.filtered(lambda line: line.ai_state == "pending"):
            raise UserError("Không còn dòng nào chờ AI duyệt.")
        self.env["hlv.vendor.import.ai"].queue(self)
        return True

    def action_accept_matches(self):
        """Nhận hết các dòng AI kết luận "khớp" mà người dùng chưa đụng tới."""
        self.ensure_one()
        lines = self.line_ids.filtered(
            lambda line: line.decision == "pending" and line.ai_verdict == VERDICT_MATCH and line.product_id)
        lines.write({"decision": "confirmed", "match_source": "ai"})
        return True

    def action_open_lines(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("hlv_vendor_import.action_vendor_import_line")
        action["domain"] = [("import_id", "=", self.id)]
        action["context"] = {"default_import_id": self.id, "search_default_todo": 1}
        action["name"] = "Dòng %s — %s" % (self.name, self.partner_id.display_name)
        return action

    def action_apply(self):
        """Nhớ mã đã xác nhận, thay tồn kho NCC bằng file này. Dòng chưa xác nhận vẫn vào bảng tồn, theo mã NCC."""
        self.ensure_one()
        if self.state != "review":
            raise UserError("Chỉ áp dụng được lần nhập đang xác nhận.")
        if self.ai_state in ("queued", "running"):
            raise UserError("AI đang duyệt, đợi xong rồi áp dụng.")
        confirmed = self.line_ids.filtered(lambda line: line.decision == "confirmed" and line.product_id)
        self.env["hlv.vendor.product.alias"].remember(self.partner_id, confirmed.filtered("code_key"))
        now = fields.Datetime.now()
        self.env["hlv.vendor.stock"].replace_for(self.partner_id, [{
            "product_id": line.product_id.id if line in confirmed else False,
            "vendor_code": line.vendor_code,
            "vendor_name": line.vendor_name,
            "uom_name": line.uom_name,
            "warehouse": warehouse,
            "qty": qty,
            "import_id": self.id,
            "date": now,
        } for line in self.line_ids for warehouse, qty in (line.stock or {}).items()])
        self.write({"state": "done", "applied_at": now, "applied_by": self.env.user.id})
        self.message_post(body="Đã áp dụng: %s dòng tồn, %s dòng khớp sản phẩm, %s dòng chưa khớp." % (
            len(self.line_ids), len(confirmed), len(self.line_ids) - len(confirmed)))
        return True
