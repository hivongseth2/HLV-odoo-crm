# -*- coding: utf-8 -*-
"""Văn bản căn cứ vào văn bản khác, và đề nghị thanh toán theo đợt.

Chuỗi văn bản: hợp đồng nguyên tắc → phụ lục (mỗi đơn một phụ lục) → giấy đề nghị thanh toán (một
hay nhiều đợt). Văn bản con giữ parent_id; các biến So_HD_Goc, Ngay_Ky_HD_Goc… lấy từ văn bản gốc nên
câu "Căn cứ hợp đồng số … ký ngày …" không phải gõ tay.

Đề nghị thanh toán: số tiền đợt = giá trị văn bản gốc x tỷ lệ, hoặc số người soạn gõ tay. Khi còn
Nháp, giá trị gốc và tổng các đợt trước lấy trực tiếp từ văn bản gốc; mỗi lần ghi (kể cả lúc xác
nhận) chụp lại vào payment_base / payment_previous, nên giấy đã xác nhận không đổi số tiền khi văn
bản gốc hay đợt khác bị sửa sau đó.

Văn bản gốc có thể do nhân viên khác phụ trách (luật nhân viên chỉ thấy văn bản của mình): chỉ
đọc số, ngày, giá trị của nó bằng sudo, không mở thêm quyền sửa.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from ..utils import contract_vars
from ..utils.amount_words import amount_in_words_vi
from .contract import _NO_AUDIT
from .contract_template import PARENT_TYPES

_NO_FREEZE = 'hlv_contract_no_payment_freeze'


class ContractLink(models.Model):
    _inherit = 'hlv.contract'

    parent_id = fields.Many2one('hlv.contract', string='Căn cứ văn bản', index=True, ondelete='restrict',
                                tracking=True, copy=False)
    child_ids = fields.One2many('hlv.contract', 'parent_id', string='Văn bản căn cứ vào văn bản này')
    quote_code = fields.Char(string='Số báo giá CRM', copy=False,
                             help='Báo giá MISA CRM lấy hàng vào văn bản; dùng được trong khuôn số ({bao_gia}).')
    payment_no = fields.Integer(string='Đợt thanh toán', default=1, copy=False)
    payment_percent = fields.Float(string='Tỷ lệ đợt này (%)', default=100)
    payment_amount_manual = fields.Float(string='Số tiền đề nghị gõ tay',
                                         help='Để 0: số tiền = giá trị văn bản gốc x tỷ lệ.')
    payment_base = fields.Float(string='Giá trị văn bản gốc (đã chụp)', readonly=True, copy=False)
    payment_previous = fields.Float(string='Đã đề nghị các đợt trước (đã chụp)', readonly=True, copy=False)

    @api.constrains('parent_id', 'template_id')
    def _check_parent_type(self):
        labels = dict(self._fields['contract_type'].selection)
        for rec in self.filtered('parent_id'):
            allowed = PARENT_TYPES.get(rec.contract_type, ())
            parent_type = rec.parent_id.sudo().contract_type
            if rec.parent_id == rec or parent_type not in allowed:
                raise ValidationError('%s không căn cứ vào %s được.' % (
                    labels.get(rec.contract_type, 'Văn bản này'), labels.get(parent_type, 'văn bản đã chọn').lower()))

    # ---------- đề nghị thanh toán ----------

    def _is_payment(self):
        return self.contract_type == 'payment'

    def _earlier_payments(self):
        """Các đề nghị thanh toán chưa huỷ của cùng văn bản gốc, đứng trước đợt này."""
        own_id = self._origin.id
        key = (self.payment_no or 0, own_id or float('inf'))
        return self.parent_id.sudo().child_ids.filtered(
            lambda c: c.contract_type == 'payment' and c.state != 'cancel' and c.id != own_id
            and (c.payment_no or 0, c.id) < key)

    def _payment_base(self):
        if self.state == 'draft' and self.parent_id:
            return self.parent_id.sudo().amount_total
        return self.payment_base

    def _payment_previous(self):
        if self.state == 'draft' and self.parent_id:
            return sum(self._earlier_payments().mapped('amount_total'))
        return self.payment_previous

    def _payment_amount(self):
        return contract_vars.payment_amount(self._payment_base(), self.payment_percent, self.payment_amount_manual)

    @api.depends('contract_type', 'parent_id.amount_total', 'payment_base', 'payment_percent',
                 'payment_amount_manual', 'state')
    def _compute_amounts(self):
        payments = self.filtered(lambda r: r._is_payment())
        super(ContractLink, self - payments)._compute_amounts()
        for rec in payments:
            total = rec._payment_amount()
            untaxed = contract_vars.round_money(total / (1 + (rec.vat_rate or 0) / 100))
            rec.amount_total = total
            rec.amount_untaxed = untaxed
            rec.amount_vat = total - untaxed
            rec.amount_words = amount_in_words_vi(total)

    def _freeze_payment(self):
        """Chụp giá trị gốc và các đợt trước vào giấy đề nghị còn Nháp (xem docstring đầu file)."""
        for rec in self.filtered(lambda r: r._is_payment() and r.state == 'draft' and r.parent_id):
            vals = {'payment_base': rec._payment_base(), 'payment_previous': rec._payment_previous()}
            if any(float_compare(rec[k], v, precision_digits=2) for k, v in vals.items()):
                super(ContractLink, rec.with_context(**{_NO_FREEZE: True, _NO_AUDIT: True})).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._freeze_payment()
        return records

    def write(self, vals):
        if self.env.context.get(_NO_FREEZE):
            return super().write(vals)
        # Trước khi ghi: giấy đang Nháp sắp được xác nhận thì chụp số lúc còn Nháp
        self._freeze_payment()
        res = super().write(vals)
        self._freeze_payment()
        return res

    # ---------- biến in ra ----------

    def _link_vars(self):
        """Biến văn bản gốc + đợt thanh toán đã định dạng, cho _merge_vars."""
        self.ensure_one()
        parent = self.parent_id.sudo()
        out = {
            'So_HD_Goc': parent.name or '',
            'Ngay_Ky_HD_Goc': parent.contract_date.strftime('%d/%m/%Y') if parent.contract_date else '',
            'So_Bao_Gia': self.quote_code or parent.quote_code or '',
            'Gia_Tri_HD_Goc': contract_vars.format_money(parent.amount_total) if parent else '',
        }
        if self._is_payment():
            out.update(contract_vars.payment_vars(self.payment_no, self.payment_percent, self._payment_amount(),
                                                  self._payment_base(), self._payment_previous()))
        return out

    def _payment_summary(self):
        """Số liệu cho phần Thanh toán trên ngăn soạn."""
        self.ensure_one()
        base, previous, amount = self._payment_base(), self._payment_previous(), self._payment_amount()
        return {'base': base, 'previous': previous, 'amount': amount, 'remaining': base - previous - amount}

    # ---------- tạo văn bản con ----------

    def _child_defaults(self, child_type):
        """Giá trị điền sẵn cho văn bản mới loại child_type căn cứ vào văn bản này: khách, các ô đã
        điền (cùng tên biến là cùng thông tin), thuế suất; đề nghị thanh toán thêm đợt kế tiếp và tỷ
        lệ phần còn lại."""
        self.ensure_one()
        parent = self.sudo()
        defaults = {
            'parent_id': parent.id,
            'parent_label': '%s · %s' % (parent.name, parent.party_name or ''),
            'parent_type': parent.contract_type,
            'partner_id': parent.partner_id.id or False,
            'partner_label': parent.partner_id.display_name or '',
            'values': dict(parent.variable_values or {}),
            'vat_rate': parent.vat_rate,
            'quote_code': parent.quote_code or '',
        }
        if child_type == 'payment':
            earlier = parent.child_ids.filtered(lambda c: c.contract_type == 'payment' and c.state != 'cancel')
            requested = sum(earlier.mapped('amount_total'))
            remaining = max(parent.amount_total - requested, 0)
            defaults.update({
                'payment_base': parent.amount_total,
                'payment_previous': requested,
                'payment_no': max(earlier.mapped('payment_no') or [0]) + 1,
                'payment_percent': round(remaining * 100.0 / parent.amount_total, 2) if parent.amount_total else 100,
            })
        return defaults

    def _link_info_brief(self):
        """Số, loại, khách, ngày, giá trị của một văn bản — đủ để chọn làm văn bản gốc hoặc liệt kê."""
        self.ensure_one()
        types = dict(self._fields['contract_type'].selection)
        return {'id': self.id, 'name': self.name, 'type_label': types.get(self.contract_type, ''),
                'contract_type': self.contract_type, 'party_name': self.party_name or '',
                'amount_total': self.amount_total, 'state': self.state,
                'state_label': dict(self._fields['state'].selection).get(self.state, ''),
                'contract_date': fields.Date.to_string(self.contract_date) if self.contract_date else '',
                'payment_no': self.payment_no if self.contract_type == 'payment' else 0}

    def _link_info(self):
        """Văn bản gốc và các văn bản con, để hiện trên ngăn soạn."""
        self.ensure_one()
        parent = self.parent_id.sudo()
        children = self.sudo().child_ids.sorted(lambda c: (c.contract_type, c.payment_no, c.id))
        return {
            'parent': parent._link_info_brief() if parent else False,
            'children': [c._link_info_brief() for c in children],
        }
