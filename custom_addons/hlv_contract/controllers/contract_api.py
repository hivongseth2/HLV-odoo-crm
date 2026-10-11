# -*- coding: utf-8 -*-
"""Trang /hop-dong: danh sách, soạn, chuyển trạng thái, xem nhanh và xuất hợp đồng.

Trang tự dựng như /hoi-gia-ncc (QWeb + JS thuần), không dùng form backend. API mẫu hợp
đồng và thông tin bên bán ở template_api.py.
"""

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request

from ..models.contract import FORM_FIELDS, STATES
from ..models.contract_template import CONTRACT_TYPES
from ..services import contract_payload as payload
from ..services.asset_version import asset_version
from ..services.contract_export import FORMATS, export_contracts
from ..utils.contract_vars import compute_totals, line_subtotal
from .common import API, PAGE_ROUTE, ContractPageMixin, parse_ids, to_int

PER_PAGE = 40
PARTNER_LIMIT = 15
_ACTIONS = {
    'confirm': 'action_confirm',
    'sign': 'action_sign',
    'draft': 'action_draft',
    'cancel': 'action_cancel',
}


def _clean_form_values(values):
    """Giữ đúng các field form được ghi, đổi giá trị rỗng về kiểu Odoo cần."""
    vals = {}
    for name in FORM_FIELDS:
        if name not in values:
            continue
        value = values[name]
        if name in ('partner_id', 'template_id'):
            value = to_int(value) or False
        elif name in ('contract_date', 'expiry_date'):
            value = value or False
        elif name == 'vat_rate':
            value = float(value or 0)
        elif isinstance(value, str):
            value = value.strip()
        vals[name] = value
    return vals


def _line_commands(lines):
    """Ghi lại toàn bộ dòng hàng theo thứ tự trên trang; dòng không có tên hàng bị bỏ."""
    commands = [(5, 0, 0)]
    for index, line in enumerate(lines or []):
        name = (line.get('product_name') or '').strip()
        if not name:
            continue
        commands.append((0, 0, {
            'sequence': index + 1,
            'product_name': name,
            'uom': (line.get('uom') or '').strip(),
            'quantity': float(line.get('quantity') or 0),
            'price_unit': float(line.get('price_unit') or 0),
        }))
    return commands


class ContractPage(ContractPageMixin, http.Controller):

    @http.route(PAGE_ROUTE, type='http', auth='user', methods=['GET'])
    def contract_page(self, **kw):
        return request.render('hlv_contract.contract_page', {
            'asset_version': asset_version(),
            'allowed': self._allowed(),
        })

    @http.route(f'{API}/config', type='json', auth='user', methods=['POST'])
    def api_config(self, **kw):
        self._check()
        company = request.env.company
        templates = request.env['hlv.contract.template'].search([])
        return {
            'is_manager': self._is_manager(),
            'user_name': request.env.user.name,
            'today': fields.Date.to_string(fields.Date.context_today(request.env.user)),
            'types': CONTRACT_TYPES,
            'states': STATES,
            'templates': [payload.template_summary(t) for t in templates],
            'defaults': {'vat_rate': company.contract_vat_rate, 'court': company.contract_court or ''},
            'variables': payload.variable_groups(),
        }

    @http.route(f'{API}/list', type='json', auth='user', methods=['POST'])
    def api_list(self, search='', state='all', contract_type='', page=1, **kw):
        self._check()
        Contract = request.env['hlv.contract']
        base = []
        term = (search or '').strip()
        if term:
            base += ['|', '|', ('name', 'ilike', term), ('buyer_name', 'ilike', term), ('buyer_vat', 'ilike', term)]
        if contract_type:
            base.append(('contract_type', '=', contract_type))
        counts = {'all': Contract.search_count(base)}
        for key, _label in STATES:
            counts[key] = Contract.search_count(base + [('state', '=', key)])
        domain = base + ([('state', '=', state)] if state in counts and state != 'all' else [])
        total = Contract.search_count(domain)
        page = max(1, to_int(page) or 1)
        contracts = Contract.search(domain, offset=(page - 1) * PER_PAGE, limit=PER_PAGE)
        return {
            'contracts': [payload.contract_summary(c) for c in contracts],
            'counts': counts,
            'page': page,
            'pages': max(1, -(-total // PER_PAGE)),
            'total': total,
        }

    @http.route(f'{API}/get', type='json', auth='user', methods=['POST'])
    def api_get(self, contract_id=None, **kw):
        self._check()
        return payload.contract_detail(self._get_record('hlv.contract', contract_id), self._is_manager())

    @http.route(f'{API}/save', type='json', auth='user', methods=['POST'])
    def api_save(self, contract_id=None, values=None, lines=None, **kw):
        """Tạo mới (không có contract_id) hoặc ghi lại hợp đồng; trả chi tiết sau khi lưu."""
        self._check()
        vals = _clean_form_values(values or {})
        if lines is not None:
            vals['line_ids'] = _line_commands(lines)
        if to_int(contract_id):
            contract = self._get_record('hlv.contract', contract_id)
            contract.write(vals)
        else:
            contract = request.env['hlv.contract'].create(vals)
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{API}/action', type='json', auth='user', methods=['POST'])
    def api_action(self, contract_id=None, action='', **kw):
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        if action == 'delete':
            self._check_manager()
            contract.unlink()
            return {'deleted': True}
        if action not in _ACTIONS:
            raise UserError('Thao tác không hợp lệ.')
        getattr(contract, _ACTIONS[action])()
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{API}/totals', type='json', auth='user', methods=['POST'])
    def api_totals(self, lines=None, vat_rate=0, **kw):
        """Thành tiền từng dòng + tổng + chữ khi đang gõ, tính ở server bằng đúng hàm model dùng
        để JS không giữ bản sao quy tắc tính tiền."""
        self._check()
        subtotals = [line_subtotal(l.get('quantity'), l.get('price_unit')) for l in (lines or [])]
        return dict(compute_totals(subtotals, vat_rate), subtotals=subtotals)

    @http.route(f'{API}/partners', type='json', auth='user', methods=['POST'])
    def api_partners(self, search='', **kw):
        self._check()
        Partner = request.env['res.partner']
        term = (search or '').strip()
        domain = ['|', '|', ('name', 'ilike', term), ('vat', 'ilike', term), ('ref', 'ilike', term)] if term else []
        Contract = request.env['hlv.contract']
        return [{
            'id': partner.id,
            'label': partner.display_name,
            'vat': partner.commercial_partner_id.vat or '',
            'values': Contract._buyer_values_from_partner(partner),
        } for partner in Partner.search(domain, limit=PARTNER_LIMIT)]

    @http.route(f'{API}/preview', type='json', auth='user', methods=['POST'])
    def api_preview(self, contract_id=None, **kw):
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        return {'name': contract.name, 'html': contract._render_html_fragment()}

    @http.route(f'{PAGE_ROUTE}/xuat', type='http', auth='user', methods=['GET'])
    def export(self, ids='', fmt='pdf', **kw):
        """Tải file: ?ids=1,2,3&fmt=pdf|docx|xlsx. Trả file thẳng, không lưu đính kèm."""
        self._check()
        if fmt not in FORMATS:
            raise UserError('Định dạng không hỗ trợ.')
        contracts = request.env['hlv.contract'].browse(parse_ids(ids)).exists()
        if not contracts:
            raise UserError('Chưa chọn hợp đồng nào.')
        contracts.check_access('read')
        filename, content, mimetype = export_contracts(contracts, fmt)
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(filename)),
        ])
