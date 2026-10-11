# -*- coding: utf-8 -*-
"""Mẫu hợp đồng: một file .docx có trường trộn, hoặc nội dung soạn ngay trên trang /hop-dong.

source = 'docx'   : giữ nguyên file Word đã tải lên, điền bằng MERGEFIELD.
source = 'builder': soạn trên trình soạn của trang (biến viết {{Ten_Bien}}). Mỗi lần lưu,
                    file .docx được dựng lại từ nội dung, nên Word và PDF luôn cùng một nguồn.
"""

import base64

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import contract_vars, docx_io, docx_merge, html_blocks

CONTRACT_TYPES = [('sale', 'Hợp đồng mua bán hàng hoá'), ('principle', 'Hợp đồng nguyên tắc')]


class ContractTemplate(models.Model):
    _name = 'hlv.contract.template'
    _description = 'Mẫu hợp đồng'
    _order = 'contract_type, name'

    name = fields.Char(string='Tên mẫu', required=True)
    contract_type = fields.Selection(CONTRACT_TYPES, string='Loại hợp đồng', required=True, default='sale')
    source = fields.Selection(
        [('docx', 'File Word (.docx)'), ('builder', 'Soạn trên trang')],
        string='Nguồn mẫu', required=True, default='docx')
    docx_file = fields.Binary(string='File Word mẫu', attachment=True)
    docx_filename = fields.Char(string='Tên file mẫu')
    # Chỉ nhóm Quản lý sửa được mẫu; không sanitize để giữ style (cỡ chữ, thụt lề, độ rộng cột)
    body_html = fields.Html(string='Nội dung mẫu', sanitize=False)
    note = fields.Text(string='Ghi chú')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Công ty', default=lambda self: self.env.company)

    @api.constrains('docx_file')
    def _check_docx_file(self):
        """Chặn file không phải .docx (ví dụ .doc, .pdf) ngay lúc lưu, thay vì để lộ ra lúc
        xuất hợp đồng. File .doc phải đi qua nút Import để được chuyển đổi."""
        for rec in self:
            if not rec.with_context(bin_size=False).docx_file:
                continue
            try:
                docx_merge.list_merge_fields(rec._docx_bytes())
            except ValueError as err:
                raise ValidationError('File mẫu "%s" không phải .docx hợp lệ: %s'
                                      % (rec.docx_filename or rec.name, err))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._rebuild_docx_for_builder()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'body_html' in vals or 'source' in vals:
            self._rebuild_docx_for_builder()
        return res

    def _rebuild_docx_for_builder(self):
        """Mẫu soạn trên trang: dựng lại file .docx từ nội dung HTML."""
        for rec in self.filtered(lambda r: r.source == 'builder'):
            docx_bytes = docx_io.build_docx(html_blocks.html_to_blocks(rec.body_html))
            rec.write({
                'docx_file': base64.b64encode(docx_bytes),
                'docx_filename': '%s.docx' % (rec.name or 'mau-hop-dong'),
            })

    def _docx_bytes(self):
        """Nội dung file .docx. Phải tắt bin_size: form/web_read đọc Binary với bin_size=True
        thì field trả về chuỗi kích thước ("18.40 Kb") thay vì base64, giải mã sẽ lỗi
        "Incorrect padding"."""
        self.ensure_one()
        data = self.with_context(bin_size=False).docx_file
        if not data:
            raise UserError('Mẫu "%s" chưa có file Word. Hãy tải file lên hoặc soạn nội dung.' % self.name)
        return base64.b64decode(data)

    def _field_report(self):
        """Biến đang dùng trong file mẫu: list {name, label, known}. Chưa có file -> []."""
        self.ensure_one()
        if not self.with_context(bin_size=False).docx_file:
            return []
        return [{
            'name': name,
            'label': contract_vars.VARIABLE_LABELS.get(name, ''),
            'known': contract_vars.is_known_variable(name),
        } for name in docx_merge.list_merge_fields(self._docx_bytes())]

    def action_convert_to_builder(self):
        """Chuyển mẫu file Word sang soạn trên trang. Một chiều: đầu/chân trang và khổ giấy
        riêng của file Word không chuyển sang được."""
        for rec in self.filtered(lambda r: r.source == 'docx'):
            blocks = docx_io.read_docx(rec._docx_bytes(), keep_fields=True)
            rec.write({'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)})
        return True
