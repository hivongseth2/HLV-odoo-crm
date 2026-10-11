# -*- coding: utf-8 -*-
"""Mẫu hợp đồng: một file .docx có trường trộn, hoặc nội dung soạn ngay trên Odoo.

source = 'docx'   : giữ nguyên file Word đã tải lên, điền bằng MERGEFIELD.
source = 'builder': soạn trên trình HTML (biến viết {{Ten_Bien}}). Mỗi lần lưu, file
                    .docx được dựng lại từ nội dung, nên luôn cùng một nguồn với
                    đường xuất Word và PDF.
"""

import base64

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import contract_vars, docx_io, docx_merge, html_blocks


class ContractTemplate(models.Model):
    _name = 'hlv.contract.template'
    _description = 'Mẫu hợp đồng'
    _order = 'contract_type, name'

    name = fields.Char(string='Tên mẫu', required=True)
    contract_type = fields.Selection(
        [('sale', 'Hợp đồng mua bán hàng hoá'), ('principle', 'Hợp đồng nguyên tắc')],
        string='Loại hợp đồng', required=True, default='sale')
    source = fields.Selection(
        [('docx', 'File Word (.docx)'), ('builder', 'Soạn trên Odoo')],
        string='Nguồn mẫu', required=True, default='docx')
    docx_file = fields.Binary(string='File Word mẫu', attachment=True)
    docx_filename = fields.Char(string='Tên file mẫu')
    body_html = fields.Html(string='Nội dung mẫu', sanitize=False)
    note = fields.Text(string='Ghi chú')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Công ty', default=lambda self: self.env.company)
    field_info = fields.Html(string='Biến trong mẫu', compute='_compute_field_info')
    variable_palette = fields.Html(string='Danh sách biến', compute='_compute_variable_palette')

    @api.depends('docx_file')
    def _compute_field_info(self):
        for rec in self:
            rec.field_info = rec._field_info_html()

    def _field_info_html(self):
        """Liệt kê trường đang có trong file mẫu, đánh dấu trường không nhận diện được."""
        self.ensure_one()
        if not self.docx_file:
            return '<p class="text-muted">Chưa có file mẫu.</p>'
        try:
            names = docx_merge.list_merge_fields(self._docx_bytes())
        except ValueError as err:
            return '<p class="text-danger">Không đọc được file: %s</p>' % err
        if not names:
            return '<p class="text-warning">Mẫu chưa có trường trộn nào.</p>'
        items = []
        for name in names:
            if contract_vars.is_known_variable(name):
                label = contract_vars.VARIABLE_LABELS.get(name, name)
                items.append('<li><code>%s</code> &mdash; %s</li>' % (name, label))
            else:
                items.append('<li class="text-danger"><code>%s</code> &mdash; không có trong danh sách biến, '
                             'sẽ hiện nguyên dạng «%s» khi xuất</li>' % (name, name))
        return '<ul>%s</ul>' % ''.join(items)

    @api.depends()
    def _compute_variable_palette(self):
        palette = self._variable_palette_html()
        for rec in self:
            rec.variable_palette = palette

    @staticmethod
    def _variable_palette_html():
        """Bảng biến hiển thị cạnh trình soạn. Dòng hàng chỉ ghi mẫu dòng 1, các dòng 2..10
        cùng cấu trúc đổi số cuối."""
        groups = [
            ('Hợp đồng', contract_vars.HEADER_VARIABLES),
            ('Tổng tiền', contract_vars.TOTAL_VARIABLES),
            ('Bên bán (lấy từ cấu hình công ty)', contract_vars.SELLER_VARIABLES),
            ('Dòng hàng (dòng 1; dòng sau đổi số cuối, thiếu dòng thì tự nhân bản dòng cuối)',
             ['Ten_Hang_1', 'DVT_1', 'So_Luong_1', 'Don_Gia_1', 'Thanh_Tien_1']),
        ]
        blocks = []
        for title, names in groups:
            chips = ''.join('<li><code>{{%s}}</code> %s</li>' % (n, contract_vars.VARIABLE_LABELS.get(n, ''))
                            for n in names)
            blocks.append('<h4>%s</h4><ul>%s</ul>' % (title, chips))
        return ''.join(blocks)

    @api.constrains('docx_file')
    def _check_docx_file(self):
        """Chặn tải lên file không phải .docx (ví dụ .doc, .pdf) vào ô file mẫu: lỗi sẽ
        chỉ lộ ra lúc xuất hợp đồng. File .doc phải đi qua Import mẫu."""
        for rec in self.filtered('docx_file'):
            try:
                docx_merge.list_merge_fields(rec._docx_bytes())
            except ValueError as err:
                raise ValidationError('File mẫu "%s" không phải .docx hợp lệ: %s. File .doc hãy dùng '
                                      'menu Import mẫu từ Word.' % (rec.docx_filename or rec.name, err))

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
        """Mẫu soạn trên Odoo: dựng lại file .docx từ nội dung HTML."""
        for rec in self.filtered(lambda r: r.source == 'builder'):
            blocks = html_blocks.html_to_blocks(rec.body_html)
            docx_bytes = docx_io.build_docx(blocks)
            rec.write({
                'docx_file': base64.b64encode(docx_bytes),
                'docx_filename': '%s.docx' % (rec.name or 'mau-hop-dong'),
            })

    def _docx_bytes(self):
        self.ensure_one()
        if not self.docx_file:
            raise UserError('Mẫu "%s" chưa có file Word. Hãy tải file lên hoặc soạn nội dung.' % self.name)
        return base64.b64decode(self.docx_file)

    def action_convert_to_builder(self):
        """Chuyển mẫu file Word sang soạn trên Odoo để chỉnh sửa. Một chiều: layout trang
        (khổ giấy, lề, đầu/chân trang) không chuyển sang được."""
        for rec in self.filtered(lambda r: r.source == 'docx'):
            blocks = docx_io.read_docx(rec._docx_bytes(), keep_fields=True)
            rec.write({'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)})
        return True
