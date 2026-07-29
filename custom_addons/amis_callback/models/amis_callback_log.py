# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
from ast import literal_eval

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


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
            voucher_items = self._parse_voucher_payload_items(data_value)
            if voucher_items:
                return voucher_items
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
                voucher_items = self._parse_voucher_payload_items(parsed)
                if voucher_items:
                    return voucher_items
                return [parsed]
        return []

    @api.model
    def _parse_voucher_payload_items(self, payload):
        vouchers = payload.get('voucher') if isinstance(payload, dict) else None
        if not isinstance(vouchers, list):
            return []
        items = []
        custom_param = payload.get('custom_param') or {}
        model_state = custom_param.get('ModelState') if isinstance(custom_param, dict) else False
        for voucher in vouchers:
            if not isinstance(voucher, dict):
                continue
            item = dict(voucher)
            item['org_refid'] = (
                voucher.get('org_refid')
                or voucher.get('refid')
                or item.get('org_refid')
            )
            item['org_refno'] = (
                voucher.get('org_refno')
                or voucher.get('refno')
                or item.get('org_refno')
            )
            item['voucher_type'] = voucher.get('voucher_type') or item.get('voucher_type')
            item['success'] = voucher.get('success') if voucher.get('success') is not None else True
            item['data'] = voucher
            item['_misa_model_state'] = model_state
            items.append(item)
        return items

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
            data_type = int(line.log_id.data_type or 0)
            item = line._misa_callback_item()
            voucher_type = line._misa_callback_voucher_type(item)
            item_refno = line._misa_callback_refno(item)
            is_request_callback = line._misa_callback_is_request_callback(voucher_type, item_refno)
            voucher_data = line._misa_callback_voucher_data(item)
            actual_refid = (
                voucher_data.get('refid') or item.get('refid') or item.get('misa_refid') or org_refid
            )
            if voucher_type == 13 and data_type in (1, 3):
                line._apply_sa_voucher_result(org_refid, success)
                continue

            picking = line._misa_callback_find_inward_picking(org_refid, item_refno, voucher_type)
            is_inward_callback = voucher_type in (7, 18) or bool(picking) or line._misa_refno_looks_like_inward(item_refno)
            po = self.env['purchase.order'].sudo()
            if voucher_type in (0, 21) and not is_inward_callback:
                po_domain = [('misa_purchase_order_org_refid', '=', org_refid)]
                if item_refno:
                    po_domain.append(('name', '=', item_refno))
                po = self.env['purchase.order'].sudo().search(po_domain, limit=1)
                if not po and not item_refno:
                    po = self.env['purchase.order'].sudo().search([
                        ('misa_purchase_order_org_refid', '=', org_refid),
                    ], limit=1)
            elif is_inward_callback:
                collided_po = self.env['purchase.order'].sudo().search([
                    ('misa_purchase_order_org_refid', '=', org_refid),
                ], limit=1)
                if collided_po:
                    _logger.warning(
                        'Bo qua apply callback phieu nhap vao don mua %s vi org_refid bi trung: %s.',
                        collided_po.name,
                        org_refid,
                    )
            if po:
                session_id = (line.session_id or '').strip()
                error_message = line.error_message or line.error_call_back_message or ''
                if data_type == 2:
                    if success:
                        po._misa_complete_purchase_order_deletion()
                    else:
                        is_created_voucher = (
                            (line.error_code or '').strip() == 'IsCreatedVoucher'
                            or 'Đã sinh chứng từ' in error_message
                        )
                        po.with_context(skip_misa_purchase_order_lifecycle=True).sudo().write({
                            'misa_purchase_order_state': (
                                'manual_delete_required' if is_created_voucher else 'error'
                            ),
                            'misa_purchase_order_last_error': error_message,
                            'misa_purchase_order_session_id': session_id or False,
                            'misa_purchase_order_state_updated_at': fields.Datetime.now(),
                        })
                    continue

                if data_type == 22:
                    try:
                        model_state = int(item.get('_misa_model_state') or 0)
                    except (TypeError, ValueError):
                        model_state = 0
                    if model_state == 3:
                        po._misa_complete_purchase_order_deletion()
                        continue
                    state_by_model_state = {
                        1: 'created',
                        2: 'changed_on_misa',
                        7: 'posted',
                        8: 'unposted',
                    }
                    misa_state = state_by_model_state.get(model_state)
                    if misa_state:
                        po.with_context(skip_misa_purchase_order_lifecycle=True).sudo().write({
                            'misa_purchase_order_synced': True,
                            'misa_purchase_order_state': misa_state,
                            'misa_purchase_order_last_error': False,
                            'misa_purchase_order_state_updated_at': fields.Datetime.now(),
                        })
                        if success:
                            line._apply_purchase_order_detail_ids(po, voucher_data)
                        continue

                vals = {}
                if success and actual_refid:
                    vals['misa_purchase_order_refid'] = actual_refid
                vals.update({
                    'misa_purchase_order_last_error': False if success else error_message,
                    'misa_purchase_order_session_id': session_id or False,
                    'misa_purchase_order_state_updated_at': fields.Datetime.now(),
                })
                if not is_request_callback:
                    vals['misa_purchase_order_synced'] = success
                    vals['misa_purchase_order_state'] = 'created' if success else 'error'
                elif not success:
                    vals['misa_purchase_order_synced'] = False
                    vals['misa_purchase_order_state'] = 'error'
                elif data_type in (1, 3):
                    vals['misa_purchase_order_state'] = 'request_accepted'
                if vals:
                    po.with_context(skip_misa_purchase_order_lifecycle=True).sudo().write(vals)
                if is_request_callback and not success and data_type in (1, 3):
                    retry_job = self.env['amis.sync.job'].sudo().search([
                        ('purchase_order_id', '=', po.id),
                        ('direction', '=', 'purchase_order'),
                    ], order='id desc', limit=1)
                    if retry_job:
                        retry_scheduled = retry_job._schedule_retry_after_callback_error(error_message)
                    else:
                        po._enqueue_misa_purchase_order(force=True)
                        retry_scheduled = True
                    if retry_scheduled:
                        po.with_context(skip_misa_purchase_order_lifecycle=True).sudo().write({
                            'misa_purchase_order_state': 'queued',
                            'misa_purchase_order_last_error': error_message,
                            'misa_purchase_order_state_updated_at': fields.Datetime.now(),
                        })
                        _logger.warning(
                            'MISA bao loi de nghi don mua %s; da dua job ve hang doi gui lai: %s',
                            po.name,
                            error_message,
                        )
                    else:
                        _logger.error(
                            'MISA bao loi de nghi don mua %s; job da het %s lan thu: %s',
                            po.name,
                            retry_job.retry_count,
                            error_message,
                        )
                if is_request_callback and success:
                    _logger.info(
                        'MISA da nhan de nghi don mua %s (%s), cho callback sinh chung tu that su.',
                        po.name,
                        org_refid,
                    )
                if success and not is_request_callback:
                    line._apply_purchase_order_detail_ids(po, voucher_data)
            else:
                payment_request = self.env['amis.payment.request'].sudo().search([
                    ('org_refid', '=', org_refid),
                ], limit=1)
                if not payment_request and item_refno:
                    payment_request = self.env['amis.payment.request'].sudo().search([
                        ('name', '=', item_refno),
                    ], limit=1)
                    if payment_request:
                        _logger.info(
                            'Matched MISA payment callback by refno %s because callback org_refid %s differs.',
                            item_refno,
                            org_refid,
                        )
                if payment_request:
                    error_message = line.error_message or line.error_call_back_message or ''
                    session_id = (line.session_id or '').strip()
                    if data_type == 2:
                        is_created_voucher = (
                            (line.error_code or '').strip() == 'IsCreatedVoucher'
                            or 'Đã sinh chứng từ' in error_message
                        )
                        payment_request.write({
                            'state': (
                                'deleted' if success
                                else 'manual_delete_required' if is_created_voucher
                                else 'error'
                            ),
                            'error_msg': False if success else error_message,
                            'callback_session_id': session_id or False,
                            'callback_data_type': data_type,
                            'state_updated_at': fields.Datetime.now(),
                        })
                        continue
                    if data_type == 22:
                        try:
                            model_state = int(item.get('_misa_model_state') or 0)
                        except (TypeError, ValueError):
                            model_state = 0
                        if model_state == 3:
                            payment_request.write({
                                'state': 'deleted',
                                'error_msg': False,
                                'callback_data_type': data_type,
                                'state_updated_at': fields.Datetime.now(),
                            })
                            continue
                    vals = {
                        'state': (
                            payment_request.state
                            if payment_request.state in (
                                'delete_pending', 'manual_delete_required', 'deleted'
                            )
                            else 'approved'
                            if success and (
                                data_type == 18 or payment_request.state == 'approved'
                            )
                            else 'request_accepted'
                            if success and data_type in (1, 3) and is_request_callback
                            else 'synced' if success
                            else 'error'
                        ),
                        'error_msg': False if success else error_message,
                        'callback_session_id': session_id or False,
                        'callback_data_type': data_type,
                        'state_updated_at': fields.Datetime.now(),
                    }
                    if success and actual_refid:
                        vals['misa_refid'] = actual_refid
                    payment_request.write(vals)
                    continue
            if voucher_type in (0, 7, 18):
                if not picking:
                    picking = line._misa_callback_find_inward_picking(org_refid, item_refno, voucher_type)
                if picking:
                    if is_request_callback and success:
                        _logger.info(
                            'MISA da nhan de nghi phieu nhap %s (%s), cho callback sinh chung tu that su.',
                            picking.name,
                            org_refid,
                        )
                    else:
                        picking.write({'misa_inward_synced': success})

    def _apply_sa_voucher_result(self, org_refid, success):
        """Apply asynchronous save result for SAVoucher (voucher_type=13)."""
        self.ensure_one()
        sale_order = self.env['sale.order'].sudo().search([
            ('misa_sa_voucher_org_refid', '=', org_refid),
        ], limit=1)
        if not sale_order:
            _logger.warning(
                'Khong tim thay sale.order cho callback SAVoucher org_refid=%s.',
                org_refid,
            )
            return False

        error_message = (
            self.error_message
            or self.error_call_back_message
            or self.error_code
            or 'MISA callback SAVoucher failed'
        )
        sale_order.sudo().write({'misa_sa_voucher_synced': bool(success)})

        job = self.env['amis.sync.job'].sudo().search([
            ('sale_order_id', '=', sale_order.id),
            ('direction', '=', 'outgoing'),
        ], order='id desc', limit=1)

        if success:
            if job:
                job.sudo().write({
                    'status': 'done',
                    'error_msg': False,
                    'processed_at': fields.Datetime.now(),
                })
            _logger.info(
                'MISA callback xac nhan SAVoucher thanh cong cho SO %s (%s).',
                sale_order.name,
                org_refid,
            )
            return True

        retry_scheduled = False
        if job:
            retry_scheduled = job._schedule_retry_after_callback_error(error_message)
        else:
            picking = self.env['stock.picking'].sudo().search([
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'outgoing'),
                ('move_ids_without_package.sale_line_id.order_id', '=', sale_order.id),
            ], order='date_done desc, id desc', limit=1)
            if picking:
                picking._enqueue_misa_sync('outgoing')
                retry_scheduled = bool(self.env['amis.sync.job'].sudo().search([
                    ('sale_order_id', '=', sale_order.id),
                    ('direction', '=', 'outgoing'),
                    ('status', '=', 'pending'),
                ], limit=1))
            else:
                _logger.error(
                    'Callback SAVoucher loi cho SO %s nhung khong tim thay outgoing job/picking de retry: %s',
                    sale_order.name,
                    error_message,
                )

        _logger.warning(
            'MISA callback bao loi SAVoucher cho SO %s (%s); retry_scheduled=%s: %s',
            sale_order.name,
            org_refid,
            retry_scheduled,
            error_message,
        )
        return retry_scheduled

    def _misa_callback_voucher_type(self, item=None):
        self.ensure_one()
        item = item or {}
        raw_value = self.voucher_type or item.get('voucher_type') or 0
        try:
            return int(raw_value or 0)
        except Exception:
            return 0

    def _misa_callback_refno(self, item=None):
        item = item or {}
        return (item.get('org_refno') or item.get('refno') or '').strip()

    def _misa_callback_is_request_callback(self, voucher_type, item_refno):
        return bool(voucher_type) and not (item_refno or '').strip()

    def _misa_refno_looks_like_inward(self, refno):
        refno = (refno or '').strip().upper()
        if not refno:
            return False
        return '/IN/' in refno or refno.startswith(('KBC/', 'NK'))

    def _misa_callback_find_inward_picking(self, org_refid, item_refno='', voucher_type=0):
        self.ensure_one()
        StockPicking = self.env['stock.picking'].sudo()
        picking = StockPicking
        item_refno = (item_refno or '').strip()
        if item_refno:
            picking = StockPicking.search([('name', '=', item_refno)], limit=1)
        if not picking and voucher_type in (0, 7, 18):
            picking = StockPicking.search([
                ('misa_inward_org_refid', '=', org_refid),
            ], limit=1)
        return picking

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
                po_line = po.order_line.filtered(
                    lambda l: l.misa_purchase_order_org_ref_detail_id == current
                    or l.misa_purchase_order_ref_detail_id == current
                )[:1]
            if not po_line:
                sort_order = int(detail.get('sort_order') or 0)
                po_line = lines_by_sort.get(sort_order) or self.env['purchase.order.line']
            if not po_line:
                code = (detail.get('inventory_item_code') or '').strip()
                candidates = lines_by_code.get(code) or []
                po_line = candidates[0] if candidates else self.env['purchase.order.line']
            if po_line:
                vals = {
                    'misa_purchase_order_ref_detail_id': ref_detail_id,
                    'misa_purchase_order_ref_detail_synced': True,
                }
                if current:
                    vals['misa_purchase_order_org_ref_detail_id'] = current
                elif not po_line.misa_purchase_order_org_ref_detail_id:
                    vals['misa_purchase_order_org_ref_detail_id'] = (
                        po._misa_purchase_order_line_org_ref_detail_id(po_line)
                    )
                po_line.sudo().write(vals)
