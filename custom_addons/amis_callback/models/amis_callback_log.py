# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
from ast import literal_eval

from odoo import api, fields, models


class AmisCallbackLog(models.Model):
    _name = 'amis.callback.log'
    _description = 'AMIS Callback Log'
    _order = 'received_at desc, id desc'

    name = fields.Char(default='/', required=True, copy=False, index=True)
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    request_path = fields.Char(string='Request Path')
    remote_addr = fields.Char(string='Remote IP')
    app_id = fields.Char(string='App ID')
    org_company_code = fields.Char(string='Org Company Code', index=True)
    data_type = fields.Integer(string='Data Type', index=True)
    input_success = fields.Boolean(string='Input Success')
    input_error_code = fields.Char(string='Input Error Code')
    input_error_message = fields.Text(string='Input Error Message')
    signature = fields.Char(string='Signature', index=True)
    signature_valid = fields.Boolean(string='Signature Valid', index=True)
    raw_payload = fields.Text(string='Raw Payload')
    data_payload = fields.Text(string='Data Payload')
    response_success = fields.Boolean(string='Response Success', default=True, index=True)
    response_error_code = fields.Char(string='Response Error Code')
    response_error_message = fields.Text(string='Response Error Message')
    state = fields.Selection([
        ('received', 'Received'),
        ('validated', 'Validated'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ], default='received', required=True, index=True)
    detail_line_ids = fields.One2many('amis.callback.log.line', 'log_id', string='Callback Details')
    detail_count = fields.Integer(string='Detail Count', compute='_compute_detail_count')

    @api.depends('detail_line_ids')
    def _compute_detail_count(self):
        for record in self:
            record.detail_count = len(record.detail_line_ids)

    @api.model
    def _next_name(self):
        return self.env['ir.sequence'].next_by_code('amis.callback.log') or '/'

    @api.model
    def create(self, vals):
        if not vals.get('name') or vals.get('name') == '/':
            vals['name'] = self._next_name()
        return super().create(vals)

    @api.model
    def _generate_signature(self, data_string, key):
        data_string = data_string or ''
        key = key or ''
        digest = hmac.new(
            key.encode('utf-8'),
            msg=data_string.encode('utf-8'),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return digest

    @api.model
    def _parse_data_items(self, data_value):
        if not data_value:
            return []
        if isinstance(data_value, list):
            return data_value
        if isinstance(data_value, dict):
            return [data_value]
        if isinstance(data_value, str):
            try:
                parsed = json.loads(data_value)
            except Exception:
                try:
                    parsed = literal_eval(data_value)
                except Exception:
                    return []
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        return []

    @api.model
    def create_from_payload(self, payload, raw_body='', request_path='', remote_addr='', parse_error=''):
        payload = payload or {}
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        app_id = (config.app_id or '').strip()
        data_string = payload.get('data', '')
        signature = payload.get('signature', '')
        expected_signature = self._generate_signature(data_string, app_id)
        signature_valid = bool(signature and expected_signature == signature)

        response = {
            'Success': True,
            'ErrorMessage': '',
        }
        state = 'validated'

        if parse_error:
            response = {
                'Success': False,
                'ErrorCode': 'InvalidParam',
                'ErrorMessage': parse_error,
            }
            state = 'failed'
            signature_valid = False
        elif not signature_valid:
            response = {
                'Success': False,
                'ErrorCode': 'InvalidParam',
                'ErrorMessage': 'Signature invalid',
            }
            state = 'rejected'

        log = self.create({
            'request_path': request_path,
            'remote_addr': remote_addr,
            'app_id': payload.get('app_id') or app_id,
            'org_company_code': payload.get('org_company_code'),
            'data_type': int(payload.get('data_type') or 0),
            'input_success': bool(payload.get('success')),
            'input_error_code': payload.get('error_code') or False,
            'input_error_message': payload.get('error_message') or '',
            'signature': signature,
            'signature_valid': signature_valid,
            'raw_payload': raw_body or json.dumps(payload, ensure_ascii=False, indent=2),
            'data_payload': data_string if isinstance(data_string, str) else json.dumps(data_string, ensure_ascii=False),
            'response_success': bool(response.get('Success')),
            'response_error_code': response.get('ErrorCode') or False,
            'response_error_message': response.get('ErrorMessage') or '',
            'state': state,
        })

        if signature_valid and not parse_error:
            data_items = self._parse_data_items(data_string)
            line_vals = []
            for index, item in enumerate(data_items, start=1):
                if not isinstance(item, dict):
                    continue
                session_id = item.get('session_id')
                if isinstance(session_id, dict):
                    session_id = json.dumps(session_id, ensure_ascii=False)
                line_vals.append({
                    'log_id': log.id,
                    'sequence': index,
                    'org_refid': item.get('org_refid'),
                    'success': bool(item.get('success')),
                    'error_code': item.get('error_code') or False,
                    'error_message': item.get('error_message') or '',
                    'session_id': session_id or False,
                    'error_call_back_message': item.get('error_call_back_message') or '',
                    'voucher_type': item.get('voucher_type') if item.get('voucher_type') is not None else False,
                    'raw_json': json.dumps(item, ensure_ascii=False),
                })
            if line_vals:
                self.env['amis.callback.log.line'].sudo().create(line_vals)

        return response


class AmisCallbackLogLine(models.Model):
    _name = 'amis.callback.log.line'
    _description = 'AMIS Callback Log Line'
    _order = 'sequence, id'

    log_id = fields.Many2one('amis.callback.log', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=1)
    org_refid = fields.Char(string='Org Ref ID', index=True)
    success = fields.Boolean(string='Success')
    error_code = fields.Char(string='Error Code')
    error_message = fields.Text(string='Error Message')
    session_id = fields.Char(string='Session ID', index=True)
    error_call_back_message = fields.Text(string='Error Callback Message')
    voucher_type = fields.Integer(string='Voucher Type')
    raw_json = fields.Text(string='Raw JSON')
