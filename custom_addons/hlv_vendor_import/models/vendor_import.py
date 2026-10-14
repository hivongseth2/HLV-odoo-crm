# -*- coding: utf-8 -*-
"""Một lần nhập file Excel của NCC — việc của người bên mình (thu mua), NCC không phải làm gì.

Luồng: tải file → đọc theo mẫu của NCC (lần đầu: đề xuất mẫu, người dùng xem lại cột) → mỗi dòng: mã NCC
đã nhớ thì khớp luôn, chưa nhớ thì dò ứng viên rộng → Claude duyệt ứng viên (chạy nền) → người dùng xác
nhận → áp dụng: nhớ mã đã xác nhận; file có cột tồn thì thay bảng tồn kho NCC, có cột giá thì cập nhật bảng giá
NCC (từng mã, từ ngày áp dụng).
"""

import base64

from odoo import api, fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import VAT_SELECTION
from odoo.exceptions import UserError

from ..services.review_payload import VERDICT_MATCH, VERDICT_NONE, VERDICT_PROBABLE
from ..services.xlsx_grid import GridError, read_grid
from .import_utils import code_key, extract_rows, fold, price_pair, read_vat, split_prefixes, stock_text

VAT_CODES = tuple(code for code, _label in VAT_SELECTION)

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
    # File giá NCC hay ghi "áp dụng từ ngày …" (có khi ở tương lai) — trước ngày đó vẫn dùng giá cũ.
    price_date = fields.Date("Giá áp dụng từ", default=fields.Date.context_today, copy=False)
    has_stock = fields.Boolean("File có tồn", compute="_compute_kinds")
    has_price = fields.Boolean("File có giá", compute="_compute_kinds")

    # Sửa mẫu ngay trên lần nhập (bước "Xem lại cột"), khỏi mở mẫu riêng.
    profile_header_row = fields.Integer(related="profile_id.header_row", readonly=False)
    profile_header_rows = fields.Selection(related="profile_id.header_rows", readonly=False)
    profile_sheet_name = fields.Char(related="profile_id.sheet_name", readonly=False)
    profile_code_prefixes = fields.Char(related="profile_id.code_prefixes", readonly=False)
    profile_brand = fields.Char(related="profile_id.brand", readonly=False)
    profile_our_code_patterns = fields.Char(related="profile_id.our_code_patterns", readonly=False)
    profile_price_in_thousands = fields.Boolean(related="profile_id.price_in_thousands", readonly=False)
    profile_skip_group_rows = fields.Boolean(related="profile_id.skip_group_rows", readonly=False)
    profile_ai_note = fields.Char(related="profile_id.ai_note")
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

    @api.depends("profile_id.column_ids.role")
    def _compute_kinds(self):
        for record in self:
            kinds = record.profile_id.kinds() if record.profile_id else frozenset()
            record.has_stock = "stock" in kinds
            record.has_price = "price" in kinds

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
        return self._sheet()[1]

    def _sheet(self):
        """(tên các sheet, lưới của sheet theo mẫu) của file đã tải."""
        self.ensure_one()
        if not self.file:
            raise UserError("Chưa tải file Excel lên.")
        try:
            return read_grid(base64.b64decode(self.file), self.profile_id.sheet_name)
        except GridError as error:
            raise UserError(str(error))

    def action_read_file(self):
        """Đọc file. Lần đầu của NCC hoặc NCC đổi mẫu: dừng ở bước xem lại cột; đúng mẫu: đọc luôn."""
        self.ensure_one()
        if self.state == "done":
            raise UserError("Lần nhập này đã áp dụng. Tạo lần nhập mới cho file mới.")
        sheet_names, grid = self._sheet()
        Profile = self.env["hlv.vendor.import.profile"]
        if not (self.profile_id and self.profile_id.matches(grid)):
            matching = Profile.search([("partner_id", "=", self.partner_id.id)]).filtered(lambda p: p.matches(grid))
            if matching:
                self.profile_id = matching[0]
        if self.profile_id and not self.profile_id.matches(grid) \
                and Profile.proposed_kinds(grid) - self.profile_id.kinds():
            # File khác loại với mẫu đang chọn (vd mẫu tồn kho, file bảng giá): làm mẫu mới, không đè mẫu cũ.
            self.profile_id = False
        if not self.profile_id:
            self.profile_id = Profile.propose(self.partner_id, grid, sheet_names=sheet_names)
            self.state = "mapping"
            self.message_post(body="Chưa có mẫu cho loại file này của NCC: đã đề xuất mẫu file, xem lại các cột "
                                   "rồi bấm \"Đọc theo mẫu này\".")
            return True
        if not self.profile_id.matches(grid):
            # NCC đổi khung: cột cũ giữ vai trò người đã chọn, cột mới để AI đề xuất.
            kept = set(self.profile_id.column_ids.mapped("header"))
            self.profile_id.refresh_columns(grid)
            self.env["hlv.vendor.import.template.ai"].suggest(self.profile_id, grid, sheet_names, kept_headers=kept)
            self.state = "mapping"
            self.message_post(body="Tiêu đề cột khác lần trước (NCC đổi mẫu?): đã đề xuất lại, xem lại các cột.")
            return True
        return self._load(grid)

    def action_refresh_columns(self):
        """Đổi dòng tiêu đề / sheet xong thì đề xuất lại cột theo chỗ mới."""
        self.ensure_one()
        self.profile_id.refresh_columns(self._grid())
        return True

    def action_ai_suggest_columns(self):
        """Nhờ AI đề xuất lại cả mẫu (dòng tiêu đề, cột…) — người bấm thì AI được đổi cả cột người đã chọn."""
        self.ensure_one()
        if not self.env["hlv.vendor.import.ai"].config()["api_key"]:
            raise UserError("Chưa có Anthropic API key (Cài đặt → Tồn kho → Trợ lý tạo mã hàng) — sửa cột bằng tay.")
        sheet_names, grid = self._sheet()
        if not self.env["hlv.vendor.import.template.ai"].suggest(self.profile_id, grid, sheet_names):
            raise UserError("AI chưa đề xuất được (lỗi gọi AI hoặc câu trả lời hỏng — xem log Odoo). Thử lại, hoặc sửa "
                            "cột bằng tay.")
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
        rows = extract_rows(grid, profile.first_data_index(), profile.column_specs(), profile.skip_group_rows)
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
            **self._price_values(row, 1000.0 if profile.price_in_thousands else 1.0),
        } for row in rows])
        self.write({"state": "review", "ai_state": "none", "ai_error": False})
        self._match(lines, prefixes)
        return True

    @staticmethod
    def _price_values(row, multiplier):
        """Giá một dòng file (nhân multiplier — file ghi theo nghìn đồng); VAT đọc được thì điền giá còn thiếu (chỉ có giá
        chưa VAT → tính giá sau VAT)."""
        vat, rate = read_vat(row["vat"], VAT_CODES)
        price, price_incl = price_pair(*(value * multiplier if value else value
                                         for value in (row["price"], row["price_incl"])), rate)
        return {"price": price, "price_incl": price_incl, "vat": vat or False}

    def _match(self, lines, prefixes):
        """Mã đã nhớ / trùng mã chắc chắn theo mẫu mã của NCC → khớp luôn; còn lại dò ứng viên; không ứng viên nào →
        "không có", khỏi hỏi AI."""
        keys = {key for key in lines.mapped("code_key") if key}
        known = self.env["hlv.vendor.product.alias"].lookup(self.partner_id, keys)
        by_code = self.env["hlv.vendor.code.match"].products_for_keys(self.profile_id, keys - set(known))
        for line in lines:
            product = known.get(line.code_key) or by_code.get(line.code_key)
            if product:
                line.write({"product_id": product.id, "decision": "confirmed", "ai_state": "skipped",
                            "match_source": "alias" if line.code_key in known else "code"})
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
        """Nhớ mã đã xác nhận; file có cột tồn thì thay tồn kho NCC, có cột giá thì cập nhật bảng giá NCC. Dòng chưa
        xác nhận vẫn vào bảng tồn / bảng giá, theo mã NCC (khớp sản phẩm ở lần nhập sau thì tự gắn)."""
        self.ensure_one()
        if self.state != "review":
            raise UserError("Chỉ áp dụng được lần nhập đang xác nhận.")
        if self.ai_state in ("queued", "running"):
            raise UserError("AI đang duyệt, đợi xong rồi áp dụng.")
        if self.has_price and not self.price_date:
            raise UserError("Điền \"Giá áp dụng từ\" (ngày NCC ghi trên thông báo giá).")
        confirmed = self.line_ids.filtered(lambda line: line.decision == "confirmed" and line.product_id)
        self.env["hlv.vendor.product.alias"].remember(self.partner_id, confirmed.filtered("code_key"))
        now = fields.Datetime.now()
        done = []
        if self.has_stock:
            self._apply_stock(confirmed, now)
            done.append("tồn kho")
        if self.has_price:
            priced = self._apply_prices(confirmed)
            done.append("%s giá từ %s" % (priced, self.price_date.strftime("%d/%m/%Y")))
        self.write({"state": "done", "applied_at": now, "applied_by": self.env.user.id})
        self.message_post(body="Đã áp dụng (%s): %s dòng, %s dòng khớp sản phẩm, %s dòng chưa khớp." % (
            ", ".join(done), len(self.line_ids), len(confirmed), len(self.line_ids) - len(confirmed)))
        return True

    def _apply_prices(self, confirmed):
        """Dòng có giá → bảng giá NCC từ ngày price_date. Dòng không có giá (ô trống) bỏ qua. Trả số dòng giá đã ghi."""
        lines = self.line_ids.filtered(lambda line: line.price or line.price_incl)
        self.env["hlv.vendor.price"].apply_for(self.partner_id, [{
            "match_key": line.code_key or fold(line.vendor_name),
            "product_id": line.product_id.id if line in confirmed else False,
            "vendor_code": line.vendor_code,
            "vendor_name": line.vendor_name,
            "uom_name": line.uom_name,
            "price": line.price,
            "price_incl": line.price_incl,
            "vat": line.vat,
            "import_id": self.id,
        } for line in lines if line.code_key or line.vendor_name], self.price_date)
        return len(lines)

    def _apply_stock(self, confirmed, now):
        self.env["hlv.vendor.stock"].replace_for(self.partner_id, [{
            "product_id": line.product_id.id if line in confirmed else False,
            "match_key": line.code_key or fold(line.vendor_name),
            "vendor_code": line.vendor_code,
            "vendor_name": line.vendor_name,
            "uom_name": line.uom_name,
            "warehouse": warehouse,
            "qty": qty,
            "import_id": self.id,
            "date": now,
        } for line in self.line_ids for warehouse, qty in (line.stock or {}).items()])
