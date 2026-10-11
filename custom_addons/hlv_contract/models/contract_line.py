# -*- coding: utf-8 -*-
"""Dòng hàng của hợp đồng. Không giới hạn số dòng: mẫu ít dòng hơn được nhân bản khi xuất."""

from odoo import api, fields, models

from ..utils.contract_vars import line_subtotal


class ContractLine(models.Model):
    _name = 'hlv.contract.line'
    _description = 'Dòng hàng hợp đồng'
    _order = 'sequence, id'

    contract_id = fields.Many2one('hlv.contract', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    # Chọn từ danh mục sản phẩm là tuỳ chọn: tên/ĐVT vẫn là chữ người dùng sửa được như gõ tay
    product_id = fields.Many2one('product.product', string='Sản phẩm', ondelete='set null')
    product_name = fields.Char(string='Tên hàng', required=True)
    uom = fields.Char(string='ĐVT')
    quantity = fields.Float(string='Số lượng', digits='Product Unit of Measure', default=1.0)
    # Đơn giá chưa VAT, giữ 4 số lẻ: người dùng nhập giá SAU VAT, chia ngược ra giá chưa VAT
    # mà làm tròn đồng ngay thì tổng sau VAT lệch vài đồng so với số họ đã gõ
    price_unit = fields.Float(string='Đơn giá (chưa VAT)', digits=(16, 4))
    subtotal = fields.Monetary(string='Thành tiền', compute='_compute_subtotal', store=True,
                               currency_field='currency_id')
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line_subtotal(line.quantity, line.price_unit)

    @api.model_create_multi
    def create(self, vals_list):
        contract_ids = {vals.get('contract_id') for vals in vals_list}
        self.env['hlv.contract'].browse(list(contract_ids - {None, False}))._check_content_editable()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('contract_id')._check_content_editable()
        return super().write(vals)

    def unlink(self):
        self.mapped('contract_id')._check_content_editable()
        return super().unlink()
