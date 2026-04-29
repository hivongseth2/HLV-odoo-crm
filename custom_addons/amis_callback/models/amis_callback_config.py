# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmisCallbackConfig(models.Model):
    _name = 'amis.callback.config'
    _description = 'Cau hinh AMIS Callback'

    name = fields.Char(string='Ten cau hinh', default='AMIS Callback', required=True)
    app_id = fields.Char(
        string='Ma ung dung (App ID)',
        help='MISA app_id dùng làm key để xác thực signature HMAC SHA256.',
        required=True,
        default='cfd435c9-b5c9-484f-b86d-ddbba36dc0f4',
    )
    callback_route = fields.Char(
        string='Duong dan callback',
        default='/api/oauth/actopensupport/call_back_data',
        readonly=True,
    )
    active = fields.Boolean(string='Kich hoat', default=True)
    note = fields.Text(
        string='Ghi chu',
        default='Cập nhật app_id đúng với giá trị MISA cấp cho hệ thống của bạn.',
    )
    api_url = fields.Char(
        string='API URL',
        required=True,
        default='https://actapi.misa.vn',
        help='URL goc API ACT OpenAPI, vi du: https://actapi.misa.vn',
    )
    org_company_code = fields.Char(
        string='Org Company Code',
        default='',
        help='Domain don vi doi tac tren AMIS Ke toan.',
    )
    access_code = fields.Char(
        string='Access Code',
        help='Ma ket noi lay tu man hinh thiet lap API ket noi cua AMIS Ke toan.',
    )
    access_token = fields.Text(
        string='Access Token',
        readonly=True,
        copy=False,
    )
    token_expired_time = fields.Char(
        string='Han token',
        readonly=True,
        copy=False,
    )
    sync_incoming_po_enabled = fields.Boolean(
        string='Dong bo phieu nhap tu PO',
        default=False,
        help='Bat de tu dong day phieu nhap kho (incoming) co nguon tu don mua hang len MISA.',
    )
    sync_outgoing_so_enabled = fields.Boolean(
        string='Dong bo phieu xuat kho tu SO',
        default=False,
        help='Bat de tu dong day phieu xuat kho (outgoing) co nguon tu don hang ban len MISA.',
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
            raise UserError('Vui long nhap Access Code truoc khi ket noi.')
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
            raise UserError('Khong lay duoc access_token tu ham connect.')

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
                raise UserError('Chua co access_token. Vui long bam "Ket noi MISA" truoc.')
            headers['X-MISA-AccessToken'] = self.access_token
        return headers

    def _post_actopen(self, path, payload, include_token=True, timeout=60):
        self.ensure_one()
        api_url = (self.api_url or '').rstrip('/')
        if not api_url:
            raise UserError('Thieu API URL.')
        url = f'{api_url}{path}'
        headers = self._build_headers(include_token=include_token)
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            _logger.exception('AMIS call failed: %s %s', path, exc)
            raise UserError(f'Goi API MISA that bai: {exc}')

        if not body.get('Success'):
            err = body.get('ErrorMessage') or body.get('ErrorCode') or 'Khong ro loi'
            raise UserError(f'MISA tra ve loi: {err}')
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
        if not self.sync_incoming_po_enabled:
            return False
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
            raise UserError('Thieu cau hinh MISA: %s' % ', '.join(missing))
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
