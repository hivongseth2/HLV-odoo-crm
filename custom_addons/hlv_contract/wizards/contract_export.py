# -*- coding: utf-8 -*-
"""Xuất / in hàng loạt hợp đồng: Word (một file hoặc gói zip), PDF gộp một file, Excel.

PDF dùng wkhtmltopdf mà Odoo đã có sẵn để in báo cáo, nên không cần cài thêm gì.
"""

import base64
import re
import zipfile
from io import BytesIO

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..utils.contract_excel import build_contract_xlsx
from ..utils.html_blocks import wrap_html_document

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|]+')


def _safe_filename(name):
    """Số hợp đồng có dấu '/', không dùng được làm tên file."""
    return _UNSAFE_FILENAME.sub('-', name or 'hop-dong').strip() or 'hop-dong'


class ContractExport(models.TransientModel):
    _name = 'hlv.contract.export'
    _description = 'Xuất hợp đồng hàng loạt'

    contract_ids = fields.Many2many('hlv.contract', string='Hợp đồng', default=lambda self: self._default_contracts())
    contract_count = fields.Integer(compute='_compute_contract_count', string='Số hợp đồng')
    export_format = fields.Selection(
        [('docx', 'Word (.docx)'), ('pdf', 'PDF (gộp một file để in)'), ('xlsx', 'Excel (.xlsx)')],
        string='Định dạng', required=True, default='pdf')

    @api.model
    def _default_contracts(self):
        if self.env.context.get('active_model') != 'hlv.contract':
            return self.env['hlv.contract']
        return self.env['hlv.contract'].browse(self.env.context.get('active_ids') or [])

    @api.depends('contract_ids')
    def _compute_contract_count(self):
        for wizard in self:
            wizard.contract_count = len(wizard.contract_ids)

    def action_export(self):
        self.ensure_one()
        contracts = self.contract_ids
        if not contracts:
            raise UserError('Chưa chọn hợp đồng nào.')
        if self.export_format == 'docx':
            filename, content = self._export_docx(contracts)
        elif self.export_format == 'pdf':
            filename, content = self._export_pdf(contracts)
        else:
            filename, content = self._export_xlsx(contracts)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(content),
            'res_model': 'hlv.contract',
            'res_id': contracts.id if len(contracts) == 1 else 0,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'self',
        }

    def _export_docx(self, contracts):
        if len(contracts) == 1:
            return '%s.docx' % _safe_filename(contracts.name), contracts._render_docx_bytes()
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for contract in contracts:
                zf.writestr('%s.docx' % _safe_filename(contract.name), contract._render_docx_bytes())
        return 'hop-dong-%d-file.zip' % len(contracts), buffer.getvalue()

    def _export_pdf(self, contracts):
        bodies = [wrap_html_document(contract._render_html_fragment()) for contract in contracts]
        # Report tạm trong bộ nhớ (new, không lưu DB) chỉ để _run_wkhtmltopdf lấy khổ giấy hợp
        # đồng thay vì khổ mặc định của công ty; nội dung PDF không qua QWeb
        paperformat = self.env.ref('hlv_contract.paperformat_hlv_contract')
        report = self.env['ir.actions.report'].new({'paperformat_id': paperformat.id})
        pdf = report._run_wkhtmltopdf(bodies)
        name = _safe_filename(contracts.name) if len(contracts) == 1 else 'hop-dong-%d-ban' % len(contracts)
        return '%s.pdf' % name, pdf

    def _export_xlsx(self, contracts):
        content = build_contract_xlsx([contract._excel_row() for contract in contracts])
        return 'danh-sach-hop-dong.xlsx', content
