# -*- coding: utf-8 -*-
"""Một biến nhập của mẫu hợp đồng — tương đương một cột trong sheet Excel cũ (HDMB/HDNT).

Danh sách biến của mẫu không khai tay từ đầu: mỗi lần lưu mẫu, module quét các trường trộn
trong file và tự thêm/bớt (xem ContractTemplate._sync_variables). Người dùng chỉ sửa nhãn,
kiểu, nhóm, giá trị mặc định. Biến tự điền (số hợp đồng, bên bán, bảng hàng, tổng tiền)
không nằm ở đây.
"""

from odoo import fields, models

from ..utils.contract_vars import SECTIONS, VARIABLE_TYPES


class ContractTemplateVariable(models.Model):
    _name = 'hlv.contract.template.variable'
    _description = 'Biến của mẫu hợp đồng'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one('hlv.contract.template', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Tên biến', required=True, help='Tên trong mẫu, ví dụ Ten_Ben_Mua')
    label = fields.Char(string='Nhãn', required=True)
    var_type = fields.Selection(VARIABLE_TYPES, string='Kiểu', required=True, default='text')
    section = fields.Selection(SECTIONS, string='Nhóm', required=True, default='other')
    default_value = fields.Char(string='Giá trị mặc định')

    _sql_constraints = [
        ('name_template_uniq', 'unique(template_id, name)', 'Mỗi biến chỉ khai một lần trong một mẫu.'),
    ]

    def _to_dict(self):
        self.ensure_one()
        return {
            'name': self.name,
            'label': self.label,
            'var_type': self.var_type,
            'section': self.section,
            'default_value': self.default_value or '',
        }
