# -*- coding: utf-8 -*-
"""Mẫu file của một NCC: sheet nào, tiêu đề ở dòng mấy, cột nào là mã / tên / ĐVT / tồn từng kho / giá.

Lần đầu nhận file của NCC, mẫu được ĐỀ XUẤT từ chữ trên dòng tiêu đề (import_utils); người bên mình sửa
lại một lần, các file sau đọc theo đúng mẫu đó. NCC đổi cột (vân tay tiêu đề khác) thì đề xuất lại. Một NCC có
thể có vài mẫu (file tồn và file bảng giá khác khung) — đọc file chọn mẫu khớp tiêu đề.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from .import_utils import (
    ROLE_CODE, ROLE_NAME, ROLES, cell_text, column_headers, column_letter, detect_header, file_kinds,
    header_signature, propose_roles,
)

KIND_NAMES = {"stock": "tồn kho", "price": "bảng giá"}

SAMPLE_ROWS = 3


class HlvVendorImportProfile(models.Model):
    _name = "hlv.vendor.import.profile"
    _description = "Mẫu file NCC"
    _order = "partner_id, id"

    name = fields.Char("Tên mẫu", required=True)
    partner_id = fields.Many2one("res.partner", "Nhà cung cấp", required=True, index=True, ondelete="cascade")
    active = fields.Boolean(default=True)
    sheet_name = fields.Char("Sheet", help="Để trống: đọc sheet đầu tiên.")
    header_row = fields.Integer("Dòng tiêu đề", default=1, help="Số dòng trong Excel (bắt đầu từ 1).")
    header_rows = fields.Selection([("1", "Một tầng"), ("2", "Hai tầng")], "Tiêu đề", default="1", required=True,
                                   help="Hai tầng: dòng tiêu đề có nhóm (vd tên kho) và dòng dưới là cột con.")
    code_prefixes = fields.Char(
        "Tiền tố mã của NCC",
        help="Phần NCC tự thêm vào trước mã hãng, cách nhau dấu phẩy. Vd SATA: \"SC\" (SC97813 = 97813). "
             "Bỏ tiền tố để dò sản phẩm bên mình và nhớ mã cho lần sau.")
    brand = fields.Char("Hãng NCC bán", help="Báo cho AI: ứng viên khác hãng là sai dù trùng số model.")
    our_code_patterns = fields.Char(
        "Mã bên mình",
        help="Mã bên mình viết thế nào từ mã NCC (đã bỏ tiền tố) — {ma} là chỗ mã NCC. Nhiều kiểu cách dấu phẩy. "
             "Vd SATA: NCC ghi SC03200, bên mình 03200-SATA → tiền tố \"SC\", mã bên mình \"{ma}-SATA\". Không phân "
             "biệt hoa thường, bỏ qua khoảng trắng - _ . /. Trống: {ma}, {ma}-<hãng>, <hãng>-{ma}. Theo mẫu ra đúng "
             "một sản phẩm thì tự gắn (khi đọc file, khi tạo / đổi mã sản phẩm), không hỏi ai.")
    price_in_thousands = fields.Boolean(
        "Giá ghi theo nghìn đồng (× 1000)", help="File ghi giá theo nghìn đồng (\"310\" = 310.000 đ): nhân 1000 khi đọc.")
    skip_group_rows = fields.Boolean(
        "Bỏ dòng tiêu đề nhóm",
        help="Bỏ các dòng xen giữa bảng không có ĐVT, không có số tồn / giá (tên nhóm hàng như \"DỤNG CỤ CẦM TAY\").")
    ai_note = fields.Char("AI ghi chú", readonly=True, help="AI nói gì khi đề xuất mẫu — đọc khi xem lại cột.")
    column_ids = fields.One2many("hlv.vendor.import.column", "profile_id", "Cột")
    header_signature = fields.Char(readonly=True)

    @api.model
    def propose(self, partner, grid, sheet_name=False, sheet_names=()):
        """Tạo mẫu mới cho NCC partner từ lưới đã đọc: dò dòng tiêu đề + đề xuất vai trò cột theo từ khoá, rồi AI đề
        xuất lại (vendor_template_ai.py — không có API key / AI lỗi thì giữ phần đoán theo từ khoá)."""
        header_index, header_rows = detect_header(grid)
        kinds = self.proposed_kinds(grid)
        # Cách đặt mã là của NCC, không của file: mẫu thứ hai (file giá bên cạnh file tồn) lấy lại của mẫu đã có.
        sibling = self.search([("partner_id", "=", partner.id)], limit=1)
        profile = self.create({
            "code_prefixes": sibling.code_prefixes,
            "brand": sibling.brand,
            "our_code_patterns": sibling.our_code_patterns,
            "name": "%s (%s)" % (partner.display_name, ", ".join(KIND_NAMES[k] for k in sorted(kinds)))
                    if kinds else partner.display_name,
            "partner_id": partner.id,
            "sheet_name": sheet_name or False,
            "header_row": header_index + 1,
            "header_rows": str(header_rows),
        })
        profile.refresh_columns(grid)
        self.env["hlv.vendor.import.template.ai"].suggest(profile, grid, sheet_names)
        return profile

    @api.model
    def proposed_kinds(self, grid):
        """File này mang tồn / giá (theo cột đề xuất từ dòng tiêu đề dò được) — để chọn mẫu cũ hay làm mẫu mới."""
        header_index, header_rows = detect_header(grid)
        return file_kinds(role for role, _warehouse in propose_roles(column_headers(grid, header_index, header_rows)))

    def kinds(self):
        """Mẫu này đọc ra tồn / giá: tập con của {"stock", "price"}."""
        self.ensure_one()
        return file_kinds(self.column_ids.mapped("role"))

    def action_link_by_code(self):
        """Gắn sản phẩm cho dòng bảng giá / tồn kho chưa khớp của NCC theo mẫu mã (sau khi sửa tiền tố / mã bên mình)."""
        self.ensure_one()
        count = self.env["hlv.vendor.code.match"].link_unmatched(self)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success" if count else "info", "sticky": False,
            "message": "Đã khớp thêm %s mã theo mẫu mã." % count if count else "Không có mã nào khớp thêm.",
        }}

    def first_data_index(self):
        """Chỉ số (từ 0) dòng dữ liệu đầu tiên."""
        self.ensure_one()
        return self.header_row - 1 + int(self.header_rows)

    def headers(self, grid):
        self.ensure_one()
        return column_headers(grid, self.header_row - 1, int(self.header_rows))

    def matches(self, grid):
        """File này có đúng mẫu không (tiêu đề tại dòng đã khai trùng vân tay đã lưu)."""
        self.ensure_one()
        return bool(self.column_ids) and header_signature(self.headers(grid)) == self.header_signature

    def refresh_columns(self, grid):
        """Đề xuất lại các cột theo tiêu đề hiện tại; cột có tiêu đề trùng cột cũ giữ vai trò người đã chọn."""
        self.ensure_one()
        headers = self.headers(grid)
        if not headers:
            raise UserError("Dòng tiêu đề %s nằm ngoài file." % self.header_row)
        kept = {column.header: column for column in self.column_ids}
        start = self.first_data_index()
        samples = grid[start:start + SAMPLE_ROWS]
        commands = [(5, 0, 0)]
        for index, (header, (role, warehouse)) in enumerate(zip(headers, propose_roles(headers))):
            old = kept.get(header)
            commands.append((0, 0, {
                "col_index": index,
                "header": header,
                "role": old.role if old else role,
                "warehouse": old.warehouse if old else warehouse,
                "sample": " | ".join(cell_text(row[index]) for row in samples if index < len(row))[:120],
            }))
        self.write({"column_ids": commands, "header_signature": header_signature(headers)})

    def column_specs(self):
        """Cột đã gán vai trò, dạng import_utils.extract_rows cần. Lỗi khi không có cột mã lẫn cột tên, hoặc không có
        cột tồn lẫn cột giá."""
        self.ensure_one()
        specs = [{"index": c.col_index, "role": c.role, "warehouse": (c.warehouse or "").strip()}
                 for c in self.column_ids if c.role != "ignore"]
        roles = {spec["role"] for spec in specs}
        if not roles & {ROLE_CODE, ROLE_NAME}:
            raise UserError("Mẫu \"%s\" chưa có cột Mã hàng NCC hay Tên hàng." % self.name)
        if not file_kinds(roles):
            raise UserError("Mẫu \"%s\" chưa có cột tồn hay cột giá nào." % self.name)
        return specs


class HlvVendorImportColumn(models.Model):
    _name = "hlv.vendor.import.column"
    _description = "Cột trong mẫu file NCC"
    _order = "profile_id, col_index"

    profile_id = fields.Many2one("hlv.vendor.import.profile", required=True, ondelete="cascade", index=True)
    col_index = fields.Integer("Thứ tự cột", required=True)
    letter = fields.Char("Cột", compute="_compute_letter")
    header = fields.Char("Tiêu đề trong file", readonly=True)
    role = fields.Selection(ROLES, "Là", required=True, default="ignore")
    warehouse = fields.Char("Tên kho", help="Chỉ cho cột tồn: tên kho hiện trên bảng tồn NCC.")
    sample = fields.Char("Vài giá trị đầu", readonly=True)

    @api.depends("col_index")
    def _compute_letter(self):
        for column in self:
            column.letter = column_letter(column.col_index)
