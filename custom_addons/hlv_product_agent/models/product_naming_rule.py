# -*- coding: utf-8 -*-
"""Quy tắc đặt tên / mã riêng cho từng dòng hàng (MILWAUKEE, KARCHER...).

Quản lý thêm ở đây thay vì sửa tài liệu A: ngoại lệ nằm tập trung một chỗ, bật tắt
được từng dòng, và mỗi dòng có ví dụ riêng.
"""
from odoo import fields, models


class HlvProductNamingRule(models.Model):
    _name = 'hlv.product.naming.rule'
    _description = "Quy tắc đặt tên / mã riêng theo dòng hàng"
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char("Dòng hàng", required=True, help="VD: MILWAUKEE, KARCHER, Vòng bi SKF")
    match = fields.Char(
        "Áp dụng khi",
        help="Mô tả cho Claude biết hàng nào thuộc dòng này. "
             "VD: hàng hãng MILWAUKEE (người dùng hay gõ MIL, Milwaukee).",
    )
    name_rule = fields.Text(
        "Quy tắc tên hàng", help="Để trống nếu tên vẫn theo quy tắc chung (tài liệu A).",
    )
    code_rule = fields.Text(
        "Quy tắc mã hàng", help="Để trống nếu mã vẫn theo quy tắc chung (tài liệu A).",
    )
    example_input = fields.Char("Ví dụ: sale gõ")
    example_name = fields.Char("Ví dụ: tên đúng")
    example_code = fields.Char("Ví dụ: mã đúng")
    note = fields.Text("Ghi chú thêm cho Claude")

    def to_prompt_dict(self):
        """Dữ liệu một quy tắc cho services.render_special_rules."""
        self.ensure_one()
        return {
            'name': self.name,
            'match': self.match,
            'name_rule': self.name_rule,
            'code_rule': self.code_rule,
            'note': self.note,
            'example_input': self.example_input,
            'example_name': self.example_name,
            'example_code': self.example_code,
        }
