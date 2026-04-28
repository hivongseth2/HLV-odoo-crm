# -*- coding: utf-8 -*-
import json
import logging
import base64
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Endpoint constants
# ─────────────────────────────────────────────
MEINVOICE_ENDPOINTS = {
    'sandbox': 'https://testapi.meinvoice.vn/api/v3',
    'production': 'https://api.meinvoice.vn/api/v3',
}

API_PATHS = {
    'get_token':            '/itg/auth/token',
    'create_invoice':       '/itg/invoicepublishing/createinvoice',
    'publish_invoice':      '/itg/invoicepublishing/publish',
    # Phát hành nhanh (1 bước, dành cho máy tính tiền / không ký số)
    'publish_direct':       '/code/itg/invoice-calculating/invoiceandpublish',
    'cancel_invoice':       '/itg/invoicepublished/cancel',
    'adjust_invoice':       '/itg/invoicepublished/adjust',
    'search_invoice':       '/itg/invoicepublished/getinvoices',
    'download_invoice':     '/itg/invoicepublished/downloadinvoice',
    'view_invoice':         '/itg/invoicepublished/invoiceview',
}


class MeinvoiceAPI(models.AbstractModel):
    """
    Service layer – tất cả logic gọi REST API MEinvoice.
    Không lưu trạng thái (abstract model), được gọi từ account.move hoặc wizard.
    """
    _name = 'meinvoice.api'
    _description = 'MEinvoice API Service'

    # ─────────────────────────────────────────
    #  Token management
    # ─────────────────────────────────────────

    def _get_base_url(self):
        env = self.env['ir.config_parameter'].sudo()
        mode = env.get_param('meinvoice.environment', 'sandbox')
        return MEINVOICE_ENDPOINTS.get(mode, MEINVOICE_ENDPOINTS['sandbox'])

    def _get_token(self):
        """
        Lấy token từ cache (ir.config_parameter).
        Nếu hết hạn hoặc chưa có → gọi API lấy token mới.
        """
        params = self.env['ir.config_parameter'].sudo()
        token = params.get_param('meinvoice.access_token')
        token_expiry_str = params.get_param('meinvoice.token_expiry')

        if token and token_expiry_str:
            try:
                expiry = datetime.fromisoformat(token_expiry_str)
                if datetime.now() < expiry - timedelta(minutes=5):
                    return token
            except Exception:
                pass

        # Refresh token
        return self._refresh_token()

    def _refresh_token(self):
        params = self.env['ir.config_parameter'].sudo()
        app_id    = params.get_param('meinvoice.app_id')
        taxcode   = params.get_param('meinvoice.tax_code')
        username  = params.get_param('meinvoice.username')
        password  = params.get_param('meinvoice.password')

        if not all([app_id, taxcode, username, password]):
            raise UserError(_(
                'Vui lòng cấu hình đầy đủ thông tin MEinvoice trong '
                'Cài đặt → Kế toán → MEinvoice.'
            ))

        url = self._get_base_url() + API_PATHS['get_token']
        payload = {
            'appid':    app_id,
            'taxcode':  taxcode,
            'username': username,
            'password': password,
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise UserError(_('Không thể kết nối MEinvoice: %s') % str(e))

        if not data.get('Success'):
            raise UserError(_(
                'Lấy token thất bại: %s'
            ) % (data.get('ErrorCode') or data.get('Errors') or 'Unknown'))

        token = data['Data']
        # MEinvoice JWT thường có hạn 1 giờ – lưu 55 phút để an toàn
        expiry = datetime.now() + timedelta(minutes=55)
        params.set_param('meinvoice.access_token', token)
        params.set_param('meinvoice.token_expiry', expiry.isoformat())
        _logger.info('MEinvoice token refreshed, expires %s', expiry)
        return token

    # ─────────────────────────────────────────
    #  HTTP helpers
    # ─────────────────────────────────────────

    def _headers(self):
        params = self.env['ir.config_parameter'].sudo()
        taxcode = params.get_param('meinvoice.tax_code', '')
        return {
            'Content-Type':   'application/json',
            'Authorization':  'Bearer ' + self._get_token(),
            'CompanyTaxCode': taxcode,
        }

    def _post(self, path, payload, params=None):
        url = self._get_base_url() + path
        _logger.debug('MEinvoice POST %s payload=%s', url, payload)
        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                params=params,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối MEinvoice: %s') % str(e))

    def _get(self, path, params=None):
        url = self._get_base_url() + path
        _logger.debug('MEinvoice GET %s params=%s', url, params)
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise UserError(_('Lỗi kết nối MEinvoice: %s') % str(e))

    def _handle_response(self, result, action_label='Thao tác'):
        """Kiểm tra Success và raise UserError nếu thất bại."""
        if not result.get('Success'):
            err = result.get('ErrorCode') or result.get('Errors') or 'Unknown'
            raise UserError(_('%s thất bại: %s') % (action_label, err))
        return result.get('Data')

    # ─────────────────────────────────────────
    #  Public API methods
    # ─────────────────────────────────────────

    def api_publish_invoice(self, invoice_data):
        """
        Phát hành hóa đơn điện tử.
        invoice_data: dict chứa thông tin hóa đơn theo chuẩn MEinvoice.
        Trả về TransactionID (mã tra cứu).
        """
        # Sử dụng endpoint phát hành trực tiếp (không cần ký số riêng)
        result = self._post(API_PATHS['publish_direct'], [invoice_data])
        data = self._handle_response(result, 'Phát hành hóa đơn')
        if isinstance(data, list) and data:
            return data[0].get('TransactionID') or data[0]
        return data

    def api_cancel_invoice(self, transaction_ids, reason):
        """
        Hủy hóa đơn.
        transaction_ids: list[str] – danh sách mã tra cứu.
        reason: str – lý do hủy.
        """
        payload = [
            {'TransactionID': tid, 'Reason': reason}
            for tid in transaction_ids
        ]
        result = self._post(API_PATHS['cancel_invoice'], payload)
        return self._handle_response(result, 'Hủy hóa đơn')

    def api_adjust_invoice(self, org_transaction_id, adjust_type, invoice_data, reason):
        """
        Điều chỉnh hóa đơn.
        adjust_type: 1=Điều chỉnh tăng, 2=Điều chỉnh giảm, 3=Thay thế.
        """
        payload = {
            'OrgTransactionID': org_transaction_id,
            'AdjustType':       adjust_type,
            'Reason':           reason,
            'OrgInvoiceData':   invoice_data,
        }
        result = self._post(API_PATHS['adjust_invoice'], payload)
        return self._handle_response(result, 'Điều chỉnh hóa đơn')

    def api_search_invoice(self, transaction_id=None, inv_no=None,
                           from_date=None, to_date=None):
        """Tra cứu hóa đơn đã phát hành."""
        params = {}
        if transaction_id:
            params['transactionID'] = transaction_id
        if inv_no:
            params['invNo'] = inv_no
        if from_date:
            params['fromDate'] = from_date
        if to_date:
            params['toDate'] = to_date
        result = self._get(API_PATHS['search_invoice'], params=params)
        return self._handle_response(result, 'Tra cứu hóa đơn')

    def api_download_invoice(self, transaction_ids, file_type='Pdf'):
        """
        Tải hóa đơn.
        file_type: 'Pdf' | 'Xml' | 'All'
        Trả về list[{TransactionID, Data}]
        """
        params = {
            'invoiceWithCode': 'true',
            'invoiceCalcu':    'false',
            'downloadDataType': file_type,
        }
        result = self._post(
            API_PATHS['download_invoice'],
            transaction_ids,
            params=params,
        )
        return self._handle_response(result, 'Tải hóa đơn')

    def api_test_connection(self):
        """Kiểm tra kết nối – chỉ thử lấy token."""
        try:
            self._refresh_token()
            return True, _('Kết nối thành công!')
        except Exception as e:
            return False, str(e)
