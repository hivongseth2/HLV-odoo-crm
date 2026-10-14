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
# Khuôn số mặc định theo loại (xem utils/contract_number): mua bán = ngày soạn + mã khách,
# nguyên tắc giữ cách đánh số cũ theo năm
DEFAULT_NUMBER_PATTERNS = {'sale': '{dd}{mm}{yyyy}/HLV-{ma_khach}', 'principle': 'HĐNT-{seq}/{yyyy}'}


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
    number_pattern = fields.Char(
        string='Khuôn số hợp đồng',
        default=lambda self: DEFAULT_NUMBER_PATTERNS.get(self.env.context.get('default_contract_type') or 'sale'),
        help='{dd}{mm}{yyyy}{yy}: ngày soạn; {seq}: số thứ tự trong năm; {ma_khach}: mã viết tắt khách '
             '(Mã đăng ký công ty trên khách hàng, không có thì tự viết tắt tên). Người soạn vẫn sửa tay được.')
    has_lines = fields.Boolean(string='Có bảng hàng hoá', readonly=True,
                               help='Mẫu có biến dòng hàng (Ten_Hang_1...) — hợp đồng sẽ có bảng hàng và tổng tiền.')
    system_fields = fields.Char(readonly=True, help='Biến tự điền có trong mẫu, cách nhau dấu phẩy.')
    # Tăng mỗi lần nội dung hoặc bộ biến của mẫu đổi; hợp đồng lưu số này lúc chụp mẫu để biết
    # mẫu đã được sửa sau khi lập (hợp đồng không tự đổi theo, xem hlv.contract._snapshot_template)
    content_version = fields.Integer(default=1, readonly=True, copy=False)

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
        """Đồng bộ biến nhập theo các trường có trong file mẫu (xem contract_vars.merge_variable_defs)
        và tăng content_version để hợp đồng nháp biết mẫu đã đổi. defs: cấu hình biến người dùng
        vừa sửa trên trang (nhãn/kiểu/nhóm/mặc định/thứ tự)."""
        for rec in self:
            names = rec._merge_field_names()
            merged = contract_vars.merge_variable_defs(names, [v._to_dict() for v in rec.variable_ids], defs)
            existing = {v.name: v for v in rec.variable_ids}
            keep = {d['name'] for d in merged}
            commands = [(1, existing[d['name']].id, d) if d['name'] in existing else (0, 0, d) for d in merged]
            commands += [(2, var.id) for name, var in existing.items() if name not in keep]
            rec.write({
                'variable_ids': commands,
                'has_lines': any(contract_vars.is_line_variable(n) for n in names),
                'system_fields': ','.join(n for n in names if contract_vars.is_system_variable(n)),
                'content_version': rec.content_version + 1,
            })

    def action_convert_to_builder(self):
        """Chuyển mẫu file Word sang soạn trên trang. Một chiều: đầu/chân trang và khổ giấy
        riêng của file Word không chuyển sang được."""
        for rec in self.filtered(lambda r: r.source == 'docx'):
            blocks = docx_io.read_docx(rec._docx_bytes(), keep_fields=True)
            rec.write({'source': 'builder', 'body_html': html_blocks.blocks_to_html(blocks)})
        return True

