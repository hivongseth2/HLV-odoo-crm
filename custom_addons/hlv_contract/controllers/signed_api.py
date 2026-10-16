# -*- coding: utf-8 -*-
"""Bản scan đã ký của hợp đồng (models/contract_signed.py): tải lên, xem, xoá."""

import base64
import binascii

from odoo import http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request

from ..services import contract_payload as payload
from .common import API, PAGE_ROUTE, ContractPageMixin

# base64 của file 20 MB dài khoảng 27 MB; chặn sớm trước khi giải mã
_MAX_BASE64 = 28 * 1024 * 1024


class ContractSignedApi(ContractPageMixin, http.Controller):

    @http.route(f'{API}/signed/upload', type='json', auth='user', methods=['POST'])
    def api_signed_upload(self, contract_id=None, filename='', data='', **kw):
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        if len(data or '') > _MAX_BASE64:
            raise UserError('File lớn hơn 20 MB.')
        try:
            raw = base64.b64decode(data or '', validate=True)
        except (binascii.Error, ValueError):
            raise UserError('Không đọc được file tải lên.')
        contract.set_signed_file(filename, raw)
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{API}/signed/delete', type='json', auth='user', methods=['POST'])
    def api_signed_delete(self, contract_id=None, **kw):
        self._check_manager()
        contract = self._get_record('hlv.contract', contract_id)
        contract.clear_signed_file()
        return payload.contract_detail(contract, self._is_manager())

    @http.route(f'{PAGE_ROUTE}/ban-ky/<int:contract_id>', type='http', auth='user', methods=['GET'])
    def signed_file(self, contract_id, download=None, **kw):
        """Mở bản ký ngay trong trình duyệt (download=1 thì tải về)."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        content = contract._signed_bytes()
        if not content:
            raise request.not_found()
        return request.make_response(content, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', content_disposition(contract.signed_filename,
                                                        'attachment' if download else 'inline')),
        ])
