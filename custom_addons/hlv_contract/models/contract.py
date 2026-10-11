# -*- coding: utf-8 -*-
"""Hợp đồng điền từ mẫu (xem contract_template).

Giá trị các biến nhập lưu trong variable_values (JSON {tên biến: giá trị}) vì mỗi mẫu có
bộ biến riêng, giống mỗi sheet Excel cũ có cột riêng. Số hợp đồng lấy từ ir.sequence theo
loại và năm (HĐMB-001/2026). Tổng tiền và chữ được tính ở đây; mẫu Word chỉ hiển thị.
Giao diện là trang /hop-dong (controllers/), không dùng form backend.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..utils import contract_vars, docx_io, docx_merge, html_blocks, preview_marks

_SEQUENCE_CODE = {'sale': 'hlv.contract.sale', 'principle': 'hlv.contract.principle'}
STATES = [('draft', 'Nháp'), ('confirmed', 'Đã xác nhận'), ('signed', 'Đã ký'), ('cancel', 'Đã huỷ')]
# Nội dung hợp đồng: khoá khi đã rời trạng thái Nháp (chặn ở server vì import/RPC vẫn ghi
# được dù giao diện khoá). Quản lý vẫn sửa được. Ghi chú nội bộ luôn sửa được.
_CONTENT_FIELDS = {'template_id', 'contract_date', 'partner_id', 'variable_values', 'vat_rate', 'line_ids'}
MANAGER_GROUP = 'hlv_contract.group_contract_manager'
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

    def _template_defaults(self, template, values):
        """values + giá trị mặc định của biến mẫu chưa có giá trị. Toà án mặc định lấy theo
        cấu hình công ty nếu biến không khai mặc định riêng."""
        merged = dict(values or {})
        for var in template.variable_ids:
            if merged.get(var.name) not in (None, ''):
                continue
            default = var.default_value
            if not default and var.name == 'Toa_An_Giai_Quyet':
                default = self.env.company.contract_court
            if default:
                merged[var.name] = default
        return merged

    @api.model_create_multi
    def create(self, vals_list):
        Template = self.env['hlv.contract.template']
        for vals in vals_list:
            template = Template.browse(vals.get('template_id'))
            vals['variable_values'] = self._template_defaults(template, vals.get('variable_values'))
            if vals.get('name', '/') in ('/', False):
                vals['name'] = self._next_contract_number(template, vals.get('contract_date'))
        return super().create(vals_list)

    def write(self, vals):
        if _CONTENT_FIELDS.intersection(vals):
            self._check_content_editable()
        if vals.get('template_id') and len(self) == 1:
            template = self.env['hlv.contract.template'].browse(vals['template_id'])
            vals['variable_values'] = self._template_defaults(
                template, vals.get('variable_values', self.variable_values))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.state not in ('draft', 'cancel')):
            raise UserError('Chỉ xoá được hợp đồng Nháp hoặc Đã huỷ.')
        return super().unlink()

    def _is_manager(self):
        return self.env.su or self.env.user.has_group(MANAGER_GROUP)

    def _check_content_editable(self):
        """Chặn sửa nội dung hợp đồng đã xác nhận/ký, trừ Quản lý."""
        if self._is_manager():
            return
        locked = self.filtered(lambda r: r.state != 'draft')
        if locked:
            raise UserError('Hợp đồng %s không còn ở trạng thái Nháp, chỉ Quản lý được sửa nội dung.'
                            % ', '.join(locked.mapped('name')))

    def _next_contract_number(self, template, contract_date):
        code = _SEQUENCE_CODE.get(template.contract_type)
        if not code:
            return '/'
        sequence_date = contract_date or fields.Date.context_today(self)
        return self.env['ir.sequence'].with_context(ir_sequence_date=sequence_date).next_by_code(
            code, sequence_date=sequence_date)

    def set_variable(self, name, value):
        """Ghi một biến nhập (ô trong bảng dữ liệu). Tên phải là biến của mẫu hợp đồng này.
        Gõ tay tên bên mua khác tên khách đang gắn thì bỏ gắn khách (không còn là khách đó)."""
        self.ensure_one()
        if name not in self.template_id.variable_ids.mapped('name'):
            raise UserError('Mẫu "%s" không có biến %s.' % (self.template_id.name, name))
        values = dict(self.variable_values or {})
        values[name] = value
        vals = {'variable_values': values}
        if name == 'Ten_Ben_Mua' and self.partner_id and value != self.partner_id.commercial_partner_id.name:
            vals['partner_id'] = False
        self.write(vals)

    def apply_partner(self, partner):
        """Gắn khách và điền các biến bên mua mẫu này có (ghi đè giá trị đang có)."""
        self.ensure_one()
        names = set(self.template_id.variable_ids.mapped('name'))
        values = dict(self.variable_values or {})
        values.update({k: v for k, v in self._buyer_values_from_partner(partner).items() if k in names})
        self.write({'partner_id': partner.id, 'variable_values': values})

    # ---------- dựng file ----------

    def _merge_vars(self):
        """Dict {tên biến: chữ in ra} cho fill_docx."""
        self.ensure_one()
        system = dict(self.company_id._contract_seller_vars(), So_Hop_Dong=self.name, Ngay_Ky=self.contract_date)
        input_types = {var.name: var.var_type for var in self.template_id.variable_ids}
        lines = [{
            'Ten_Hang': line.product_name,
            'DVT': line.uom,
            'So_Luong': line.quantity,
            'Don_Gia': line.price_unit,
        } for line in self.line_ids]
        return contract_vars.build_vars(system, self.variable_values or {}, input_types, lines, self.vat_rate)

    def _render_docx_bytes(self):
        """File .docx của hợp đồng này, đã điền đủ biến."""
        self.ensure_one()
        try:
            return docx_merge.fill_docx(self.template_id._docx_bytes(), self._merge_vars(),
                                         line_count=len(self.line_ids))
        except ValueError as err:
            raise UserError('Không điền được mẫu "%s": %s' % (self.template_id.name, err))

    def _preview_html(self):
        """Bản xem trước khi đang soạn: như bản in, nhưng mỗi biến nhập được đánh dấu (đã điền /
        còn trống, trống thì hiện nhãn) để người soạn thấy ô nào nằm chỗ nào trên hợp đồng.
        Chạy được cả với hợp đồng chưa lưu (record new()) — số hợp đồng khi đó chưa có."""
        self.ensure_one()
        values = self._merge_vars()
        for var in self.template_id.variable_ids:
            text = values.get(var.name) or ''
            values[var.name] = preview_marks.mark(var.name, text or var.label, not text)
        if values.get('So_Hop_Dong') in ('', '/', False):
            values['So_Hop_Dong'] = preview_marks.mark('So_Hop_Dong', 'số tự cấp khi lưu', True)
        try:
            docx = docx_merge.fill_docx(self.template_id._docx_bytes(), values, line_count=len(self.line_ids))
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
