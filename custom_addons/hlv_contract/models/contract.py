# -*- coding: utf-8 -*-
"""Hợp đồng mua bán hàng hoá / hợp đồng nguyên tắc, điền từ mẫu (xem contract_template).

Số hợp đồng lấy từ ir.sequence theo loại và năm (HĐMB-001/2026), không đếm theo thứ tự
dòng như form Excel cũ. Tổng tiền và chữ được tính lại ở đây; mẫu Word chỉ hiển thị.
Giao diện là trang /hop-dong (controllers/), không dùng form backend.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..utils import contract_vars, docx_io, docx_merge, html_blocks
from .contract_template import CONTRACT_TYPES

_SEQUENCE_CODE = {'sale': 'hlv.contract.sale', 'principle': 'hlv.contract.principle'}
STATES = [('draft', 'Nháp'), ('confirmed', 'Đã xác nhận'), ('signed', 'Đã ký'), ('cancel', 'Đã huỷ')]
# Field trang /hop-dong được ghi. Không có state/name/user_id: trạng thái đi qua action_*,
# số hợp đồng do sequence cấp.
FORM_FIELDS = (
    'contract_type', 'template_id', 'contract_date', 'expiry_date', 'partner_id',
    'buyer_name', 'buyer_address', 'buyer_vat', 'buyer_phone', 'buyer_fax',
    'buyer_representative', 'buyer_position', 'delivery_time', 'delivery_place',
    'payment_terms', 'court', 'main_product', 'vat_rate', 'note',
)
# Nội dung hợp đồng: khoá khi đã rời trạng thái Nháp (chặn ở server vì import/RPC vẫn ghi
# được dù giao diện khoá). Quản lý vẫn sửa được.
_CONTENT_FIELDS = set(FORM_FIELDS) - {'note'} | {'line_ids'}
MANAGER_GROUP = 'hlv_contract.group_contract_manager'
_DATE_FMT = '%d/%m/%Y'


class Contract(models.Model):
    _name = 'hlv.contract'
    _description = 'Hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'contract_date desc, id desc'

    name = fields.Char(string='Số hợp đồng', default='/', copy=False, readonly=True, tracking=True, index=True)
    contract_type = fields.Selection(CONTRACT_TYPES, string='Loại hợp đồng', required=True, default='sale',
                                     tracking=True)
    template_id = fields.Many2one('hlv.contract.template', string='Mẫu', required=True, tracking=True)
    state = fields.Selection(STATES, string='Trạng thái', default='draft', required=True, tracking=True, copy=False)
    contract_date = fields.Date(string='Ngày ký', required=True, default=fields.Date.context_today, tracking=True)
    expiry_date = fields.Date(string='Ngày hết hạn')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Nhân viên phụ trách', default=lambda self: self.env.user,
                              tracking=True, index=True)

    partner_id = fields.Many2one('res.partner', string='Khách hàng', tracking=True)
    buyer_name = fields.Char(string='Tên bên mua', required=True, tracking=True)
    buyer_address = fields.Char(string='Địa chỉ bên mua')
    buyer_vat = fields.Char(string='MST bên mua')
    buyer_phone = fields.Char(string='Điện thoại bên mua')
    buyer_fax = fields.Char(string='Fax bên mua')
    buyer_representative = fields.Char(string='Người đại diện bên mua')
    buyer_position = fields.Char(string='Chức vụ bên mua')

    delivery_time = fields.Char(string='Thời gian giao hàng')
    delivery_place = fields.Char(string='Địa điểm giao hàng')
    payment_terms = fields.Text(string='Điều kiện thanh toán')
    court = fields.Char(string='Toà án giải quyết', default=lambda self: self.env.company.contract_court)
    main_product = fields.Char(string='Mặt hàng chính', help='Dùng cho hợp đồng nguyên tắc')
    vat_rate = fields.Float(string='Thuế suất VAT (%)', default=lambda self: self.env.company.contract_vat_rate)

    line_ids = fields.One2many('hlv.contract.line', 'contract_id', string='Hàng hoá', copy=True)
    amount_untaxed = fields.Monetary(string='Tổng tiền hàng', compute='_compute_amounts', store=True,
                                     currency_field='currency_id')
    amount_vat = fields.Monetary(string='Tiền thuế VAT', compute='_compute_amounts', store=True,
                                 currency_field='currency_id')
    amount_total = fields.Monetary(string='Tổng giá trị', compute='_compute_amounts', store=True,
                                   currency_field='currency_id', tracking=True)
    amount_words = fields.Char(string='Bằng chữ', compute='_compute_amounts', store=True)
    note = fields.Text(string='Ghi chú')

    @api.depends('line_ids.subtotal', 'vat_rate')
    def _compute_amounts(self):
        for rec in self:
            totals = contract_vars.compute_totals(rec.line_ids.mapped('subtotal'), rec.vat_rate)
            rec.amount_untaxed = totals['untaxed']
            rec.amount_vat = totals['vat']
            rec.amount_total = totals['total']
            rec.amount_words = totals['words']

    @api.constrains('template_id', 'contract_type')
    def _check_template_type(self):
        for rec in self:
            if rec.template_id and rec.template_id.contract_type != rec.contract_type:
                raise ValidationError('Mẫu "%s" không đúng loại hợp đồng.' % rec.template_id.name)

    @api.model
    def _buyer_values_from_partner(self, partner):
        """Thông tin bên mua điền sẵn khi chọn khách. Bên mua là pháp nhân: chọn người liên
        hệ thì lấy công ty cha, người liên hệ thành người đại diện. Địa chỉ gộp một dòng."""
        company = partner.commercial_partner_id
        address_lines = (company.contact_address or '').splitlines()
        values = {
            'partner_id': partner.id,
            'buyer_name': company.name or '',
            'buyer_address': ', '.join(line.strip() for line in address_lines if line.strip()),
            'buyer_vat': company.vat or '',
            'buyer_phone': company.phone or partner.phone or '',
        }
        if partner != company:
            values.update({'buyer_representative': partner.name or '', 'buyer_position': partner.function or ''})
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') in ('/', False):
                vals['name'] = self._next_contract_number(vals)
        return super().create(vals_list)

    def write(self, vals):
        if _CONTENT_FIELDS.intersection(vals):
            self._check_content_editable()
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

    def _next_contract_number(self, vals):
        contract_type = vals.get('contract_type') or self.default_get(['contract_type']).get('contract_type')
        code = _SEQUENCE_CODE.get(contract_type)
        if not code:
            return '/'
        sequence_date = vals.get('contract_date') or fields.Date.context_today(self)
        return self.env['ir.sequence'].with_context(ir_sequence_date=sequence_date).next_by_code(
            code, sequence_date=sequence_date)

    # ---------- dựng file ----------

    def _merge_values(self):
        """Giá trị thô đưa vào contract_vars.build_vars, định dạng để build_vars lo."""
        self.ensure_one()
        values = {
            'So_Hop_Dong': self.name,
            'Ngay_Ky': self.contract_date,
            'Ten_Ben_Mua': self.buyer_name,
            'Dia_Chi_Ben_Mua': self.buyer_address,
            'Ma_So_Thue_Ben_Mua': self.buyer_vat,
            'Dien_Thoai_Ben_Mua': self.buyer_phone,
            'Fax_Ben_Mua': self.buyer_fax,
            'Nguoi_Dai_Dien_Ben_Mua': self.buyer_representative,
            'Chuc_Vu_Ben_Mua': self.buyer_position,
            'Thoi_Gian_Giao_Hang': self.delivery_time,
            'Dia_Diem_Giao_Hang': self.delivery_place,
            'Dieu_Kien_Thanh_Toan': self.payment_terms,
            'Ngay_Het_Han': self.expiry_date.strftime(_DATE_FMT) if self.expiry_date else '',
            'Toa_An_Giai_Quyet': self.court,
            'Mat_Hang_Chinh': self.main_product,
            'Thue_Suat_VAT': self.vat_rate,
            'lines': [{
                'Ten_Hang': line.product_name,
                'DVT': line.uom,
                'So_Luong': line.quantity,
                'Don_Gia': line.price_unit,
                'Thanh_Tien': line.subtotal,
            } for line in self.line_ids],
        }
        values.update(self.company_id._contract_seller_vars())
        return values

    def _render_docx_bytes(self):
        """File .docx của hợp đồng này, đã điền đủ biến."""
        self.ensure_one()
        filled = contract_vars.build_vars(self._merge_values())
        try:
            return docx_merge.fill_docx(self.template_id._docx_bytes(), filled,
                                         line_count=len(self.line_ids))
        except ValueError as err:
            raise UserError('Không điền được mẫu "%s": %s' % (self.template_id.name, err))

    def _render_html_fragment(self):
        """Nội dung hợp đồng dạng HTML (không có thẻ html/body), dùng cho xem nhanh và PDF."""
        self.ensure_one()
        blocks = docx_io.read_docx(self._render_docx_bytes(), keep_fields=False)
        return html_blocks.blocks_to_html(blocks)

    def _excel_row(self):
        """Một dòng cho file Excel, theo cột CONTRACT_XLSX_COLUMNS, số để nguyên kiểu."""
        self.ensure_one()
        row = {
            'So_Hop_Dong': self.name,
            'Loai_Hop_Dong': dict(CONTRACT_TYPES).get(self.contract_type),
            'Ngay_Ky': self.contract_date,
            'Ngay_Het_Han': self.expiry_date,
            'Ten_Ben_Mua': self.buyer_name,
            'Dia_Chi_Ben_Mua': self.buyer_address,
            'Ma_So_Thue_Ben_Mua': self.buyer_vat,
            'Dien_Thoai_Ben_Mua': self.buyer_phone,
            'Fax_Ben_Mua': self.buyer_fax,
            'Nguoi_Dai_Dien_Ben_Mua': self.buyer_representative,
            'Chuc_Vu_Ben_Mua': self.buyer_position,
            'Mat_Hang_Chinh': self.main_product,
            'Thoi_Gian_Giao_Hang': self.delivery_time,
            'Dia_Diem_Giao_Hang': self.delivery_place,
            'Dieu_Kien_Thanh_Toan': self.payment_terms,
            'Toa_An_Giai_Quyet': self.court,
            'Tong_Tien_Hang': self.amount_untaxed,
            'Thue_Suat_VAT': self.vat_rate,
            'Tien_Thue_VAT': self.amount_vat,
            'Tong_Gia_Tri_HD': self.amount_total,
            'Tong_Gia_Tri_Bang_Chu': self.amount_words,
            'Trang_Thai': dict(STATES).get(self.state),
            'Ghi_Chu': self.note,
        }
        for idx, line in enumerate(self.line_ids, start=1):
            row.update({
                'Ten_Hang_%d' % idx: line.product_name,
                'DVT_%d' % idx: line.uom,
                'So_Luong_%d' % idx: line.quantity,
                'Don_Gia_%d' % idx: line.price_unit,
                'Thanh_Tien_%d' % idx: line.subtotal,
            })
        return row

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
