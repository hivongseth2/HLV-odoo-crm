# -*- coding: utf-8 -*-
"""Đổi record thành dict JSON cho trang /hop-dong. Chỉ đọc, không ghi gì.

Ngày trả dạng 'YYYY-MM-DD' (đúng định dạng ô <input type="date">), số để nguyên kiểu số;
JS lo hiển thị.
"""

from odoo import fields

from ..models.contract import FORM_FIELDS, STATES
from ..models.contract_template import CONTRACT_TYPES
from ..utils import contract_vars

STATE_LABELS = dict(STATES)
TYPE_LABELS = dict(CONTRACT_TYPES)
SELLER_FIELDS = (
    'contract_seller_name', 'contract_seller_address', 'contract_seller_phone', 'contract_seller_vat',
    'contract_seller_representative', 'contract_seller_position', 'contract_seller_bank_account',
    'contract_seller_bank_name', 'contract_court', 'contract_vat_rate',
)


def _date(value):
    return fields.Date.to_string(value) if value else ''


def contract_summary(contract):
    """Một dòng trong danh sách."""
    return {
        'id': contract.id,
        'name': contract.name,
        'contract_type': contract.contract_type,
        'type_label': TYPE_LABELS.get(contract.contract_type, ''),
        'contract_date': _date(contract.contract_date),
        'buyer_name': contract.buyer_name or '',
        'buyer_vat': contract.buyer_vat or '',
        'amount_total': contract.amount_total,
        'state': contract.state,
        'state_label': STATE_LABELS.get(contract.state, ''),
        'user': contract.user_id.name or '',
        'line_count': len(contract.line_ids),
    }


def _form_value(contract, name):
    """Giá trị một field của form: ngày -> chuỗi, many2one -> id (False nếu trống), số giữ
    nguyên, chữ trống -> ''."""
    field = contract._fields[name]
    value = contract[name]
    if field.type == 'date':
        return _date(value)
    if field.type == 'many2one':
        return value.id or False
    if field.type in ('float', 'integer', 'monetary'):
        return value
    return value or ''


def contract_detail(contract, can_manage):
    """Đủ dữ liệu cho ngăn soạn hợp đồng. can_manage: người xem thuộc nhóm Quản lý."""
    detail = contract_summary(contract)
    detail.update({
        'values': {name: _form_value(contract, name) for name in FORM_FIELDS},
        'partner_label': contract.partner_id.display_name or '',
        'lines': [{
            'id': line.id,
            'product_name': line.product_name,
            'uom': line.uom or '',
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'subtotal': line.subtotal,
        } for line in contract.line_ids],
        'amount_untaxed': contract.amount_untaxed,
        'amount_vat': contract.amount_vat,
        'amount_words': contract.amount_words or '',
        'editable': contract.state == 'draft' or can_manage,
        'actions': _allowed_actions(contract, can_manage),
    })
    return detail


def _allowed_actions(contract, can_manage):
    """Nút chuyển trạng thái hiện trên ngăn soạn, khớp kiểm quyền trong model."""
    state = contract.state
    actions = []
    if state == 'draft':
        actions.append('confirm')
    if state == 'confirmed':
        actions += ['sign', 'draft']
    if can_manage and state in ('signed', 'cancel'):
        actions.append('draft')
    if can_manage and state != 'cancel':
        actions.append('cancel')
    if can_manage and state in ('draft', 'cancel'):
        actions.append('delete')
    return actions


def template_summary(template):
    return {
        'id': template.id,
        'name': template.name,
        'contract_type': template.contract_type,
        'type_label': TYPE_LABELS.get(template.contract_type, ''),
        'source': template.source,
        'filename': template.docx_filename or '',
        'active': template.active,
    }


def template_detail(template):
    try:
        field_report = template._field_report()
        file_error = ''
    except ValueError as err:
        field_report, file_error = [], str(err)
    detail = template_summary(template)
    detail.update({
        'body_html': (template.body_html or '') if template.source == 'builder' else '',
        'note': template.note or '',
        'fields': field_report,
        'file_error': file_error,
    })
    return detail


def variable_groups():
    """Bảng biến cho trình soạn mẫu. Dòng hàng chỉ đưa dòng 1: bảng hàng chỉ cần một dòng mẫu,
    hợp đồng nhiều dòng hơn thì dòng cuối tự nhân bản khi xuất."""
    groups = [
        ('Hợp đồng & bên mua', contract_vars.HEADER_VARIABLES),
        ('Tổng tiền', contract_vars.TOTAL_VARIABLES),
        ('Bên bán (cấu hình công ty)', contract_vars.SELLER_VARIABLES),
        ('Dòng hàng', ['%s_1' % f for f in contract_vars.LINE_FIELDS]),
    ]
    return [{
        'title': title,
        'items': [{'name': n, 'label': contract_vars.VARIABLE_LABELS.get(n, n)} for n in names],
    } for title, names in groups]


def seller_values(company):
    return {name: company[name] or ('' if name != 'contract_vat_rate' else 0) for name in SELLER_FIELDS}
