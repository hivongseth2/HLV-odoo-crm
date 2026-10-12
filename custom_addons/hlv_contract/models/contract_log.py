# -*- coding: utf-8 -*-
"""Nhật ký hợp đồng: ai làm gì, lúc nào, đổi từ gì sang gì.

Bảng riêng thay vì chatter: hợp đồng bị xoá thì chatter mất theo, còn nhật ký phải giữ được
cả việc xoá. Chỉ ghi thêm — không ai sửa/xoá được (quyền chỉ đọc, ghi bằng sudo trong _log).
"""

from odoo import api, fields, models

ACTIONS = [
    ('create', 'Tạo'),
    ('update', 'Sửa'),
    ('body', 'Sửa nội dung riêng'),
    ('template', 'Áp dụng mẫu'),
    ('state', 'Đổi trạng thái'),
    ('export', 'Xuất file'),
    ('delete', 'Xoá'),
]


class ContractLog(models.Model):
    _name = 'hlv.contract.log'
    _description = 'Nhật ký hợp đồng'
    _order = 'id desc'

    # set null: xoá hợp đồng vẫn giữ dòng nhật ký (contract_name giữ số hợp đồng để còn tra)
    contract_id = fields.Many2one('hlv.contract', ondelete='set null', index=True, readonly=True)
    contract_name = fields.Char(string='Số hợp đồng', readonly=True, index=True)
    company_id = fields.Many2one('res.company', readonly=True, index=True)
    user_id = fields.Many2one('res.users', string='Người làm', readonly=True, index=True)
    action = fields.Selection(ACTIONS, string='Việc', required=True, readonly=True, index=True)
    summary = fields.Char(string='Tóm tắt', readonly=True)
    details = fields.Text(string='Chi tiết', readonly=True)

    @api.model
    def _log(self, contract, action, summary, details=None):
        """Ghi một dòng nhật ký cho contract (người làm = người đang đăng nhập).
        details: list dòng chữ (thay đổi cụ thể) hoặc None."""
        return self.sudo().create({
            'contract_id': contract.id,
            'contract_name': contract.name,
            'company_id': contract.company_id.id,
            'user_id': self.env.uid,
            'action': action,
            'summary': summary,
            'details': '\n'.join(details or []) or False,
        })
