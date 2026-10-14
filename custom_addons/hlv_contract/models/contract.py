# -*- coding: utf-8 -*-
"""Hợp đồng điền từ mẫu (xem contract_template).

Giá trị các biến nhập lưu trong variable_values (JSON {tên biến: giá trị}) vì mỗi mẫu có
bộ biến riêng, giống mỗi sheet Excel cũ có cột riêng. Số hợp đồng lấy từ ir.sequence theo
loại và năm (HĐMB-001/2026). Tổng tiền và chữ được tính ở đây; mẫu Word chỉ hiển thị.
Giao diện là trang /hop-dong (controllers/), không dùng form backend.

Mỗi hợp đồng giữ BẢN CHỤP nội dung riêng (doc_file + doc_variables) lấy từ mẫu lúc lập: sửa
mẫu sau đó không làm đổi hợp đồng đã lập. Người soạn còn sửa được chữ trên chính hợp đồng
(doc_custom) mà không đụng tới mẫu.
"""

import base64
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..utils import contract_number, contract_vars, docx_io, docx_merge, html_blocks, preview_marks
from ..utils.audit_diff import diff_lines, diff_values
from .contract_template import DEFAULT_NUMBER_PATTERNS

_SEQUENCE_CODE = {'sale': 'hlv.contract.sale', 'principle': 'hlv.contract.principle'}
STATES = [('draft', 'Nháp'), ('confirmed', 'Đã xác nhận'), ('signed', 'Đã ký'), ('cancel', 'Đã huỷ')]
# Nội dung hợp đồng: khoá với MỌI người khi đã rời trạng thái Nháp (chặn ở server vì import/RPC
# vẫn ghi được dù giao diện khoá). Muốn sửa thì đưa về Nháp trước. Ghi chú nội bộ luôn sửa được.
_CONTENT_FIELDS = {'name', 'template_id', 'contract_date', 'partner_id', 'variable_values', 'vat_rate', 'line_ids',
                   'doc_file', 'doc_variables', 'doc_html', 'doc_custom', 'overrides'}
MANAGER_GROUP = 'hlv_contract.group_contract_manager'
# Field thường ghi vào nhật ký khi đổi (cùng các ô biến và hàng hoá)
_AUDIT_FIELDS = [
    ('name', 'Số hợp đồng'), ('template_id', 'Mẫu'), ('contract_date', 'Ngày ký'), ('partner_id', 'Khách hàng'),
    ('vat_rate', 'Thuế suất VAT (%)'), ('user_id', 'Phụ trách'), ('note', 'Ghi chú nội bộ'),
]
# Ghi bằng context này thì write không tự so trước/sau — hàm gọi tự ghi một dòng nhật ký gọn hơn
_NO_AUDIT = 'hlv_contract_no_audit'
# Biến chuẩn điền sẵn khi chọn khách: tên biến -> hàm lấy từ (công ty khách, người liên hệ)
_PARTNER_FILL = {
    'Ten_Ben_Mua': lambda company, contact: company.name,
    'Dia_Chi_Ben_Mua': lambda company, contact: ', '.join(
        line.strip() for line in (company.contact_address or '').splitlines() if line.strip()),
    'Ma_So_Thue_Ben_Mua': lambda company, contact: company.vat,
    'Dien_Thoai_Ben_Mua': lambda company, contact: company.phone or contact.phone,
    'Nguoi_Dai_Dien_Ben_Mua': lambda company, contact: contact.name if contact != company else '',
    'Chuc_Vu_Ben_Mua': lambda company, contact: contact.function if contact != company else '',
}


