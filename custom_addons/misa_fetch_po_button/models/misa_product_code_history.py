# -*- coding: utf-8 -*-
"""Lịch sử đổi mã hàng (Odoo <-> MISA CRM) để truy vết.

Mã hàng là khoá nối Odoo với MISA, với đơn / phiếu cũ, mã vạch, SKU web: đổi mã mà
không ghi lại là về sau không ai lần ra "mã cũ X giờ là mã gì". Mỗi lần đổi — dù từ
trợ lý Claude, API ngoài hay form Odoo — đều để lại một dòng ở đây, kể cả khi một bên
đổi được mà bên kia không.
"""
from odoo import api, fields, models


class MisaProductCodeHistory(models.Model):
    _name = 'misa.product.code.history'
    _description = "Lịch sử đổi mã hàng"
    _order = 'id desc'
    _rec_name = 'new_code'

    product_tmpl_id = fields.Many2one(
        'product.template', string="Sản phẩm Odoo", ondelete='set null', index=True, readonly=True)
    old_code = fields.Char("Mã cũ", required=True, index=True, readonly=True)
    new_code = fields.Char("Mã mới", required=True, index=True, readonly=True)
    misa_id = fields.Char("MISA ID", index=True, readonly=True)
    source = fields.Selection(
        [('agent', "Trợ lý Claude"), ('api', "API ngoài"), ('odoo', "Sửa trên Odoo")],
        string="Đổi qua", required=True, readonly=True,
    )
    user_id = fields.Many2one(
        'res.users', string="Tài khoản", readonly=True, default=lambda self: self.env.uid)
    actor = fields.Char(
        "Người đổi", readonly=True,
        help="Tên sale (trợ lý), địa chỉ IP bên gọi (API) hoặc người sửa form (Odoo).")
    misa_updated = fields.Boolean("Đã đổi trên MISA", readonly=True)
    odoo_updated = fields.Boolean("Đã đổi trên Odoo", readonly=True)
    note = fields.Text("Ghi chú", readonly=True)

    @api.model
    def record(self, old_code, new_code, source, actor=None, product_tmpl=None, misa_id=None,
               misa_updated=False, odoo_updated=False, note=None):
        """Ghi một dòng lịch sử (sudo: người đổi thường không có quyền ghi bảng này)."""
        return self.sudo().create({
            'old_code': (old_code or '').strip() or '?',
            'new_code': (new_code or '').strip() or '?',
            'source': source,
            'actor': actor or False,
            'product_tmpl_id': product_tmpl.id if product_tmpl else False,
            'misa_id': str(misa_id) if misa_id else False,
            'misa_updated': misa_updated,
            'odoo_updated': odoo_updated,
            'note': note or False,
        })
