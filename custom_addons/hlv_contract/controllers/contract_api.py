# -*- coding: utf-8 -*-
"""Trang /hop-dong: danh sách, bảng dữ liệu theo mẫu (kiểu Excel), soạn, chuyển trạng thái,
xem nhanh và xuất hợp đồng.

Trang tự dựng như /hoi-gia-ncc (QWeb + JS thuần), không dùng form backend. API mẫu hợp
đồng và thông tin bên bán ở template_api.py; ô tìm sản phẩm / đơn bán ở lookup_api.py.
"""

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request
from odoo.tools.misc import file_open

from ..models.contract import STATES
from ..models.contract_template import CONTRACT_TYPES
from ..services import contract_payload as payload
from ..services.asset_version import asset_version
from ..services.contract_export import FORMATS, export_contracts
from ..utils.contract_vars import compute_totals, line_prices, line_subtotal
from .common import API, PAGE_ROUTE, ContractPageMixin, parse_ids, to_int

GUIDE_FILE = 'hlv_contract/static/guide/huong-dan.html'
# File hướng dẫn viết theo khuôn trang Artifact (không có <html>/<head>) để đăng được nguyên văn;
# mở trong Odoo thì bọc thêm khung chuẩn, nếu không trình duyệt chạy chế độ quirks và đoán sai mã chữ
_GUIDE_SHELL = ('<!doctype html><html lang="vi"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>%s</body></html>')
PER_PAGE = 40
GRID_PER_PAGE = 80
_ACTIONS = {
    'confirm': 'action_confirm',
    'sign': 'action_sign',
    'draft': 'action_draft',
    'cancel': 'action_cancel',
}


def _line_commands(lines, vat_rate):
    """Ghi lại toàn bộ dòng hàng theo thứ tự trên trang; dòng không có tên hàng bị bỏ.
    Người dùng gõ giá sau VAT hoặc chưa VAT (price_basis cho biết ô nào); lưu giá chưa VAT."""
    commands = [(5, 0, 0)]
    for index, line in enumerate(lines or []):
        name = (line.get('product_name') or '').strip()
        if not name:
            continue
        commands.append((0, 0, {
            'sequence': index + 1,
            'product_id': to_int(line.get('product_id')) or False,
            'product_name': name,
            'uom': (line.get('uom') or '').strip(),
            'quantity': float(line.get('quantity') or 0),
            'price_unit': line_prices(line, vat_rate)[0],
        }))
    return commands


def _clean_values(var_names, values):
    """Chỉ giữ các biến được phép, chữ thì bỏ khoảng trắng hai đầu."""
    names = set(var_names)
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in (values or {}).items() if k in names}


def _var_names(contract, template):
    """Biến nhập ghi được: hợp đồng đang có giữ mẫu cũ thì theo bản chụp riêng của nó, đổi sang
    mẫu khác (hoặc hợp đồng mới) thì theo mẫu."""
    if contract and contract.template_id == template:
        return [v['name'] for v in contract._doc_variables()]
    return template.variable_ids.mapped('name')


