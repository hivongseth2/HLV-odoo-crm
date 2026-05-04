# -*- coding: utf-8 -*-
import logging
from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MisaInvoiceTemplateWizard(models.TransientModel):
    _name = 'misa.invoice.template.wizard'
    _description = 'Danh sách mẫu hóa đơn MISA'

    line_ids = fields.One2many(
        'misa.invoice.template.wizard.line',
        'wizard_id',
        string='Mẫu hóa đơn',
        readonly=True,
    )
    message = fields.Char(string='Ghi chú', readonly=True)


class MisaInvoiceTemplateWizardLine(models.TransientModel):
    _name = 'misa.invoice.template.wizard.line'
    _description = 'Dòng mẫu hóa đơn MISA'

    wizard_id = fields.Many2one('misa.invoice.template.wizard', ondelete='cascade')
    template_id = fields.Char(string='Invoice Template ID', readonly=True)
    series = fields.Char(string='Ký hiệu (Series)', readonly=True)
    name = fields.Char(string='Tên mẫu', readonly=True)
    status = fields.Char(string='Trạng thái', readonly=True)
