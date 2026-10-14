# -*- coding: utf-8 -*-
"""Trang /hop-dong — các ô tìm: khách hàng, sản phẩm, đơn bán (lấy dòng hàng sang hợp đồng).

Chọn là để điền nhanh; mọi ô sau khi điền vẫn sửa tay được.
"""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..utils.contract_vars import price_incl
from .common import API, ContractPageMixin, to_int

LIMIT = 15


def _price_excl(product, company):
    """Giá bán chưa VAT của sản phẩm: bảng giá Odoo có thể khai giá đã gồm thuế, nên tính qua
    thuế bán của sản phẩm thay vì lấy thẳng lst_price. Không có thuế -> lst_price."""
    taxes = product.taxes_id.filtered(lambda tax: tax.company_id == company)
    if not taxes:
        return product.lst_price
    return taxes.compute_all(product.lst_price, product=product)['total_excluded']


class ContractLookup(ContractPageMixin, http.Controller):

    @http.route(f'{API}/partners', type='json', auth='user', methods=['POST'])
    def api_partners(self, search='', **kw):
        self._check()
        term = (search or '').strip()
        domain = ['|', '|', ('name', 'ilike', term), ('vat', 'ilike', term), ('ref', 'ilike', term)] if term else []
        Contract = request.env['hlv.contract']
        return [{
            'id': partner.id,
            'label': partner.display_name,
            'vat': partner.commercial_partner_id.vat or '',
            'values': Contract._buyer_values_from_partner(partner),
        } for partner in request.env['res.partner'].search(domain, limit=LIMIT)]

    @http.route(f'{API}/products', type='json', auth='user', methods=['POST'])
    def api_products(self, search='', vat_rate=0, **kw):
        """Sản phẩm khớp mã/tên; giá trả cả chưa VAT và sau VAT theo thuế suất của hợp đồng."""
        self._check()
        term = (search or '').strip()
        if not term:
            return []
        company = request.env.company
        products = request.env['product.product'].search(
            ['|', ('default_code', 'ilike', term), ('name', 'ilike', term), ('sale_ok', '=', True)], limit=LIMIT)
        return [{
            'id': product.id,
            'label': product.display_name,
            'name': product.name,
            'code': product.default_code or '',
            'uom': product.uom_id.name or '',
            'price_excl': _price_excl(product, company),
            'price_incl': price_incl(_price_excl(product, company), vat_rate),
        } for product in products]

    @http.route(f'{API}/sale_orders', type='json', auth='user', methods=['POST'])
    def api_sale_orders(self, search='', **kw):
        self._check()
        term = (search or '').strip()
        domain = [('state', '!=', 'cancel')]
        if term:
            domain += ['|', ('name', 'ilike', term), ('partner_id', 'ilike', term)]
        orders = request.env['sale.order'].search(domain, limit=LIMIT, order='date_order desc')
        return [{
            'id': order.id,
            'label': order.name,
            'partner': order.partner_id.display_name or '',
            'amount_total': order.amount_total,
        } for order in orders]

    @http.route(f'{API}/sale_order_lines', type='json', auth='user', methods=['POST'])
    def api_sale_order_lines(self, order_id=None, vat_rate=0, **kw):
        """Dòng hàng của đơn bán để đưa sang hợp đồng. Đơn giá chưa VAT = thành tiền chưa thuế /
        số lượng (đã trừ chiết khấu dòng), không lấy price_unit vì có thể đã gồm thuế."""
        self._check()
        order = self._get_record('sale.order', order_id)
        lines = []
        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty):
            lines.append({
                'product_id': line.product_id.id or False,
                'product_name': (line.name or line.product_id.display_name or '').split('\n')[0].strip(),
                'uom': line.product_uom.name or '',
                'quantity': line.product_uom_qty,
                'price_excl': line.price_subtotal / line.product_uom_qty,
                'price_incl': price_incl(line.price_subtotal / line.product_uom_qty, vat_rate),
            })
        return {
            'lines': lines,
            'partner_id': order.partner_id.id,
            'partner_label': order.partner_id.display_name,
            'partner_values': request.env['hlv.contract']._buyer_values_from_partner(order.partner_id),
        }

    # ------------------------------------------------------------ báo giá MISA CRM (BG…)

    def _misa(self):
        """Bộ đọc MISA CRM của module misa_fetch_po_button (không bắt buộc cài)."""
        misa = request.env.get('misa.api.utils')
        if misa is None or not hasattr(misa, 'crm_search_quotes'):
            raise UserError('Chưa cài / chưa nâng cấp module kết nối MISA CRM (misa_fetch_po_button).')
        return misa.sudo()

    @http.route(f'{API}/crm_quotes', type='json', auth='user', methods=['POST'])
    def api_crm_quotes(self, search='', **kw):
        """Báo giá trên MISA CRM theo số (BG…) hoặc tên khách."""
        self._check()
        return self._misa().crm_search_quotes(search)

    @http.route(f'{API}/crm_quote_lines', type='json', auth='user', methods=['POST'])
    def api_crm_quote_lines(self, quote_id=None, account_id=None, account_name='', vat_rate=0, **kw):
        """Hàng + khách của một báo giá CRM để đưa vào hợp đồng. Đơn giá lấy đúng giá chưa VAT trên
        báo giá (đã trừ chiết khấu); VAT đề xuất = thuế suất chung của các dòng (khác nhau thì không đề xuất).
        Khách: tìm trong Odoo theo mã khách CRM / MST — không tạo khách mới."""
        self._check()
        misa = self._misa()
        rows = misa.crm_quote_products(to_int(quote_id))
        rates = {row['tax_percent'] for row in rows if row['tax_percent'] is not None}
        rate = rates.pop() if len(rates) == 1 else float(vat_rate or 0)
        Product = request.env['product.product']
        lines = [{
            'product_id': Product.search([('default_code', '=', row['code'])], limit=1).id or False,
            'product_name': row['name'],
            'uom': row['unit'],
            'quantity': row['qty'],
            'price_basis': 'excl',
            'price_excl': row['price'],
            'price_incl': price_incl(row['price'], rate),
        } for row in rows]
        codes = misa.crm_account_codes(to_int(account_id)) if to_int(account_id) else {}
        partner = self._find_crm_partner(codes)
        result = {'lines': lines, 'vat_rate': rate, 'partner_id': partner.id or False,
                  'partner_label': partner.display_name or ''}
        if partner:
            result['partner_values'] = request.env['hlv.contract']._buyer_values_from_partner(partner)
        else:
            result['partner_values'] = {'Ten_Ben_Mua': account_name or '', 'Ma_So_Thue_Ben_Mua': codes.get('taxcode') or ''}
        return result

    def _find_crm_partner(self, codes):
        """Khách Odoo ứng với khách CRM: mã khách CRM nằm ở Mã đăng ký công ty / Mã tham chiếu (do đồng
        bộ MISA ghi), không thấy thì theo MST. Không thấy gì -> recordset rỗng."""
        Partner = request.env['res.partner']
        number, tax = codes.get('account_number'), codes.get('taxcode')
        if number:
            partner = Partner.search(['|', ('company_registry', '=', number), ('ref', '=', number)], limit=1)
            if partner:
                return partner.commercial_partner_id
        if tax:
            return Partner.search([('vat', '=', tax), ('is_company', '=', True)], limit=1)
        return Partner
