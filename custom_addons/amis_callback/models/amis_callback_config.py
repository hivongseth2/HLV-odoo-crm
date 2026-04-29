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

    def _post_actopen(self, path, payload, include_token=True, timeout=60):
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