class Contract(models.Model):
    _name = 'hlv.contract'
    _description = 'Hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'contract_date desc, id desc'

    name = fields.Char(string='Số hợp đồng', default='/', copy=False, readonly=True, tracking=True, index=True)
    template_id = fields.Many2one('hlv.contract.template', string='Mẫu', required=True, tracking=True, index=True)
    contract_type = fields.Selection(related='template_id.contract_type', store=True, string='Loại hợp đồng')
    state = fields.Selection(STATES, string='Trạng thái', default='draft', required=True, tracking=True, copy=False)
    contract_date = fields.Date(string='Ngày ký', required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Nhân viên phụ trách', default=lambda self: self.env.user,
                              tracking=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', tracking=True)
    variable_values = fields.Json(string='Giá trị biến', default=dict, copy=True)
    # Tách ra cột thường để danh sách tìm/sắp xếp được (JSON không tìm kiếm được)
    party_name = fields.Char(string='Bên mua', compute='_compute_party', store=True, index=True)
    party_vat = fields.Char(string='MST bên mua', compute='_compute_party', store=True)

    vat_rate = fields.Float(string='Thuế suất VAT (%)', default=lambda self: self.env.company.contract_vat_rate)
    line_ids = fields.One2many('hlv.contract.line', 'contract_id', string='Hàng hoá', copy=True)
    amount_untaxed = fields.Monetary(string='Tổng tiền hàng', compute='_compute_amounts', store=True,
                                     currency_field='currency_id')
    amount_vat = fields.Monetary(string='Tiền thuế VAT', compute='_compute_amounts', store=True,
                                 currency_field='currency_id')
    amount_total = fields.Monetary(string='Tổng giá trị', compute='_compute_amounts', store=True,
                                   currency_field='currency_id', tracking=True)
    amount_words = fields.Char(string='Bằng chữ', compute='_compute_amounts', store=True)
    note = fields.Text(string='Ghi chú nội bộ')

    # Bản chụp nội dung của riêng hợp đồng này (xem docstring đầu file)
    doc_file = fields.Binary(string='File Word của hợp đồng', attachment=True, copy=True)
    doc_variables = fields.Json(string='Biến của hợp đồng', copy=True)
    doc_has_lines = fields.Boolean(string='Có bảng hàng', copy=True)
    doc_html = fields.Html(string='Nội dung sửa riêng', sanitize=False, copy=True)
    doc_custom = fields.Boolean(string='Đã sửa nội dung riêng', copy=True)
    template_version = fields.Integer(string='Phiên bản mẫu đã chụp', copy=True)
    doc_system_fields = fields.Char(string='Biến tự điền có trong nội dung', copy=True)
    # Số hợp đồng còn theo khuôn (chưa ai sửa tay): đổi khách thì số tự cấp lại theo mã khách mới
    number_auto = fields.Boolean(default=True, copy=False)
    # Người soạn sửa đè chữ của biến tự điền (ngày ký, bên bán, tổng tiền bằng chữ…): {tên biến: chữ}
    overrides = fields.Json(string='Sửa đè biến tự điền', copy=True)

    @api.depends('line_ids.subtotal', 'vat_rate')
    def _compute_amounts(self):
        for rec in self:
            totals = contract_vars.compute_totals(rec.line_ids.mapped('subtotal'), rec.vat_rate)
            rec.amount_untaxed = totals['untaxed']
            rec.amount_vat = totals['vat']
            rec.amount_total = totals['total']
            rec.amount_words = totals['words']

    @api.depends('variable_values', 'partner_id')
    def _compute_party(self):
        for rec in self:
            values = rec.variable_values or {}
            company = rec.partner_id.commercial_partner_id
            rec.party_name = values.get('Ten_Ben_Mua') or company.name or ''
            rec.party_vat = values.get('Ma_So_Thue_Ben_Mua') or company.vat or ''

    @api.model
    def _buyer_values_from_partner(self, partner):
        """Giá trị biến chuẩn bên mua khi chọn khách. Bên mua là pháp nhân: chọn người liên hệ
        thì lấy công ty cha, người liên hệ thành người đại diện. Trang chỉ điền các biến mẫu có."""
        company = partner.commercial_partner_id
        return {name: getter(company, partner) or '' for name, getter in _PARTNER_FILL.items()}

    def _with_defaults(self, var_defs, values):
        """values + giá trị mặc định của các biến (list dict) chưa có giá trị. Toà án mặc định lấy
        theo cấu hình công ty nếu biến không khai mặc định riêng."""
        merged = dict(values or {})
        for var in var_defs:
            if merged.get(var['name']) not in (None, ''):
                continue
            default = var.get('default_value')
            if not default and var['name'] == 'Toa_An_Giai_Quyet':
                default = self.env.company.contract_court
            if default:
                merged[var['name']] = default
        return merged

    @api.model_create_multi
    def create(self, vals_list):
        Template = self.env['hlv.contract.template']
        for vals in vals_list:
            template = Template.browse(vals.get('template_id'))
            var_defs = [v._to_dict() for v in template.variable_ids]
            vals['variable_values'] = self._with_defaults(var_defs, vals.get('variable_values'))
            if vals.get('name', '/') in ('/', False):
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                vals['name'] = self._next_contract_number(template, partner, vals.get('company_id'))
            else:
                vals['number_auto'] = False
        records = super().create(vals_list)
        records.filtered(lambda r: not r.doc_file).with_context(**{_NO_AUDIT: True})._snapshot_template()
        for rec in records:
            initial = rec._audit_snapshot()
            rec._log('create', 'Tạo hợp đồng từ mẫu "%s"' % rec.template_id.name,
                     diff_values({}, initial['fields'], {}) + diff_lines([], initial['lines']))
        return records

    def write(self, vals):
        if _CONTENT_FIELDS.intersection(vals):
            self._check_content_editable()
        audit = not self.env.context.get(_NO_AUDIT)
        before = {rec.id: rec._audit_snapshot() for rec in self} if audit else {}
        new_template = vals.get('template_id') and len(self) == 1 and vals['template_id'] != self.template_id.id
        if new_template:
            template = self.env['hlv.contract.template'].browse(vals['template_id'])
            vals['variable_values'] = self._with_defaults(
                [v._to_dict() for v in template.variable_ids], vals.get('variable_values', self.variable_values))
        if 'name' in vals and len(self) == 1 and vals['name'] != self.name:
            vals['number_auto'] = False
        res = super().write(vals)
        if new_template:
            self.with_context(**{_NO_AUDIT: True})._snapshot_template()
        if ('partner_id' in vals or new_template) and 'name' not in vals:
            self._refresh_auto_number()
        if audit:
            self._log_changes(before)
        return res

    def unlink(self):
        if self.filtered(lambda r: r.state not in ('draft', 'cancel')):
            raise UserError('Chỉ xoá được hợp đồng Nháp hoặc Đã huỷ.')
        for rec in self:
            rec._log('delete', 'Xoá hợp đồng (%s, bên mua: %s, giá trị %s)' % (
                dict(STATES).get(rec.state), rec.party_name or '—', contract_vars.format_money(rec.amount_total)))
        return super().unlink()

    # ---------- nhật ký ----------

    def _log(self, action, summary, details=None):
        self.ensure_one()
        return self.env['hlv.contract.log']._log(self, action, summary, details)

    def _audit_value(self, field_name):
        """Giá trị field dạng chữ cho nhật ký: ngày dd/mm/yyyy, many2one theo tên."""
        value = self[field_name]
        field = self._fields[field_name]
        if field.type == 'date':
            return value.strftime('%d/%m/%Y') if value else ''
        if field.type == 'many2one':
            return value.display_name or ''
        if field.type == 'float':
            return contract_vars.format_number(value)
        return value or ''

    def _audit_snapshot(self):
        """Ảnh chụp nội dung để so trước/sau: field thường + ô biến (theo nhãn) + hàng hoá (giá sau VAT)."""
        self.ensure_one()
        labels = {v['name']: v['label'] for v in self._doc_variables()}
        shown = {label: self._audit_value(name) for name, label in _AUDIT_FIELDS}
        shown.update({labels.get(k, k): v for k, v in (self.variable_values or {}).items()})
        shown.update({'Sửa đè ' + contract_vars.SYSTEM_LABELS.get(k, k): v for k, v in (self.overrides or {}).items()})
        return {
            'state': self.state,
            'fields': shown,
            'lines': [{
                'name': line.product_name,
                'uom': line.uom,
                'quantity': line.quantity,
                'price': contract_vars.price_incl(line.price_unit, self.vat_rate),
            } for line in self.line_ids],
        }

    def _log_changes(self, before):
        """Sau một lần ghi: đổi trạng thái thành một dòng, đổi nội dung thành một dòng có chi tiết."""
        states = dict(STATES)
        for rec in self:
            old, new = before[rec.id], rec._audit_snapshot()
            if old['state'] != new['state']:
                rec._log('state', '%s → %s' % (states.get(old['state']), states.get(new['state'])))
            details = diff_values(old['fields'], new['fields'], {}) + diff_lines(old['lines'], new['lines'])
            if details:
                rec._log('update', 'Sửa %d mục' % len(details), details)

    def _is_manager(self):
        return self.env.su or self.env.user.has_group(MANAGER_GROUP)

    def _check_content_editable(self):
        """Hợp đồng đã xác nhận / đã ký / đã huỷ là văn bản đã chốt: không ai sửa nội dung, kể cả
        Quản lý — phải đưa về Nháp trước (có lưu vết trạng thái). Chỉ bỏ qua khi chạy quyền hệ thống
        (script nâng cấp)."""
        if self.env.su:
            return
        locked = self.filtered(lambda r: r.state != 'draft')
        if locked:
            raise UserError('Hợp đồng %s không còn ở trạng thái Nháp. Bấm "Về nháp để sửa" trước khi sửa nội dung.'
                            % ', '.join(locked.mapped('name')))

    # ---------- bản chụp nội dung riêng ----------

    def _doc_bytes(self):
        """File Word dùng để điền hợp đồng: bản chụp riêng; hợp đồng tạm (xem trước khi chưa lưu)
        chưa có bản chụp thì dùng mẫu."""
        self.ensure_one()
        data = self.with_context(bin_size=False).doc_file
        return base64.b64decode(data) if data else self.template_id._docx_bytes()

    def _has_snapshot(self):
        # bin_size: chỉ hỏi kích thước, không nạp cả file Word (hàm này chạy mỗi lần ghi nhật ký)
        return bool(self.with_context(bin_size=True).doc_file)

    def _doc_variables(self):
        """Biến nhập của hợp đồng (list dict theo thứ tự ô nhập)."""
        self.ensure_one()
        if self._has_snapshot():
            return list(self.doc_variables or [])
        return [v._to_dict() for v in self.template_id.variable_ids]

    def _doc_has_lines(self):
        self.ensure_one()
        return self.doc_has_lines if self._has_snapshot() else self.template_id.has_lines

    def _template_outdated(self):
        """Mẫu đã được sửa sau khi chụp vào hợp đồng này."""
        self.ensure_one()
        return self._has_snapshot() and self.template_version != self.template_id.content_version

    def _snapshot_template(self):
        """Chụp nội dung + bộ biến hiện tại của mẫu vào hợp đồng; bỏ nội dung đã sửa riêng."""
        for rec in self:
            template = rec.template_id
            rec.write({
                'doc_file': base64.b64encode(template._docx_bytes()),
                'doc_variables': [v._to_dict() for v in template.variable_ids],
                'doc_has_lines': template.has_lines,
                'doc_system_fields': template.system_fields,
                'doc_html': False,
                'doc_custom': False,
                'template_version': template.content_version,
            })

    def action_apply_template(self):
        """Hợp đồng nháp lấy lại nội dung theo mẫu hiện tại (mẫu vừa được sửa, hoặc bỏ phần chữ đã
        sửa riêng). Giá trị đã điền giữ nguyên; biến mới của mẫu nhận giá trị mặc định."""
        self._check_content_editable()
        for rec in self.with_context(**{_NO_AUDIT: True}):
            had_custom = rec.doc_custom
            rec._snapshot_template()
            rec.write({'variable_values': rec._with_defaults(rec._doc_variables(), rec.variable_values)})
            rec._log('template', 'Lấy lại nội dung theo mẫu "%s"%s' % (
                rec.template_id.name, ', bỏ phần chữ đã sửa riêng' if had_custom else ''))

    def body_html_for_edit(self):
        """Nội dung hợp đồng dạng HTML để sửa chữ, biến hiện dạng {{Ten_Bien}}."""
        self.ensure_one()
        if self.doc_custom and self.doc_html:
            return self.doc_html
        return html_blocks.blocks_to_html(docx_io.read_docx(self._doc_bytes(), keep_fields=True))

    def save_custom_body(self, html, variable_edits=None):
        """Lưu chữ người dùng sửa trên riêng hợp đồng này (mẫu không đổi): dựng lại file Word từ
        nội dung, đồng bộ bộ biến theo các biến còn trong nội dung (biến mới chèn vào thì nhận nhãn
        trong variable_edits hoặc theo thư viện)."""
        self.ensure_one()
        self._check_content_editable()
        docx = docx_io.build_docx(html_blocks.html_to_blocks(html))
        names = docx_merge.list_merge_fields(docx)
        old_vars = {v['name']: v['label'] for v in self._doc_variables()}
        var_defs = contract_vars.merge_variable_defs(names, self._doc_variables(), variable_edits)
        new_vars = {v['name']: v['label'] for v in var_defs}
        details = ['Thêm ô: %s' % new_vars[n] for n in new_vars if n not in old_vars]
        details += ['Bỏ ô: %s' % old_vars[n] for n in old_vars if n not in new_vars]
        self.with_context(**{_NO_AUDIT: True}).write({
            'doc_html': html,
            'doc_file': base64.b64encode(docx),
            'doc_variables': var_defs,
            'doc_has_lines': any(contract_vars.is_line_variable(n) for n in names),
            'doc_system_fields': ','.join(n for n in names if contract_vars.is_system_variable(n)),
            'doc_custom': True,
            'variable_values': self._with_defaults(var_defs, self.variable_values),
        })
        self._log('body', 'Sửa chữ trên nội dung hợp đồng (mẫu gốc không đổi)', details)

    def _next_contract_number(self, template, partner, company_id=None, exclude_id=None):
        """Số hợp đồng theo khuôn của mẫu, ngày soạn = hôm nay. Chỉ lấy số thứ tự (ir.sequence)
        khi khuôn có {seq}. Trùng số hợp đồng khác thì thêm -2, -3…"""
        pattern = template.number_pattern or DEFAULT_NUMBER_PATTERNS.get(template.contract_type)
        today = fields.Date.context_today(self)
        seq = None
        if contract_number.uses_sequence(pattern) and _SEQUENCE_CODE.get(template.contract_type):
            raw = self.env['ir.sequence'].with_context(ir_sequence_date=today).next_by_code(
                _SEQUENCE_CODE[template.contract_type], sequence_date=today)
            # Dãy số cũ có tiền tố/hậu tố (HĐNT-007/2026): lấy cụm số đầu tiên làm số thứ tự
            match = re.search(r'\d+', raw or '')
            seq = int(match.group(0)) if match else None
        company = partner.commercial_partner_id
        code = contract_number.customer_code(company.company_registry, company.name) if company else ''
        number = contract_number.build_number(pattern, today, seq, code)
        domain = [('company_id', '=', company_id or self.env.company.id)]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return contract_number.unique_number(
            number, lambda n: bool(self.with_context(active_test=False).search_count(domain + [('name', '=', n)])))

    def _refresh_auto_number(self):
        """Hợp đồng nháp còn số theo khuôn có {ma_khach} (không có {seq}): cấp lại số theo khách hiện tại."""
        for rec in self.filtered(lambda r: r.number_auto and r.state == 'draft'):
            pattern = rec.template_id.number_pattern or ''
            if contract_number.uses_customer(pattern) and not contract_number.uses_sequence(pattern):
                number = rec._next_contract_number(rec.template_id, rec.partner_id, rec.company_id.id, rec.id)
                if number != rec.name:
                    old = rec.name
                    # super(): không qua write của hợp đồng để số vẫn được coi là theo khuôn
                    super(Contract, rec).write({'name': number})
                    rec._log('update', 'Cấp lại số theo khách: %s → %s' % (old, number))

    @api.constrains('name', 'company_id')
    def _check_unique_number(self):
        for rec in self.filtered(lambda r: r.name and r.name != '/'):
            if self.search_count([('id', '!=', rec.id), ('name', '=', rec.name), ('company_id', '=', rec.company_id.id)]):
                raise ValidationError('Số hợp đồng %s đã có, hãy đặt số khác.' % rec.name)

    def set_variable(self, name, value):
        """Ghi một biến nhập (ô trong bảng dữ liệu). Tên phải là biến của mẫu hợp đồng này.
        Gõ tay tên bên mua khác tên khách đang gắn thì bỏ gắn khách (không còn là khách đó)."""
        self.ensure_one()
        if name not in [v['name'] for v in self._doc_variables()]:
            raise UserError('Hợp đồng %s không có ô %s.' % (self.name, name))
        values = dict(self.variable_values or {})
        values[name] = value
        vals = {'variable_values': values}
        if name == 'Ten_Ben_Mua' and self.partner_id and value != self.partner_id.commercial_partner_id.name:
            vals['partner_id'] = False
        self.write(vals)

    def apply_partner(self, partner):
        """Gắn khách và điền các biến bên mua mẫu này có (ghi đè giá trị đang có)."""
        self.ensure_one()
        names = {v['name'] for v in self._doc_variables()}
        values = dict(self.variable_values or {})
        values.update({k: v for k, v in self._buyer_values_from_partner(partner).items() if k in names})
        self.write({'partner_id': partner.id, 'variable_values': values})

    # ---------- dựng file ----------

    def _var_styles(self):
        """Kiểu chữ đặt cho từng biến (đậm, in hoa...) theo bản chụp của hợp đồng."""
        return {v['name']: v['style'] for v in self._doc_variables() if v.get('style')}

    def _merge_vars(self, with_overrides=True):
        """Dict {tên biến: chữ in ra} cho fill_docx. with_overrides=False: giá trị tự tính, chưa áp
        phần người soạn sửa đè (để hiện làm gợi ý)."""
        self.ensure_one()
        system = dict(self.company_id._contract_seller_vars(), So_Hop_Dong=self.name, Ngay_Ky=self.contract_date)
        input_types = {var['name']: var['var_type'] for var in self._doc_variables()}
        lines = [{
            'Ten_Hang': line.product_name,
            'DVT': line.uom,
            'So_Luong': line.quantity,
            'Don_Gia': line.price_unit,
        } for line in self.line_ids]
        values = contract_vars.build_vars(system, self.variable_values or {}, input_types, lines, self.vat_rate)
        if with_overrides:
            values.update({k: v for k, v in (self.overrides or {}).items() if v not in (None, '') and k in values})
        return values

    def _system_fields(self):
        """Biến tự điền có trong nội dung hợp đồng mà người soạn được sửa đè: bỏ số hợp đồng (sửa ở ô
        Số hợp đồng) và biến dòng hàng (sửa ở bảng hàng)."""
        self.ensure_one()
        names = (self.doc_system_fields if self._has_snapshot() else self.template_id.system_fields) or ''
        return [n for n in names.split(',') if n and n != 'So_Hop_Dong' and not contract_vars.is_line_variable(n)]

    def _render_docx_bytes(self):
        """File .docx của hợp đồng này, đã điền đủ biến."""
        self.ensure_one()
        try:
            return docx_merge.fill_docx(self._doc_bytes(), self._merge_vars(), line_count=len(self.line_ids),
                                         styles=self._var_styles())
        except ValueError as err:
            raise UserError('Không điền được mẫu "%s": %s' % (self.template_id.name, err))

    def _preview_html(self):
        """Bản xem trước khi đang soạn: như bản in, nhưng mỗi biến nhập được đánh dấu (đã điền /
        còn trống, trống thì hiện nhãn) để người soạn thấy ô nào nằm chỗ nào trên hợp đồng.
        Chạy được cả với hợp đồng chưa lưu (record new()) — số hợp đồng khi đó chưa có."""
        self.ensure_one()
        values = self._merge_vars()
        for var in self._doc_variables():
            text = values.get(var['name']) or ''
            values[var['name']] = preview_marks.mark(var['name'], text or var['label'], not text)
        if values.get('So_Hop_Dong') in ('', '/', False):
            values['So_Hop_Dong'] = preview_marks.mark('So_Hop_Dong', 'số tự cấp khi lưu', True)
        try:
            docx = docx_merge.fill_docx(self._doc_bytes(), values, line_count=len(self.line_ids),
                                        styles=self._var_styles())
        except ValueError as err:
            raise UserError('Không điền được mẫu "%s": %s' % (self.template_id.name, err))
        html = html_blocks.blocks_to_html(docx_io.read_docx(docx, keep_fields=False))
        return preview_marks.marks_to_html(html)

    def _render_html_fragment(self):
        """Nội dung hợp đồng dạng HTML (không có thẻ html/body), dùng cho xem nhanh và PDF."""
        self.ensure_one()
        blocks = docx_io.read_docx(self._render_docx_bytes(), keep_fields=False)
        return html_blocks.blocks_to_html(blocks)

    # ---------- chuyển trạng thái ----------

    def action_confirm(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'confirmed'})

    def action_sign(self):
        self.filtered(lambda r: r.state == 'confirmed').write({'state': 'signed'})

    def action_cancel(self):
        if not self._is_manager():
            raise AccessError('Chỉ Quản lý hợp đồng được huỷ hợp đồng.')
        self.filtered(lambda r: r.state != 'cancel').write({'state': 'cancel'})

    def action_draft(self):
        """Đưa về Nháp để sửa: nhân viên được làm với hợp đồng Đã xác nhận của mình (chưa ký);
        hợp đồng đã ký hoặc đã huỷ chỉ Quản lý mở lại."""
        if not self._is_manager() and self.filtered(lambda r: r.state != 'confirmed'):
            raise AccessError('Chỉ Quản lý được mở lại hợp đồng đã ký hoặc đã huỷ.')
        self.filtered(lambda r: r.state != 'draft').write({'state': 'draft'})
