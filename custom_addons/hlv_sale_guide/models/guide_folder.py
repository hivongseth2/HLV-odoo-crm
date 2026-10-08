# -*- coding: utf-8 -*-
"""Thư mục chứa hướng dẫn, lồng nhau thành cây (VD Bán hàng / Hỏi giá NCC)."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleGuideFolder(models.Model):
    _name = "hlv.sale.guide.folder"
    _description = "Thư mục hướng dẫn"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "sequence, name"

    name = fields.Char(string="Tên", required=True)
    parent_id = fields.Many2one("hlv.sale.guide.folder", string="Thư mục cha", ondelete="cascade", index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("hlv.sale.guide.folder", "parent_id", string="Thư mục con")
    complete_name = fields.Char(string="Đường dẫn đầy đủ", compute="_compute_complete_name", store=True, recursive=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    guide_ids = fields.One2many("hlv.sale.guide", "folder_id", string="Hướng dẫn")

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for folder in self:
            parent = folder.parent_id.complete_name
            folder.complete_name = f"{parent} / {folder.name}" if parent else folder.name

    @api.constrains("parent_id")
    def _check_parent_cycle(self):
        if self._has_cycle():
            raise ValidationError(_("Không thể đặt một thư mục nằm trong chính nó."))
