# -*- coding: utf-8 -*-
"""Văn bản gốc cho phụ lục / đề nghị thanh toán: tìm văn bản để căn cứ vào, và giá trị điền sẵn khi
lập văn bản con từ một văn bản (nút "+ Phụ lục", "+ Đề nghị thanh toán" trên ngăn soạn).

Văn bản gốc có thể do nhân viên khác phụ trách (hợp đồng nguyên tắc của khách lập từ trước): tìm
bằng sudo nhưng chỉ trả số, khách, ngày, giá trị — không mở nội dung.
"""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.contract_template import PARENT_TYPES
from .common import API, ContractPageMixin, to_int

PARENT_LIMIT = 20


class ContractLinkApi(ContractPageMixin, http.Controller):

    @http.route(f'{API}/parents', type='json', auth='user', methods=['POST'])
    def api_parents(self, contract_type='', search='', partner_id=None, **kw):
        """Văn bản gốc chọn được cho loại contract_type, ưu tiên cùng khách. Loại không có văn bản gốc -> []."""
        self._check()
        allowed = PARENT_TYPES.get(contract_type)
        if not allowed:
            return []
        domain = [('contract_type', 'in', list(allowed)), ('state', '!=', 'cancel'),
                  ('company_id', 'in', request.env.companies.ids)]
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('party_name', 'ilike', term)]
        partner = request.env['res.partner'].browse(to_int(partner_id)).exists()
        if partner and not term:
            domain.append(('partner_id', 'child_of', partner.commercial_partner_id.id))
        records = request.env['hlv.contract'].sudo().search(domain, limit=PARENT_LIMIT)
        return [rec._link_info_brief() for rec in records]

    @http.route(f'{API}/child_defaults', type='json', auth='user', methods=['POST'])
    def api_child_defaults(self, parent_id=None, child_type='', **kw):
        """Giá trị điền sẵn cho văn bản child_type mới căn cứ vào parent_id, kèm mẫu gợi ý (mẫu đang
        dùng đầu tiên của loại đó)."""
        self._check()
        parent = request.env['hlv.contract'].sudo().browse(to_int(parent_id)).exists()
        if not parent or parent.contract_type not in PARENT_TYPES.get(child_type, ()):
            raise UserError('Văn bản này không dùng làm căn cứ cho loại đã chọn được.')
        template = request.env['hlv.contract.template'].search([('contract_type', '=', child_type)], limit=1)
        return dict(parent._child_defaults(child_type), template_id=template.id or False)
