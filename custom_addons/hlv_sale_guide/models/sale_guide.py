# -*- coding: utf-8 -*-
"""Một hướng dẫn nội bộ: trang HTML (kèm ảnh/CSS) tải lên từ backend, đọc ở /huong-dan/<slug>/.

Nội dung không nằm trong code: quản lý tải file .html hoặc .zip lên form, bấm Lưu là trang mới
có hiệu lực, không cần nâng cấp module. Các file của gói lưu thành ir.attachment gắn với bản
ghi, tên attachment là đường dẫn tương đối trong gói (index.html, img/a.png…).
"""

import base64
import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .guide_utils import INDEX, normalize_document, slugify, unpack_package

GUIDE_ROUTE = "/huong-dan"


class SaleGuide(models.Model):
    _name = "hlv.sale.guide"
    _description = "Hướng dẫn nội bộ"
    _order = "topic, sequence, name"

    name = fields.Char(string="Tên", required=True)
    slug = fields.Char(
        string="Đường dẫn", required=True, copy=False,
        help="Phần sau /huong-dan/ trên link, VD hoi-gia-ncc. Chỉ chữ thường không dấu, số và dấu -.",
    )
    topic = fields.Char(string="Nhóm", default="Bán hàng", help="Gom các hướng dẫn trên trang danh sách.")
    summary = fields.Text(string="Mô tả ngắn")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    group_ids = fields.Many2many(
        "res.groups", string="Chỉ cho nhóm",
        help="Để trống: mọi người dùng nội bộ đều đọc được. Chọn nhóm: chỉ người trong nhóm đó.",
    )
    package = fields.Binary(
        string="Tải nội dung (.html / .zip)", compute="_compute_package", inverse="_inverse_package",
        help="Một file .html, hoặc .zip gồm index.html và ảnh/CSS đi kèm. Tải lên là thay toàn bộ nội dung cũ.",
    )
    published_on = fields.Datetime(string="Cập nhật nội dung lúc", readonly=True)
    file_summary = fields.Text(string="Các file đang dùng", compute="_compute_file_summary")
    url = fields.Char(string="Link", compute="_compute_url")

    _sql_constraints = [
        ("slug_unique", "unique(slug)", "Đường dẫn này đã có hướng dẫn khác dùng."),
    ]

    @api.depends("slug")
    def _compute_url(self):
        for guide in self:
            guide.url = f"{GUIDE_ROUTE}/{guide.slug}/" if guide.slug else False

    def _compute_package(self):
        # Ô chỉ để tải lên: nội dung thật nằm ở attachment (_guide_files), không giữ bản zip.
        self.package = False

    def _inverse_package(self):
        for guide in self.filtered("package"):
            try:
                files = unpack_package(base64.b64decode(guide.package))
            except ValueError as exc:
                raise UserError(str(exc)) from exc
            guide._replace_files(files)

    @api.depends("published_on")
    def _compute_file_summary(self):
        for guide in self:
            files = guide._guide_files() if guide.id else self.env["ir.attachment"]
            guide.file_summary = "\n".join(f"{att.name} · {att.file_size // 1024 or 1} KB" for att in files) or False

    @api.onchange("name")
    def _onchange_name_slug(self):
        if self.name and not self.slug:
            self.slug = slugify(self.name)

    @api.constrains("slug")
    def _check_slug(self):
        for guide in self:
            if not guide.slug or guide.slug != slugify(guide.slug):
                raise ValidationError(_("Đường dẫn chỉ gồm chữ thường không dấu, số và dấu - (VD hoi-gia-ncc)."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Gõ "Hỏi giá NCC" vẫn được: đổi sẵn thành hoi-gia-ncc thay vì bắt nhập lại.
            vals["slug"] = slugify(vals.get("slug") or vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        if "slug" in vals:
            vals["slug"] = slugify(vals["slug"])
        return super().write(vals)

    def unlink(self):
        self._guide_files().unlink()
        return super().unlink()

    def _guide_files(self):
        """Attachment chứa nội dung các hướng dẫn trong self (sudo — đã qua quyền đọc bản ghi)."""
        return self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name), ("res_id", "in", self.ids), ("res_field", "=", False),
        ], order="res_id, name")

    def _guide_file(self, path):
        """Attachment của một đường dẫn trong gói (VD "img/a.png"), không có → recordset rỗng."""
        self.ensure_one()
        return self._guide_files().filtered(lambda att: att.name == path)[:1]

    def _replace_files(self, files):
        """Thay toàn bộ nội dung bằng files {đường dẫn: bytes} (đã qua unpack_package)."""
        self.ensure_one()
        page = files[INDEX].decode("utf-8-sig", errors="replace")
        files = {**files, INDEX: normalize_document(page).encode("utf-8")}
        self._guide_files().unlink()
        # sudo: attachment HTML do người không phải admin tạo bị Odoo ép về text/plain — trang
        # phục vụ theo đuôi file ở controller nên không sao, nhưng tạo bằng sudo cho gọn.
        # image_no_postprocess: giữ nguyên ảnh chụp màn hình, không để Odoo tự thu nhỏ.
        self.env["ir.attachment"].sudo().with_context(image_no_postprocess=True).create([
            {
                "name": path,
                "raw": content,
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": mimetypes.guess_type(path)[0] or "application/octet-stream",
            }
            for path, content in files.items()
        ])
        self.published_on = fields.Datetime.now()

    def action_open_page(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.url, "target": "new"}
