# -*- coding: utf-8 -*-
"""Nhật ký mọi lần trợ lý tạo / sửa hàng trên MISA.

Ghi bởi Odoo ngay khi MISA báo thành công — không dựa vào lời Claude kể lại.
"""
from datetime import timedelta

from odoo import api, fields, models


def _escape_like(value):
    # =ilike coi % và _ là ký tự đại diện; mã hàng có dấu _ sẽ khớp nhầm mã khác.
    return value.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')


class HlvProductAgentLog(models.Model):
    _name = 'hlv.product.agent.log'
    _description = "Hàng tạo / sửa qua trợ lý"
    _order = 'id desc'
    _rec_name = 'product_code'

    session_id = fields.Many2one('hlv.product.chat.session', string="Hội thoại", ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string="Tài khoản", readonly=True, index=True)
    sale_name = fields.Char("Nhân viên", readonly=True, index=True)
    sale_code = fields.Char("Mã sale MISA", readonly=True)
    action = fields.Selection(
        [('create', "Tạo mới"), ('update', "Sửa")], string="Việc", required=True, readonly=True,
    )
    misa_id = fields.Char("MISA ID", readonly=True, index=True)
    product_code = fields.Char("Mã hàng", readonly=True, index=True)
    product_name = fields.Char("Tên hàng", readonly=True)
    category_id = fields.Integer("ID nhóm MISA", readonly=True)
    category_name = fields.Char("Nhóm", readonly=True)
    unit = fields.Char("ĐVT", readonly=True)
    description = fields.Text("Thông số", readonly=True)
    updated_field = fields.Char("Trường đã sửa", readonly=True)
    old_value = fields.Char("Giá trị cũ", readonly=True)
    new_value = fields.Char("Giá trị mới", readonly=True)

    odoo_product_id = fields.Many2one(
        'product.product', string="Sản phẩm Odoo", compute='_compute_odoo_product',
        help="Sản phẩm Odoo có đúng mã hàng này — trống nghĩa là MISA chưa đồng bộ về.",
    )
    in_odoo = fields.Boolean(
        "Đã có trên Odoo", compute='_compute_odoo_product', search='_search_in_odoo',
    )

    @api.depends('product_code')
    def _compute_odoo_product(self):
        # Non-stored có chủ đích: hàng về Odoo lúc nào là do đồng bộ MISA, nhật ký
        # không biết để tự tính lại; đọc lúc nào tra lúc đó.
        codes = [code for code in self.mapped('product_code') if code]
        products = self.env['product.product'].sudo().with_context(active_test=False).search(
            [('default_code', 'in', codes)]) if codes else self.env['product.product']
        by_code = {product.default_code: product for product in products}
        for log in self:
            product = by_code.get(log.product_code)
            log.odoo_product_id = product
            log.in_odoo = bool(product)

    def _search_in_odoo(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError("Chỉ hỗ trợ = / !=")
        # Chỉ tra các mã có trong nhật ký (bảng nhỏ) chứ không kéo cả kho mã sản phẩm.
        log_codes = [code for code in self.sudo().search([]).mapped('product_code') if code]
        found = self.env['product.product'].sudo().with_context(active_test=False).search(
            [('default_code', 'in', log_codes)]).mapped('default_code') if log_codes else []
        positive = (operator == '=') == bool(value)
        return [('product_code', 'in' if positive else 'not in', found)]

    @api.model
    def record(self, session, action, **vals):
        """Ghi một dòng nhật ký cho cuộc hội thoại `session`."""
        return self.sudo().create(dict(
            vals,
            session_id=session.id,
            user_id=session.user_id.id,
            sale_name=session.sale_name or session.user_id.name,
            sale_code=session.sale_code or False,
            action=action,
        ))

    @api.model
    def recent_creation(self, code, name, minutes):
        """Lần tạo gần đây (trong `minutes` phút) có cùng mã hoặc cùng tên. Rỗng nếu không có.

        So không phân biệt hoa thường. Dùng để chặn hai sale tạo trùng cùng lúc: MISA
        có thể chưa kịp trả hàng vừa tạo trong kết quả tìm kiếm.
        """
        since = fields.Datetime.now() - timedelta(minutes=minutes)
        domain = [('action', '=', 'create'), ('create_date', '>=', since)]
        matches = []
        if code:
            matches.append(('product_code', '=ilike', _escape_like(code)))
        if name:
            matches.append(('product_name', '=ilike', _escape_like(name)))
        if not matches:
            return self.browse()
        if len(matches) == 2:
            matches = ['|'] + matches
        return self.sudo().search(domain + matches, limit=1)
