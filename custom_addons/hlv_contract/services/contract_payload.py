# -*- coding: utf-8 -*-
"""Đổi record thành dict JSON cho trang /hop-dong. Chỉ đọc, không ghi gì.

Ngày trả dạng 'YYYY-MM-DD' (đúng định dạng ô <input type="date">), số để nguyên kiểu số;
JS lo hiển thị.
"""

from odoo import fields

from ..models.contract import STATES
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
    """Một dòng trong danh sách tổng hợp."""
    return {
        'id': contract.id,
        'name': contract.name,
        'template_id': contract.template_id.id,
        'template_name': contract.template_id.name or '',
        'contract_date': _date(contract.contract_date),
        'party_name': contract.party_name or '',
        'party_vat': contract.party_vat or '',
        'amount_total': contract.amount_total,
        'has_lines': contract.template_id.has_lines,
        'state': contract.state,
        'state_label': STATE_LABELS.get(contract.state, ''),
        'user': contract.user_id.name or '',
    }


def _lines(contract):
    rate = contract.vat_rate
    return [{
        'id': line.id,
        'product_id': line.product_id.id or False,
        'product_name': line.product_name,
        'uom': line.uom or '',
        'quantity': line.quantity,
        'price_unit': line.price_unit,
        'price_incl': contract_vars.price_incl(line.price_unit, rate),
        'subtotal': line.subtotal,
        'subtotal_incl': contract_vars.price_incl(line.subtotal, rate),
    } for line in contract.line_ids]


def contract_detail(contract, can_manage):
    """Đủ dữ liệu cho ngăn soạn hợp đồng. can_manage: người xem thuộc nhóm Quản lý."""
    detail = contract_summary(contract)
    detail.update({
        'values': dict(contract.variable_values or {}),
        'partner_id': contract.partner_id.id or False,
        'partner_label': contract.partner_id.display_name or '',
        'vat_rate': contract.vat_rate,
        'note': contract.note or '',
        'lines': _lines(contract),
        'amount_untaxed': contract.amount_untaxed,
        'amount_vat': contract.amount_vat,
        'amount_words': contract.amount_words or '',
        'editable': contract.state == 'draft' or can_manage,
        'actions': _allowed_actions(contract, can_manage),
    })
    return detail


def grid_row(contract, can_manage):
    """Một dòng trong bảng dữ liệu kiểu Excel của một mẫu."""
    row = contract_summary(contract)
    row.update({
        'values': dict(contract.variable_values or {}),
        'lines': [{'name': line.product_name, 'quantity': line.quantity} for line in contract.line_ids],
        'editable': contract.state == 'draft' or can_manage,
    })
    return row


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
        'has_lines': template.has_lines,
        'variables': [var._to_dict() for var in template.variable_ids],
    }


def template_detail(template):
    """Chi tiết mẫu cho màn soạn mẫu; file hỏng thì báo lỗi thay vì vỡ trang."""
    detail = template_summary(template)
    system = [n for n in (template.system_fields or '').split(',') if n]
    detail.update({
        'body_html': (template.body_html or '') if template.source == 'builder' else '',
        'note': template.note or '',
        'system_fields': [{'name': n, 'label': contract_vars.SYSTEM_LABELS.get(n, n)} for n in system],
    })
    return detail


def variable_library():
    """Thư viện biến cho trình soạn mẫu: biến chuẩn (gợi ý nhãn/kiểu, tự điền khi chọn khách)
    và biến tự điền (không cần nhập). Biến dòng hàng chỉ đưa dòng 1: bảng hàng chỉ cần một
    dòng mẫu, hợp đồng nhiều mặt hàng thì dòng đó tự nhân bản khi xuất."""
    def items(names):
        return [{'name': n, 'label': contract_vars.SYSTEM_LABELS.get(n, n)} for n in names]

    standard = [dict(contract_vars.default_variable_def(n)) for n in contract_vars.STANDARD_VARIABLES]
    return {
        'standard': standard,
        'system': [
            {'title': 'Số & ngày hợp đồng', 'items': items(contract_vars.DATE_VARIABLES)},
            {'title': 'Bên bán (cấu hình công ty)', 'items': items(contract_vars.SELLER_VARIABLES)},
            {'title': 'Bảng hàng hoá — dùng trong bảng hàng', 'items': items(
                ['%s_1' % f for f in contract_vars.LINE_FIELDS])},
            {'title': 'Tổng tiền — tính từ bảng hàng', 'items': items(contract_vars.TOTAL_VARIABLES)},
        ],
        'types': contract_vars.VARIABLE_TYPES,
        'sections': contract_vars.SECTIONS,
    }


def seller_values(company):
    return {name: company[name] or ('' if name != 'contract_vat_rate' else 0) for name in SELLER_FIELDS}
