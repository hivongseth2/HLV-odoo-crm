# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
from ast import literal_eval

from odoo import api, fields, models


class AmisCallbackLog(models.Model):
    _name = 'amis.callback.log'
    _description = 'Nhat ky AMIS Callback'
    _order = 'received_at desc, id desc'

    name = fields.Char(default='/', required=True, copy=False, index=True)
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    request_path = fields.Char(string='Duong dan request')
    remote_addr = fields.Char(string='IP nguon')
    app_id = fields.Char(string='App ID')
    org_company_code = fields.Char(string='Ma cong ty doi tac', index=True)
    data_type = fields.Integer(string='Loai du lieu', index=True)
    input_success = fields.Boolean(string='Input hop le')
    input_error_code = fields.Char(string='Ma loi input')
    input_error_message = fields.Text(string='Thong diep loi input')
    signature = fields.Char(string='Signature', index=True)
    signature_valid = fields.Boolean(string='Signature hop le', index=True)
    raw_payload = fields.Text(string='Payload goc')
    data_payload = fields.Text(string='Du lieu data')
    response_success = fields.Boolean(string='Phan hoi thanh cong', default=True, index=True)
    response_error_code = fields.Char(string='Ma loi phan hoi')
    response_error_message = fields.Text(string='Thong diep loi phan hoi')
    state = fields.Selection([
        ('received', 'Da nhan'),
        ('validated', 'Hop le'),
        ('rejected', 'Tu choi'),
        ('failed', 'That bai'),
    ], default='received', required=True, index=True)
    detail_line_ids = fields.One2many('amis.callback.log.line', 'log_id', string='Chi tiet callback')
    detail_count = fields.Integer(string='So dong chi tiet', compute='_compute_detail_count')

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
    _description = 'Dong chi tiet AMIS Callback'
    _order = 'sequence, id'

    log_id = fields.Many2one('amis.callback.log', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=1)
    org_refid = fields.Char(string='Org Ref ID', index=True)
    success = fields.Boolean(string='Thanh cong')
    error_code = fields.Char(string='Ma loi')
    error_message = fields.Text(string='Thong diep loi')
    session_id = fields.Char(string='Session ID', index=True)
    error_call_back_message = fields.Text(string='Thong diep callback loi')
    voucher_type = fields.Integer(string='Loai chung tu')
    raw_json = fields.Text(string='JSON goc')
    @api.model
    def create(self, vals):
        record = super().create(vals)
        record._apply_sync_result()
        return record

    def _apply_sync_result(self):
        for line in self:
            org_refid = (line.org_refid or '').strip()
            if not org_refid:
                continue
            success = bool(line.success)
            voucher_type = int(line.voucher_type or 0)
            item = line._misa_callback_item()
            voucher_data = line._misa_callback_voucher_data(item)
            actual_refid = (
                voucher_data.get('refid') or item.get('refid') or item.get('misa_refid') or org_refid
            )
            if voucher_type == 21:
                po = self.env['purchase.order'].sudo().search([
                    ('misa_purchase_order_org_refid', '=', org_refid),
                ], limit=1)
                if po:
                    vals = {'misa_purchase_order_synced': success}
                    if success and actual_refid:
                        vals['misa_purchase_order_refid'] = actual_refid
                    po.write(vals)
                    if success:
                        line._apply_purchase_order_detail_ids(po, voucher_data)
            elif voucher_type in (7, 18):
                picking = self.env['stock.picking'].sudo().search([
                    ('misa_inward_org_refid', '=', org_refid),
                ], limit=1)
                if picking:
                    picking.write({'misa_inward_synced': success})

    def _misa_callback_item(self):
        self.ensure_one()
        if not self.raw_json:
            return {}
        try:
            item = json.loads(self.raw_json)
        except Exception:
            return {}
        return item if isinstance(item, dict) else {}

    def _misa_callback_voucher_data(self, item):
        data = item.get('data') if isinstance(item, dict) else None
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return data if isinstance(data, dict) else {}

    def _apply_purchase_order_detail_ids(self, po, voucher_data):
        details = voucher_data.get('detail') or []
        if not isinstance(details, list):
            return
        lines_by_sort = {
            index: line
            for index, line in enumerate(po.order_line.filtered(lambda l: not getattr(l, 'display_type', False)), start=1)
        }
        lines_by_code = {}
        for po_line in lines_by_sort.values():
            code = (po_line.product_id.default_code or '').strip()
            if code:
                lines_by_code.setdefault(code, []).append(po_line)
        for detail in details:
            if not isinstance(detail, dict):
                continue
            ref_detail_id = (detail.get('ref_detail_id') or '').strip()
            if not ref_detail_id:
                continue
            po_line = self.env['purchase.order.line']
            current = (detail.get('org_ref_detail_id') or '').strip()
            if current:
                po_line = po.order_line.filtered(lambda l: l.misa_purchase_order_ref_detail_id == current)[:1]
            if not po_line:
                sort_order = int(detail.get('sort_order') or 0)
                po_line = lines_by_sort.get(sort_order) or self.env['purchase.order.line']
            if not po_line:
                code = (detail.get('inventory_item_code') or '').strip()
                candidates = lines_by_code.get(code) or []
                po_line = candidates[0] if candidates else self.env['purchase.order.line']
            if po_line:
                po_line.sudo().write({'misa_purchase_order_ref_detail_id': ref_detail_id})
