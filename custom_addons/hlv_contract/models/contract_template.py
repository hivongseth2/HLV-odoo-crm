# -*- coding: utf-8 -*-
"""Mẫu hợp đồng: một file .docx có trường trộn, hoặc nội dung soạn ngay trên trang /hop-dong.

source = 'docx'   : giữ nguyên file Word đã tải lên, điền bằng MERGEFIELD.
source = 'builder': soạn trên trình soạn của trang (biến viết {{Ten_Bien}}). Mỗi lần lưu,
                    file .docx được dựng lại từ nội dung, nên Word và PDF luôn cùng một nguồn.

Mỗi mẫu có bộ biến nhập riêng (variable_ids), tự đồng bộ theo các trường có trong file.
"""

import base64

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import contract_vars, docx_io, docx_merge, html_blocks

CONTRACT_TYPES = [('sale', 'Hợp đồng mua bán hàng hoá'), ('principle', 'Hợp đồng nguyên tắc')]
_TYPE_KEYS = {key for key, _label in contract_vars.VARIABLE_TYPES}
_SECTION_KEYS = {key for key, _label in contract_vars.SECTIONS}


class ContractTemplate(models.Model):
    _name = 'hlv.contract.template'
    _description = 'Mẫu hợp đồng'
    _order = 'contract_type, name'

    name = fields.Char(string='Tên mẫu', required=True)
    contract_type = fields.Selection(CONTRACT_TYPES, string='Loại hợp đồng', required=True, default='sale',
                                     help='Quyết định dãy số hợp đồng (HĐMB-… / HĐNT-…).')
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
    variable_ids = fields.One2many('hlv.contract.template.variable', 'template_id', string='Biến nhập', copy=True)
    has_lines = fields.Boolean(string='Có bảng hàng hoá', readonly=True,
                               help='Mẫu có biến dòng hàng (Ten_Hang_1...) — hợp đồng sẽ có bảng hàng và tổng tiền.')
    system_fields = fields.Char(readonly=True, help='Biến tự điền có trong mẫu, cách nhau dấu phẩy.')

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
        records._sync_variables()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'body_html' in vals or 'source' in vals:
            self._rebuild_docx_for_builder()
        if 'docx_file' in vals:
            self._sync_variables()
        return res

    def _rebuild_docx_for_builder(self):
        """Mẫu soạn trên trang: dựng lại file .docx từ nội dung HTML (write này tự đồng bộ biến)."""
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

    def _merge_field_names(self):
        self.ensure_one()
        if not self.with_context(bin_size=False).docx_file:
            return []
        return docx_merge.list_merge_fields(self._docx_bytes())

    def _sync_variables(self, defs=None):
        """Đồng bộ biến nhập theo các trường có trong file mẫu: thêm biến mới (nhãn/kiểu lấy
        từ thư viện), xoá biến không còn trong mẫu, giữ cấu hình biến đã có.

        defs: list dict {name, label, var_type, section, default_value} người dùng sửa trên
        trang — áp vào biến cùng tên, và thứ tự trong defs là thứ tự ô nhập. Biến không có
        trong defs đứng sau, theo thứ tự xuất hiện trong mẫu."""
        defs_by_name = {d.get('name'): d for d in (defs or []) if d.get('name')}
        def_order = [d.get('name') for d in (defs or [])]
        for rec in self:
            names = rec._merge_field_names()
            inputs = [n for n in names if not contract_vars.is_system_variable(n)]
            existing = {v.name: v for v in rec.variable_ids}
            if defs is None:
                ordered = sorted(inputs, key=lambda n: (existing[n].sequence if n in existing else 10 ** 6,
                                                        inputs.index(n)))
            else:
                ordered = sorted(inputs, key=lambda n: (def_order.index(n) if n in def_order else len(def_order),
                                                        inputs.index(n)))
            commands = []
            for index, name in enumerate(ordered):
                vals = existing[name]._to_dict() if name in existing else contract_vars.default_variable_def(name)
                vals.update(_clean_def(defs_by_name.get(name)))
                vals.update({'name': name, 'sequence': (index + 1) * 10})
                commands.append((1, existing[name].id, vals) if name in existing else (0, 0, vals))
            commands += [(2, var.id) for name, var in existing.items() if name not in inputs]
            rec.write({
                'variable_ids': commands,
                'has_lines': any(contract_vars.is_line_variable(n) for n in names),
                'system_fields': ','.join(n for n in names if contract_vars.is_system_variable(n)),
            })

    def action_convert_to_builder(self):
        """Chuyển mẫu file Word sang soạn trên trang. Một chiều: đầu/chân trang và khổ giấy
        riêng của file Word không chuyển sang được."""
        for rec in self.filtered(lambda r: r.source == 'docx'):
            blocks = docx_io.read_docx(rec._docx_bytes(), keep_fields=True)
            rec.write({'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)})
        return True


def _clean_def(definition):
    """Giữ đúng các khoá người dùng được sửa, bỏ giá trị kiểu/nhóm không hợp lệ."""
    if not definition:
        return {}
    vals = {}
    if (definition.get('label') or '').strip():
        vals['label'] = definition['label'].strip()
    if definition.get('var_type') in _TYPE_KEYS:
        vals['var_type'] = definition['var_type']
    if definition.get('section') in _SECTION_KEYS:
        vals['section'] = definition['section']
    if 'default_value' in definition:
        vals['default_value'] = (definition.get('default_value') or '').strip()
    return vals
