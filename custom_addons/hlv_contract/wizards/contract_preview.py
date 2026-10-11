# -*- coding: utf-8 -*-
"""Cửa sổ xem nhanh hợp đồng đã điền, không tạo file."""

from odoo import fields, models


class ContractPreview(models.TransientModel):
    _name = 'hlv.contract.preview'
    _description = 'Xem nhanh hợp đồng'

    contract_id = fields.Many2one('hlv.contract', required=True, ondelete='cascade')
    html = fields.Html(string='Nội dung', sanitize=False, readonly=True)

    def action_export_pdf(self):
        return self.contract_id.action_open_export()
