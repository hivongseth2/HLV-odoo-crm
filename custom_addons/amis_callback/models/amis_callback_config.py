# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmisCallbackConfig(models.Model):
    _name = 'amis.callback.config'
    _description = 'Cấu hình AMIS Callback'

    name = fields.Char(string='Tên cấu hình', default='AMIS Callback', required=True)
    app_id = fields.Char(
        string='Mã ứng dụng (App ID)',
        help='MISA app_id dùng làm key để xác thực signature HMAC SHA256.',
        required=True,
        default='cfd435c9-b5c9-484f-b86d-ddbba36dc0f4',
    )
    callback_route = fields.Char(
        string='Đường dẫn callback',
        default='/api/oauth/actopensupport/call_back_data',
        readonly=True,
    )
    active = fields.Boolean(string='Kích hoạt', default=True)
    note = fields.Text(
        string='Ghi chú',
        default='Hàm kết nối token: https://actapp.misa.vn/api/oauth/actopen/connect. Cập nhật app_id và access_code đúng với giá trị MISA cấp cho hệ thống của bạn.',
    )
    api_url = fields.Char(
        string='API URL',
        required=True,
        default='https://actapp.misa.vn',
        help='URL gốc API ACT OpenAPI, ví dụ: https://actapp.misa.vn',
    )
    org_company_code = fields.Char(
        string='Mã miền công ty (org_company_code)',
        default='',
        help='Domain đơn vị đối tác trên AMIS Kế toán.',
    )
    access_code = fields.Char(
        string='Mã kết nối (access_code)',
        help='Mã kết nối lấy từ màn hình thiết lập API kết nối của AMIS Kế toán.',
    )
    access_token = fields.Text(
        string='Access Token',
        readonly=True,
        copy=False,
    )
    token_expired_time = fields.Char(
        string='Hạn token',
        readonly=True,
        copy=False,
    )
    sync_incoming_po_enabled = fields.Boolean(
        string='Đồng bộ phiếu nhập từ PO',
        default=False,
        help='Bật để tự động đẩy phiếu nhập kho (incoming) có nguồn từ đơn mua hàng lên MISA.',
    )
    sync_outgoing_so_enabled = fields.Boolean(
        string='Đồng bộ phiếu xuất kho từ SO',
        default=False,
        help='Bật để tự động đẩy phiếu xuất kho (outgoing) có nguồn từ đơn hàng bán lên MISA.',
    )
    misa_branch_id = fields.Char(
        string='MISA Branch ID',
        default='53a073a0-5381-4493-820f-51ea32ebe990',
        help='Branch ID thật trên MISA dùng cho chứng từ nhập kho.',
    )
    misa_stock_id = fields.Char(
        string='MISA Stock ID',
        default='de167b2d-ec5f-404a-8532-08257193bc91',
        help='Stock ID thật trên MISA (kho HLV).',
    )

    def ensure_singleton(self):
        record = self.search([], limit=1)
        if record:
            return record
        return self.create({
            'name': 'AMIS Callback',
        })

    def action_connect_misa(self):
        self.ensure_one()
        if not self.access_code:
            raise UserError('Vui lòng nhập Access Code trước khi kết nối.')
        payload = {
            'app_id': self.app_id,
            'access_code': self.access_code,
            'org_company_code': self.org_company_code,
        }
        response = self._post_actopen('/api/oauth/actopen/connect', payload, include_token=False)
        data_raw = response.get('Data')
        data_obj = {}
        if isinstance(data_raw, str):
            try:
                data_obj = json.loads(data_raw)
            except Exception:
                data_obj = {}
        elif isinstance(data_raw, dict):
            data_obj = data_raw

        token = data_obj.get('access_token')
        expired = data_obj.get('expired_time')
        if not token:
            raise UserError('Không lấy được access_token từ hàm connect.')

        self.sudo().write({
            'access_token': token,
            'token_expired_time': expired or '',
        })
        return True

    def _build_headers(self, include_token=True):
        self.ensure_one()
        headers = {
            'Content-Type': 'application/json',
        }
        if include_token:
            if not self.access_token:
                raise UserError('Chưa có access_token. Vui lòng bấm "Kết nối MISA" trước.')
            headers['X-MISA-AccessToken'] = self.access_token
        return headers

    def _post_actopen(self, path, payload, include_token=True, timeout=15):
        self.ensure_one()
        api_url = (self.api_url or '').rstrip('/')
        if not api_url:
            raise UserError('Thiếu API URL.')
        url = f'{api_url}{path}'
        headers = self._build_headers(include_token=include_token)
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            _logger.exception('AMIS call failed: %s %s', path, exc)
            raise UserError(f'Gọi API MISA thất bại: {exc}')

        if not body.get('Success'):
            err = body.get('ErrorMessage') or body.get('ErrorCode') or 'Không rõ lỗi'
            raise UserError(f'MISA trả về lỗi: {err}')
        return body

    def push_dictionary(self, dictionary_items):
        self.ensure_one()
        if not dictionary_items:
            return {'Success': True}
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'dictionary': dictionary_items,
        }
        return self._post_actopen('/apir/sync/actopen/save_dictionary', payload, include_token=True)

    def get_dictionary(self, data_type, branch_id=None, skip=0, take=100, last_sync_time=None):
        """Lay danh muc tu AMIS ke toan theo endpoint get_dictionary.

        Returns:
            dict: {
                'raw': body goc,
                'items': danh sach item da parse tu Data,
                'custom_data': dict parse tu CustomData,
                'last_sync_time': gia tri LastSyncTime neu co,
            }
        """
        self.ensure_one()

        take = int(take or 0)
        if take <= 0:
            take = 100
        if take > 100:
            take = 100

        payload = {
            'data_type': int(data_type),
            'branch_id': branch_id or None,
            'skip': int(skip or 0),
            'take': take,
            'app_id': self.app_id,
            'last_sync_time': last_sync_time or None,
        }
        body = self._post_actopen('/apir/sync/actopen/get_dictionary', payload, include_token=True)

        data_raw = body.get('Data')
        items = []
        if isinstance(data_raw, str):
            try:
                parsed = json.loads(data_raw)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                items = []
        elif isinstance(data_raw, list):
            items = data_raw

        custom_raw = body.get('CustomData')
        custom_data = {}
        if isinstance(custom_raw, str):
            try:
                custom_data = json.loads(custom_raw) or {}
            except Exception:
                custom_data = {}
        elif isinstance(custom_raw, dict):
            custom_data = custom_raw

        return {
            'raw': body,
            'items': items,
            'custom_data': custom_data,
            'last_sync_time': custom_data.get('LastSyncTime'),
        }

    def find_dictionary_item_by_code(self, data_type, code_field, code_value, branch_id=None, take=100, max_pages=30):
        """Tim 1 item danh muc theo code voi phan trang get_dictionary."""
        self.ensure_one()
        if not code_value:
            return False

        skip = 0
        take = min(max(int(take or 100), 1), 100)
        for _page in range(max(1, int(max_pages or 1))):
            result = self.get_dictionary(
                data_type=data_type,
                branch_id=branch_id,
                skip=skip,
                take=take,
                last_sync_time=None,
            )
            items = result.get('items') or []
            for item in items:
                if str(item.get(code_field) or '').strip() == str(code_value).strip():
                    return item
            if len(items) < take:
                break
            skip += take
        return False

    def push_inward_voucher(self, voucher_payload, dictionary_items=None):
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_outgoing_voucher(self, voucher_payload, dictionary_items=None):
        """Dua phieu xuat kho sang MISA.
        
        Tuong tu push_inward_voucher, dung de dua chung tu xuat kho (outgoing) len MISA.
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': dictionary_items or [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_sa_voucher(self, voucher_payload):
        """Push SAVoucher (ban hang kiem xuat kho, voucher_type=13) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def push_sa_invoice(self, voucher_payload):
        """Push SAInvoice (hoa don ban hang, voucher_type=11) len MISA."""
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
            'voucher': [voucher_payload],
            'dictionary': [],
        }
        return self._post_actopen('/apir/sync/actopen/save', payload, include_token=True)

    def ensure_sync_ready(self):
        self.ensure_one()
        missing = []
        if not self.app_id:
            missing.append('App ID')
        if not self.org_company_code:
            missing.append('Org Company Code')
        if not self.api_url:
            missing.append('API URL')
        if not self.access_token:
            missing.append('Access Token')
        if missing:
            raise UserError('Thiếu cấu hình MISA: %s' % ', '.join(missing))
        return True

    def delete_call_back_data(self):
        """Xoa ket qua goi callback cua tai khoan ung dung ACT.
        
        Endpoint: POST /api/oauth/actopensupport/delete_call_back_data
        Dung de xoa cac ket qua callback da ghi nhan de test.
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
        }
        return self._post_actopen('/api/oauth/actopensupport/delete_call_back_data', payload, include_token=False)

    def check_call_back_data(self):
        """Kiem tra cac ket qua goi callback cua tai khoan ung dung demo.
        
        Endpoint: POST /api/oauth/actopensupport/check_call_back_data
        Dung de kiem tra cac loi goi da tu phat toi ham call_back_data,
        dung de test thong luong callback.
        
        Returns:
            dict: Trai ve Success, ErrorMessage, va Data (danh sach ket qua callback).
        """
        self.ensure_one()
        payload = {
            'app_id': self.app_id,
            'org_company_code': self.org_company_code,
        }
        return self._post_actopen('/api/oauth/actopensupport/check_call_back_data', payload, include_token=False)

    def action_test_outgoing_push(self):
        """Action de test push outgoing (dung cho test)"""
        return True
