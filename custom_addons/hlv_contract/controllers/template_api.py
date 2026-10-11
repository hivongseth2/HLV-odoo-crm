# -*- coding: utf-8 -*-
"""Trang /hop-dong — phần mẫu hợp đồng (soạn, import .doc/.docx, tải file) và thông tin bên
bán. Thao tác ghi chỉ dành cho nhóm Quản lý; nhân viên chỉ cần danh sách mẫu (trong config).
"""

import base64
import binascii

from odoo import http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request

from ..services import contract_payload as payload
from ..services.contract_export import FORMATS, safe_filename
from ..services.template_import import template_vals_from_upload
from .common import API, PAGE_ROUTE, ContractPageMixin, to_int

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ContractTemplatePage(ContractPageMixin, http.Controller):

    @http.route(f'{API}/templates', type='json', auth='user', methods=['POST'])
    def api_templates(self, **kw):
        self._check_manager()
        Template = request.env['hlv.contract.template'].with_context(active_test=False)
        return [payload.template_summary(t) for t in Template.search([], order='active desc, contract_type, name')]

    @http.route(f'{API}/template', type='json', auth='user', methods=['POST'])
    def api_template(self, template_id=None, **kw):
        self._check_manager()
        return payload.template_detail(self._get_record('hlv.contract.template', template_id))

    @http.route(f'{API}/template/save', type='json', auth='user', methods=['POST'])
    def api_template_save(self, template_id=None, name='', contract_type='sale', body_html=None,
                          note='', active=True, **kw):
        """Lưu thông tin mẫu; body_html chỉ gửi khi soạn trên trang. Không có template_id thì
        tạo mẫu soạn trên trang mới."""
        self._check_manager()
        vals = {'name': (name or '').strip() or 'Mẫu mới', 'contract_type': contract_type,
                'note': note or '', 'active': bool(active)}
        if body_html is not None:
            vals.update({'source': 'builder', 'body_html': body_html})
        if to_int(template_id):
            template = self._get_record('hlv.contract.template', template_id)
            template.write(vals)
        else:
            vals.setdefault('source', 'builder')
            template = request.env['hlv.contract.template'].create(vals)
        return payload.template_detail(template)

    @http.route(f'{API}/template/upload', type='json', auth='user', methods=['POST'])
    def api_template_upload(self, template_id=None, name='', contract_type='sale', filename='',
                            data='', keep_word_file=True, **kw):
        """Tải .docx/.doc lên: tạo mẫu mới, hoặc thay nội dung mẫu có sẵn (template_id)."""
        self._check_manager()
        try:
            raw = base64.b64decode(data or '', validate=True)
        except (binascii.Error, ValueError):
            raise UserError('Không đọc được file tải lên.')
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise UserError('File rỗng hoặc lớn hơn 10 MB.')
        vals = template_vals_from_upload(filename, raw, bool(keep_word_file))
        if to_int(template_id):
            template = self._get_record('hlv.contract.template', template_id)
            template.write(vals)
        else:
            vals.update({'name': (name or '').strip() or filename, 'contract_type': contract_type})
            template = request.env['hlv.contract.template'].create(vals)
        return payload.template_detail(template)

    @http.route(f'{API}/template/convert', type='json', auth='user', methods=['POST'])
    def api_template_convert(self, template_id=None, **kw):
        self._check_manager()
        template = self._get_record('hlv.contract.template', template_id)
        template.action_convert_to_builder()
        return payload.template_detail(template)

    @http.route(f'{PAGE_ROUTE}/mau/<int:template_id>/file', type='http', auth='user', methods=['GET'])
    def template_file(self, template_id, **kw):
        """Tải file Word của mẫu (mẫu soạn trên trang thì là file dựng ra từ nội dung)."""
        self._check()
        template = self._get_record('hlv.contract.template', template_id)
        filename = template.docx_filename or '%s.docx' % safe_filename(template.name)
        return request.make_response(template._docx_bytes(), headers=[
            ('Content-Type', FORMATS['docx']),
            ('Content-Disposition', content_disposition(filename)),
        ])

    @http.route(f'{API}/seller', type='json', auth='user', methods=['POST'])
    def api_seller(self, values=None, **kw):
        """Đọc (values=None) hoặc ghi thông tin bên bán của công ty đang chọn."""
        self._check_manager()
        company = request.env.company
        if values is not None:
            vals = {k: values[k] for k in payload.SELLER_FIELDS if k in values}
            if 'contract_vat_rate' in vals:
                vals['contract_vat_rate'] = float(vals['contract_vat_rate'] or 0)
            company.write(vals)
        return payload.seller_values(company)
