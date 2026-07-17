# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import fields, models


class MisaExtensionConfigVersion(models.Model):
    _name = "misa.extension.config.version"
    _description = "Phiên bản batch config cho Extension"
    _order = "version desc"

    version = fields.Integer(
        string="Version",
        required=True,
        default=1,
        help="Số version của batch config này. Tăng mỗi lần publish config mới.",
    )
    min_extension_version = fields.Char(
        string="Extension version tối thiểu",
        default="2.0.0",
        help="Extension version tối thiểu để chạy với config này. "
             "Extension cũ hơn sẽ bị chặn, hiện banner 'cần cập nhật'.",
    )
    published_at = fields.Datetime(
        string="Ngày publish",
        default=fields.Datetime.now,
        help="Thời điểm config version này được publish.",
    )
    notes = fields.Text(
        string="Mô tả thay đổi",
        help="Ghi chú cho version này. VD: 'Thêm nút đối chiếu PO, đổi tên nút tạo YCMH'",
    )
    element_ids = fields.One2many(
        "misa.extension.element",
        "version_id",
        string="Elements",
        help="Các element thuộc version config này.",
    )
    active = fields.Boolean(
        string="Kích hoạt",
        default=True,
        help="Chỉ version active mới được extension fetch. "
             "Khi publish version mới, nên deactivate version cũ.",
    )