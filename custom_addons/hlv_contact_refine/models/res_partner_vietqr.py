# -*- coding: utf-8 -*-
import logging
import re
from urllib.parse import quote

import requests

from odoo import _, api, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

VIETQR_BUSINESS_API_URL = "https://api.vietqr.io/v2/business"
VIETNAM_TAX_CODE_PATTERN = re.compile(r"^\d{10}(?:-\d{3})?$")


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def hlv_vietqr_lookup_business(self, tax_code):
        tax_code = self._hlv_vietqr_normalize_tax_code(tax_code)
        existing = self._hlv_vietqr_find_existing_partner(tax_code)
        if existing:
            active_note = '' if existing.active else _(' (đang lưu trữ)')
            raise UserError(_(
                'MST %(tax_code)s đã tồn tại trên liên hệ "%(partner)s"%(active_note)s.'
            ) % {
                'tax_code': tax_code,
                'partner': existing.display_name,
                'active_note': active_note,
            })

        payload = self._hlv_vietqr_fetch_business(tax_code)
        data = payload['data']
        metadata = payload.get('metadata') or {}
        country = self.env.ref('base.vn', raise_if_not_found=False)

        return {
            'name': str(data.get('name') or '').strip(),
            'vat': str(data.get('id') or tax_code).strip(),
            'street': str(data.get('address') or '').strip(),
            'status': str(data.get('status') or '').strip(),
            'updated_at': str(metadata.get('updatedAt') or '').strip(),
            'country_id': country.id if country else False,
            'country_name': country.display_name if country else '',
        }

    @api.model
    def _hlv_vietqr_normalize_tax_code(self, tax_code):
        tax_code = re.sub(r'\s+', '', str(tax_code or '').strip().upper())
        if tax_code.startswith('VN'):
            tax_code = tax_code[2:]
        if not VIETNAM_TAX_CODE_PATTERN.fullmatch(tax_code):
            raise UserError(_(
                'Mã số thuế không hợp lệ. Vui lòng nhập 10 số hoặc mã chi nhánh '
                'theo dạng 10 số-3 số.'
            ))
        return tax_code

    @api.model
    def _hlv_vietqr_find_existing_partner(self, tax_code):
        Partner = self.sudo().with_context(active_test=False)
        candidates = Partner.search([
            '|',
            ('vat', '=ilike', tax_code),
            ('vat', '=ilike', 'VN%s' % tax_code),
        ])
        return candidates.filtered(
            lambda partner: re.sub(
                r'\s+', '', (partner.vat or '').strip().upper()
            ).removeprefix('VN') == tax_code
        )[:1]

    @api.model
    def _hlv_vietqr_fetch_business(self, tax_code):
        url = '%s/%s' % (VIETQR_BUSINESS_API_URL, quote(tax_code, safe=''))
        try:
            response = requests.get(
                url,
                headers={'Accept': 'application/json'},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise UserError(_(
                'VietQR phản hồi quá chậm. Vui lòng thử lại sau.'
            )) from exc
        except (requests.RequestException, ValueError) as exc:
            _logger.exception(
                'Không lấy được thông tin doanh nghiệp VietQR cho MST %s',
                tax_code,
            )
            raise UserError(_(
                'Không kết nối hoặc không đọc được dữ liệu từ VietQR: %s'
            ) % exc) from exc

        data = payload.get('data') if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get('code') != '00'
            or not isinstance(data, dict)
        ):
            message = payload.get('desc') if isinstance(payload, dict) else False
            raise UserError(_(
                'VietQR không tìm thấy thông tin cho MST '
                '%(tax_code)s: %(message)s'
            ) % {
                'tax_code': tax_code,
                'message': message or _('Không rõ lỗi'),
            })

        if not str(data.get('name') or '').strip():
            raise UserError(_(
                'VietQR có trả dữ liệu nhưng thiếu tên doanh nghiệp cho MST %s.'
            ) % tax_code)
        return payload
