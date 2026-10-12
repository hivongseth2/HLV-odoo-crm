# -*- coding: utf-8 -*-
"""Trang /hop-dong — các ô tìm: khách hàng, sản phẩm, đơn bán (lấy dòng hàng sang hợp đồng).

Chọn là để điền nhanh; mọi ô sau khi điền vẫn sửa tay được.
"""

from odoo import http
from odoo.http import request

from ..utils.contract_vars import price_incl
from .common import API, ContractPageMixin

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
                'price_incl': price_incl(line.price_subtotal / line.product_uom_qty, vat_rate),
            })
        return {
            'lines': lines,
            'partner_id': order.partner_id.id,
            'partner_label': order.partner_id.display_name,
            'partner_values': request.env['hlv.contract']._buyer_values_from_partner(order.partner_id),
        }
