# -*- coding: utf-8 -*-
import json
import logging
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ─── Base URLs ────────────────────────────────────────────────────────────────
BASE_URLS = {
    'sandbox':    'https://testapi.meinvoice.vn/api2',
    'production': 'https://api.meinvoice.vn/api2',
}

# ─── API paths (Inbot – hóa đơn đầu ra) ──────────────────────────────────────
PATH = {
    'validate_user':     '/validateUser',           # Bước 1: lấy SecureToken
    'get_jwt':           '/getjwttoken',             # Bước 2: lấy JWTToken
    'get_subscribers':   '/getsubscribers',          # Lấy danh sách subscriber
    'get_organizations': '/getorganizations',        # Lấy organizations
    'get_invoices':      '/getinvoices',             # Lấy danh sách hóa đơn đầu ra
    'mark_accounting':   '/markaccounting',          # Đánh dấu hạch toán 1 HĐ
    'mark_accounting_multi': '/markaccountings',     # Đánh dấu hạch toán nhiều HĐ
}


class MeinvoiceOutputAPI(models.AbstractModel):
    """
    Service layer – toàn bộ logic gọi REST API meInvoice Inbot (hóa đơn đầu ra).

    Luồng xác thực (tài liệu misa.vn/154997):
        1. POST /validateUser   → nhận SecureToken
        2. POST /getjwttoken    → nhận JWTToken  (dùng cho mọi API sau)
    """
    _name = 'meinvoice.output.api'
    _description = 'MEinvoice Output Invoice API Service'

    # ─── Config helpers ───────────────────────────────────────────────────────

    def _get_base_url(self):
        env_mode = self.env['ir.config_parameter'].sudo().get_param(
            'meinvoice_output.environment', 'sandbox'
        )
        return BASE_URLS.get(env_mode, BASE_URLS['sandbox'])

    def _get_credentials(self):
        p = self.env['ir.config_parameter'].sudo()
        return {
            'client_id': p.get_param('meinvoice_output.client_id', ''),
            'app_id':    p.get_param('meinvoice_output.app_id', ''),
            'username':  p.get_param('meinvoice_output.username', ''),
            'password':  p.get_param('meinvoice_output.password', ''),
            'tax_code':  p.get_param('meinvoice_output.tax_code', ''),
        }

    # ─── Token management ─────────────────────────────────────────────────────

    def _get_jwt_token(self):
        """Lấy JWTToken từ cache; refresh nếu hết hạn."""
        p = self.env['ir.config_parameter'].sudo()
        token = p.get_param('meinvoice_output.jwt_token', '')
        expiry_str = p.get_param('meinvoice_output.jwt_expiry', '')

        if token and expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if datetime.now() < expiry - timedelta(minutes=5):
                    return token
            except Exception:
                pass

        return self._refresh_jwt_token()

    def _refresh_jwt_token(self):
        creds = self._get_credentials()
        missing = [k for k, v in creds.items() if not v]
        if missing:
            raise UserError(_(
                'Vui lòng cấu hình đầy đủ thông tin meInvoice trong Cài đặt.\n'
                'Thiếu: %s'
            ) % ', '.join(missing))

        base = self._get_base_url()

        # ── Bước 1: lấy SecureToken ──────────────────────────────────────────
        try:
            r1 = requests.post(
                base + PATH['validate_user'],
                json={
                    'ClientID': creds['client_id'],
                    'AppID':    creds['app_id'],
                    'Username': creds['username'],
                    'Password': creds['password'],
                },
                timeout=30,
            )
            r1.raise_for_status()
            d1 = r1.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối meInvoice (validateUser): %s') % e)

        if d1.get('Status') != 200:
            raise UserError(
                _('Lấy SecureToken thất bại: %s') % (d1.get('Message') or d1)
            )
        secure_token = d1.get('Payload') or d1.get('Token') or d1.get('Data', {}).get('Token', '')
        if not secure_token:
            raise UserError(_('meInvoice không trả về SecureToken. Response: %s') % d1)

        # ── Bước 2: đổi SecureToken → JWTToken ──────────────────────────────
        try:
            r2 = requests.post(
                base + PATH['get_jwt'],
                json={
                    'ClientID':    creds['client_id'],
                    'AppID':       creds['app_id'],
                    'SecureToken': secure_token,
                },
                timeout=30,
            )
            r2.raise_for_status()
            d2 = r2.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối meInvoice (getjwttoken): %s') % e)

        if d2.get('Status') != 200:
            raise UserError(
                _('Lấy JWTToken thất bại: %s') % (d2.get('Message') or d2)
            )
        jwt = d2.get('Payload') or d2.get('Token') or d2.get('Data', {}).get('Token', '')
        if not jwt:
            raise UserError(_('meInvoice không trả về JWTToken. Response: %s') % d2)

        # Cache – JWT thường có hạn 2 giờ, lưu 115 phút
        expiry = datetime.now() + timedelta(minutes=115)
        p = self.env['ir.config_parameter'].sudo()
        p.set_param('meinvoice_output.jwt_token',  jwt)
        p.set_param('meinvoice_output.jwt_expiry', expiry.isoformat())
        _logger.info('meInvoice JWT refreshed, expires %s', expiry)
        return jwt

    # ─── HTTP helpers ─────────────────────────────────────────────────────────

    def _headers(self):
        creds = self._get_credentials()
        return {
            'Content-Type':   'application/json',
            'Authorization':  'Bearer ' + self._get_jwt_token(),
            'CompanyTaxCode': creds['tax_code'],
        }

    def _post(self, path, payload):
        url = self._get_base_url() + path
        _logger.debug('meInvoice POST %s payload=%s', url, payload)
        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối meInvoice: %s') % e)

    def _get(self, path, params=None):
        url = self._get_base_url() + path
        _logger.debug('meInvoice GET %s params=%s', url, params)
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối meInvoice: %s') % e)

    @staticmethod
    def _check(result, label=''):
        """Kiểm tra Status==200 và raise nếu không."""
        if result.get('Status') != 200:
            raise UserError(
                _('%s thất bại: %s') % (label, result.get('Message') or result)
            )
        return result.get('Payload') or result.get('Data') or result

    # ─── Public API ───────────────────────────────────────────────────────────

    def api_get_subscribers(self):
        """Lấy danh sách subscriber (organization gốc)."""
        result = self._post(PATH['get_subscribers'], {})
        return self._check(result, 'Lấy subscribers')

    def api_get_organizations(self, subscriber_id=''):
        """Lấy danh sách organizations (chi nhánh / MST)."""
        payload = {}
        if subscriber_id:
            payload['SubscriberID'] = subscriber_id
        result = self._post(PATH['get_organizations'], payload)
        return self._check(result, 'Lấy organizations')

    def api_get_invoices(self, from_date, to_date,
                         organization_id='',
                         accounting_status=None,
                         page_index=1, page_size=50):
        """
        Lấy danh sách hóa đơn đầu ra đã phát hành.

        accounting_status:
            None    = tất cả
            0       = chưa hạch toán
            1       = đã hạch toán

        Trả về list hóa đơn.
        """
        payload = {
            'FromDate':       from_date,   # 'YYYY-MM-DD'
            'ToDate':         to_date,
            'PageIndex':      page_index,
            'PageSize':       page_size,
            'InvoiceType':    1,           # 1 = hóa đơn đầu ra (xuất bán)
        }
        if organization_id:
            payload['OrganizationID'] = organization_id
        if accounting_status is not None:
            payload['AccountingStatus'] = accounting_status

        result = self._post(PATH['get_invoices'], payload)
        data = self._check(result, 'Lấy danh sách hóa đơn')

        # Normalize: API có thể trả về list hoặc {Data: [...], Total: N}
        if isinstance(data, list):
            return data, len(data)
        if isinstance(data, dict):
            items = data.get('Data') or data.get('Invoices') or []
            total = data.get('Total') or data.get('TotalRecord') or len(items)
            return items, total
        return [], 0

    def api_mark_accounting(self, invoice_ids):
        """
        Đánh dấu hạch toán cho nhiều hóa đơn.
        invoice_ids: list[str] – danh sách InvoiceID từ meInvoice.
        """
        # API đánh dấu hạch toán nhiều HĐ
        payload = {'InvoiceID': invoice_ids}
        result = self._post(PATH['mark_accounting_multi'], payload)
        return self._check(result, 'Đánh dấu hạch toán')

    def api_test_connection(self):
        """Test kết nối – refresh JWT."""
        try:
            self._refresh_jwt_token()
            return True, _('Kết nối thành công!')
        except Exception as e:
            return False, str(e)