class ContractPage(ContractPageMixin, http.Controller):

    @http.route(PAGE_ROUTE, type='http', auth='user', methods=['GET'])
    def contract_page(self, **kw):
        return request.render('hlv_contract.contract_page', {
            'asset_version': asset_version(),
            'allowed': self._allowed(),
        })

    @http.route(f'{PAGE_ROUTE}/huong-dan', type='http', auth='user', methods=['GET'])
    def guide(self, **kw):
        with file_open(GUIDE_FILE, 'rb') as handle:
            content = handle.read().decode('utf-8')
        return request.make_response(_GUIDE_SHELL % content, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route(f'{API}/config', type='json', auth='user', methods=['POST'])
    def api_config(self, **kw):
        self._check()
        templates = request.env['hlv.contract.template'].search([])
        return {
            'is_manager': self._is_manager(),
            'today': fields.Date.to_string(fields.Date.context_today(request.env.user)),
            'types': CONTRACT_TYPES,
            'states': STATES,
            'templates': [payload.template_summary(t) for t in templates],
            'default_vat': request.env.company.contract_vat_rate,
            'library': payload.variable_library(),
        }

    def _base_domain(self, search, template_id=None):
        domain = []
        term = (search or '').strip()
        if term:
            domain += ['|', '|', ('name', 'ilike', term), ('party_name', 'ilike', term), ('party_vat', 'ilike', term)]
        if to_int(template_id):
            domain.append(('template_id', '=', to_int(template_id)))
        return domain

    def _paged(self, domain, state, page, per_page):
        Contract = request.env['hlv.contract']
        counts = {'all': Contract.search_count(domain)}
        for key, _label in STATES:
            counts[key] = Contract.search_count(domain + [('state', '=', key)])
        if state in counts and state != 'all':
            domain = domain + [('state', '=', state)]
        total = Contract.search_count(domain)
        page = max(1, to_int(page) or 1)
        records = Contract.search(domain, offset=(page - 1) * per_page, limit=per_page)
        return records, {'counts': counts, 'page': page, 'pages': max(1, -(-total // per_page)), 'total': total}

    @http.route(f'{API}/list', type='json', auth='user', methods=['POST'])
    def api_list(self, search='', state='all', page=1, **kw):
        self._check()
        contracts, meta = self._paged(self._base_domain(search), state, page, PER_PAGE)
        return dict(meta, contracts=[payload.contract_summary(c) for c in contracts])

    @http.route(f'{API}/grid', type='json', auth='user', methods=['POST'])
    def api_grid(self, template_id=None, search='', state='all', page=1, **kw):
        """Bảng dữ liệu một mẫu: cột là biến của mẫu, mỗi hợp đồng một dòng — như sheet Excel cũ."""
        self._check()
        template = self._get_record('hlv.contract.template', template_id)
        contracts, meta = self._paged(self._base_domain(search, template.id), state, page, GRID_PER_PAGE)
        manager = self._is_manager()
        return dict(meta, template=payload.template_summary(template),
                    rows=[payload.grid_row(c, manager) for c in contracts])

    @http.route(f'{API}/get', type='json', auth='user', methods=['POST'])
    def api_get(self, contract_id=None, **kw):
        self._check()
        return payload.contract_detail(self._get_record('hlv.contract', contract_id), self._is_manager())

    def _form_vals(self, contract, params):
        """Giá trị ghi từ ngăn soạn (dùng chung cho Lưu và Xem trước). Khoá nào không gửi thì giữ nguyên.
        params: template_id, contract_date, partner_id, vat_rate, note, values, lines, name, overrides."""
        template = request.env['hlv.contract.template'].browse(
            to_int(params.get('template_id')) or (contract.template_id.id if contract else 0)).exists()
        if not template:
            raise UserError('Chọn mẫu hợp đồng.')
        vals = {'template_id': template.id}
        if params.get('contract_date') is not None:
            vals['contract_date'] = params['contract_date'] or fields.Date.context_today(request.env.user)
        if params.get('partner_id') is not None:
            vals['partner_id'] = to_int(params['partner_id']) or False
        if params.get('vat_rate') is not None:
            vals['vat_rate'] = float(params['vat_rate'] or 0)
        if params.get('note') is not None:
            vals['note'] = params['note']
        # Số hợp đồng người dùng sửa tay (để trống = giữ số đang có)
        if (params.get('name') or '').strip() and (not contract or params['name'].strip() != contract.name):
            vals['name'] = params['name'].strip()
        if params.get('overrides') is not None:
            vals['overrides'] = {k: str(v).strip() for k, v in params['overrides'].items() if str(v or '').strip()}
        if params.get('values') is not None:
            existing = dict(contract.variable_values or {}) if contract else {}
            vals['variable_values'] = dict(existing, **_clean_values(_var_names(contract, template), params['values']))
        if params.get('lines') is not None:
            rate = vals['vat_rate'] if 'vat_rate' in vals else (
                contract.vat_rate if contract else request.env.company.contract_vat_rate)
            vals['line_ids'] = _line_commands(params['lines'], rate)
        return template, vals

    @http.route(f'{API}/save', type='json', auth='user', methods=['POST'])
    def api_save(self, contract_id=None, **params):
        """Tạo mới (không có contract_id) hoặc ghi lại hợp đồng; trả chi tiết sau khi lưu."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id) if to_int(contract_id) else None
        template, vals = self._form_vals(contract, params)
        if contract:
            if contract.template_id == template:
                vals.pop('template_id')
            contract.write(vals)
        else:
            contract = request.env['hlv.contract'].create(vals)
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{API}/set_value', type='json', auth='user', methods=['POST'])
    def api_set_value(self, contract_id=None, name='', value='', **kw):
        """Sửa một ô trong bảng dữ liệu. name='contract_date' là ngày ký, còn lại là biến của mẫu."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        if name == 'contract_date':
            contract.write({'contract_date': value or fields.Date.context_today(request.env.user)})
        else:
            contract.set_variable(name, value.strip() if isinstance(value, str) else value)
        return payload.grid_row(contract, self._is_manager())

    @http.route(f'{API}/set_partner', type='json', auth='user', methods=['POST'])
    def api_set_partner(self, contract_id=None, partner_id=None, **kw):
        """Chọn khách ở ô tên/MST bên mua của bảng dữ liệu: điền cả cụm thông tin bên mua."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        contract.apply_partner(self._get_record('res.partner', partner_id))
        return payload.grid_row(contract, self._is_manager())

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
        lines = lines or []
        prices = [line_prices(l, vat_rate) for l in lines]
        subtotals = [line_subtotal(l.get('quantity'), p[0]) for l, p in zip(lines, prices)]
        return dict(compute_totals(subtotals, vat_rate), subtotals=subtotals,
                    prices_excl=[p[0] for p in prices], prices_incl=[p[1] for p in prices],
                    subtotals_incl=[line_subtotal(l.get('quantity'), p[1]) for l, p in zip(lines, prices)])

    @http.route(f'{API}/preview', type='json', auth='user', methods=['POST'])
    def api_preview(self, contract_id=None, marks=False, **kw):
        """Hợp đồng đã lưu dạng HTML. marks=True: đánh dấu chỗ từng biến (khung xem trước của
        bảng dữ liệu); False: đúng như bản in (hộp Xem nhanh)."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        html = contract._preview_html() if marks else contract._render_html_fragment()
        return {'name': contract.name, 'html': html}

    @http.route(f'{API}/preview_draft', type='json', auth='user', methods=['POST'])
    def api_preview_draft(self, contract_id=None, **params):
        """Xem trước nội dung đang gõ trên ngăn soạn, chưa lưu gì: dựng hợp đồng tạm trong bộ
        nhớ (new) từ đúng các giá trị sẽ lưu."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id) if to_int(contract_id) else None
        _template, vals = self._form_vals(contract, dict(params, note=None))
        manual_number = 'name' in vals
        vals.setdefault('vat_rate', contract.vat_rate if contract else request.env.company.contract_vat_rate)
        vals.setdefault('contract_date', contract.contract_date if contract else fields.Date.context_today(request.env.user))
        vals.setdefault('name', contract.name if contract else '/')
        vals['company_id'] = (contract.company_id if contract else request.env.company).id
        if contract and contract.template_id == _template:
            # Giữ nguyên mẫu: xem trước theo bản chụp riêng (có thể đã sửa chữ), không theo mẫu hiện tại
            vals.update({
                'doc_file': contract.with_context(bin_size=False).doc_file,
                'doc_variables': contract.doc_variables,
                'doc_has_lines': contract.doc_has_lines,
            })
        draft = request.env['hlv.contract'].new(vals)
        number = None if manual_number else draft._preview_number(contract)
        if number:
            draft.name = number
        return {'html': draft._preview_html(), 'number': number}

    @http.route(f'{API}/number_preview', type='json', auth='user', methods=['POST'])
    def api_number_preview(self, contract_id=None, template_id=None, partner_id=None, **kw):
        """Số hợp đồng dự kiến theo mẫu + khách đang chọn (chưa lấy số), để hiện trong ô Số hợp đồng.
        Trả {'number': None} khi lưu không làm đổi số đang có."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id) if to_int(contract_id) else None
        template = request.env['hlv.contract.template'].browse(to_int(template_id)).exists()
        if not template:
            return {'number': None}
        draft = request.env['hlv.contract'].new({
            'template_id': template.id,
            'partner_id': to_int(partner_id) or False,
            'company_id': (contract.company_id if contract else request.env.company).id,
        })
        return {'number': draft._preview_number(contract)}

    @http.route(f'{API}/body', type='json', auth='user', methods=['POST'])
    def api_body(self, contract_id=None, **kw):
        """Nội dung riêng của hợp đồng để sửa chữ (biến hiện dạng {{Ten_Bien}})."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        return {
            'name': contract.name,
            'html': contract.body_html_for_edit(),
            'variables': contract._doc_variables(),
            'doc_custom': contract.doc_custom,
        }

    @http.route(f'{API}/body/save', type='json', auth='user', methods=['POST'])
    def api_body_save(self, contract_id=None, body_html='', variables=None, **kw):
        """Lưu chữ sửa trên riêng hợp đồng này; mẫu gốc không đổi."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        contract.save_custom_body(body_html or '', variables)
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{API}/apply_template', type='json', auth='user', methods=['POST'])
    def api_apply_template(self, contract_id=None, **kw):
        """Hợp đồng nháp lấy lại nội dung theo mẫu hiện tại (bỏ chữ đã sửa riêng nếu có)."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        contract.action_apply_template()
        return payload.contract_detail(contract, self._is_manager())

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
        label = {'pdf': 'PDF', 'docx': 'Word', 'xlsx': 'Excel'}[fmt]
        for contract in contracts:
            contract._log('export', 'Xuất %s%s' % (label, '' if len(contracts) == 1 else ' (cùng %d hợp đồng)' % len(contracts)))
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(filename)),
        ])
