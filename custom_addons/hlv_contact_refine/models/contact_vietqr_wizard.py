# -*- coding: utf-8 -*-
import logging
import re
from urllib.parse import quote

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

VIETQR_BUSINESS_API_URL = "https://api.vietqr.io/v2/business"
VIETNAM_TAX_CODE_PATTERN = re.compile(r"^\d{10}(?:-\d{3})?$")


class HlvContactVietqrWizard(models.TransientModel):
    _name = 'hlv.contact.vietqr.wizard'
    _description = 'Tạo liên hệ từ mã số thuế VietQR'

    tax_code = fields.Char(
        string='Mã số thuế',
        required=True,
        help='Nhập mã số thuế 10 số hoặc mã chi nhánh dạng 10 số-3 số.',
    )

    def _normalize_tax_code(self):
        self.ensure_one()
        tax_code = re.sub(r'\s+', '', (self.tax_code or '').strip().upper())
        if tax_code.startswith('VN'):
            tax_code = tax_code[2:]
        if not VIETNAM_TAX_CODE_PATTERN.fullmatch(tax_code):
            raise UserError(_(
                'Mã số thuế không hợp lệ. Vui lòng nhập 10 số hoặc mã chi nhánh '
                'theo dạng 10 số-3 số.'
            ))
        return tax_code

    def _find_existing_partner(self, tax_code):
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
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

    def _fetch_vietqr_business(self, tax_code):
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
        if not isinstance(payload, dict) or payload.get('code') != '00' or not isinstance(data, dict):
            message = payload.get('desc') if isinstance(payload, dict) else False
            raise UserError(_(
                'VietQR không tìm thấy thông tin cho MST %(tax_code)s: %(message)s'
            ) % {
                'tax_code': tax_code,
                'message': message or _('Không rõ lỗi'),
            })

        name = str(data.get('name') or '').strip()
        if not name:
            raise UserError(_(
                'VietQR có trả dữ liệu nhưng thiếu tên doanh nghiệp cho MST %s.'
            ) % tax_code)
        return payload

    def action_fetch_and_create(self):
        self.ensure_one()
        tax_code = self._normalize_tax_code()
        existing = self._find_existing_partner(tax_code)
        if existing:
            active_note = '' if existing.active else _(' (đang lưu trữ)')
            raise UserError(_(
                'MST %(tax_code)s đã tồn tại trên liên hệ "%(partner)s"%(active_note)s.'
            ) % {
                'tax_code': tax_code,
                'partner': existing.display_name,
                'active_note': active_note,
            })

        payload = self._fetch_vietqr_business(tax_code)
        data = payload['data']
        metadata = payload.get('metadata') or {}
        api_tax_code = str(data.get('id') or tax_code).strip()
        status = str(data.get('status') or '').strip()
        updated_at = str(metadata.get('updatedAt') or '').strip()

        note_lines = [_('Liên hệ được tạo từ dữ liệu tra cứu VietQR.')]
        if status:
            note_lines.append(_('Tình trạng MST: %s') % status)
        if updated_at:
            note_lines.append(_('Dữ liệu nguồn cập nhật lúc: %s') % updated_at)
        if metadata.get('disclaimer'):
            note_lines.append(str(metadata['disclaimer']).strip())

        country = self.env.ref('base.vn', raise_if_not_found=False)
        partner = self.env['res.partner'].create({
            'name': str(data['name']).strip(),
            'is_company': True,
            'vat': api_tax_code,
            'street': str(data.get('address') or '').strip() or False,
            'country_id': country.id if country else False,
            'comment': '\n'.join(note_lines),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Liên hệ'),
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }
