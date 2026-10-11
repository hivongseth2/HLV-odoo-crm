# -*- coding: utf-8 -*-
"""Import mẫu hợp đồng từ file .docx hoặc .doc (Word 97-2003).

.docx: giữ nguyên file (mẫu Word) hoặc chuyển sang soạn trên Odoo.
.doc : đọc chữ và trường trộn; định dạng (đậm, căn lề) không đọc được nên mặc định mở
       trong trình soạn để người dùng chỉnh lại trước khi dùng.
"""

import base64
import os

from odoo import fields, models
from odoo.exceptions import UserError

from ..utils import docx_io, html_blocks
from ..utils.doc_binary import read_doc_blocks


class ContractTemplateImport(models.TransientModel):
    _name = 'hlv.contract.template.import'
    _description = 'Import mẫu hợp đồng'

    name = fields.Char(string='Tên mẫu', required=True)
    contract_type = fields.Selection(
        [('sale', 'Hợp đồng mua bán hàng hoá'), ('principle', 'Hợp đồng nguyên tắc')],
        string='Loại hợp đồng', required=True, default='sale')
    file = fields.Binary(string='File Word (.doc/.docx)', required=True)
    filename = fields.Char(string='Tên file')
    mode = fields.Selection(
        [('builder', 'Mở trong trình soạn Odoo để chỉnh'), ('docx', 'Giữ nguyên file Word')],
        string='Cách dùng', required=True, default='docx',
        help='File .doc luôn được chuyển sang trình soạn vì không giữ được định dạng gốc.')

    def action_import(self):
        self.ensure_one()
        ext = os.path.splitext(self.filename or '')[1].lower()
        data = base64.b64decode(self.file)
        if ext == '.docx':
            vals = self._vals_from_docx(data)
        elif ext == '.doc':
            vals = self._vals_from_doc(data)
        else:
            raise UserError('Chỉ hỗ trợ file .doc hoặc .docx.')
        vals.update({'name': self.name, 'contract_type': self.contract_type})
        template = self.env['hlv.contract.template'].create(vals)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contract.template',
            'res_id': template.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _vals_from_docx(self, data):
        try:
            blocks = docx_io.read_docx(data, keep_fields=True)
        except (ValueError, KeyError) as err:
            raise UserError('File .docx không đọc được: %s' % err)
        if self.mode == 'builder':
            return {'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)}
        return {'source': 'docx', 'docx_file': self.file, 'docx_filename': self.filename}

    def _vals_from_doc(self, data):
        try:
            blocks = read_doc_blocks(data)
        except (ValueError, IndexError) as err:
            raise UserError('File .doc không đọc được: %s. Thử mở bằng Word và lưu lại dạng .docx.' % err)
        return {
            'source': 'builder',
            'body_html': html_blocks.blocks_to_html(blocks),
            'note': 'Import từ %s: định dạng chữ (đậm, căn lề) và bảng cần kiểm tra lại.' % self.filename,
        }
