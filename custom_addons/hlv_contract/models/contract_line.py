# -*- coding: utf-8 -*-
"""Dòng hàng của hợp đồng. Không giới hạn số dòng: mẫu ít dòng hơn được nhân bản khi xuất."""

from odoo import api, fields, models


class ContractLine(models.Model):
    _name = 'hlv.contract.line'
    _description = 'Dòng hàng hợp đồng'
    _order = 'sequence, id'

    contract_id = fields.Many2one('hlv.contract', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_name = fields.Char(string='Tên hàng', required=True)
    uom = fields.Char(string='ĐVT')
    quantity = fields.Float(string='Số lượng', digits='Product Unit of Measure', default=1.0)
    price_unit = fields.Monetary(string='Đơn giá', currency_field='currency_id')
    subtotal = fields.Monetary(string='Thành tiền', compute='_compute_subtotal', store=True,
                               currency_field='currency_id')
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

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
