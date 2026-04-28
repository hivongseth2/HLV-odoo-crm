# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ─── Mapping event_type → handler method name ─────────────────────────────────
EVENT_HANDLERS = {
    # Khách hàng
    'customer.created': '_handle_customer',
    'customer.updated': '_handle_customer',
    'customer.create': '_handle_customer',   # alias (CRM v1)
    'customer.update': '_handle_customer',
    # Đơn hàng
    'order.created': '_handle_order',
    'order.updated': '_handle_order',
    'order.create':  '_handle_order',
    'order.update':  '_handle_order',
    # Ping / test
    'ping':    '_handle_ping',
    'test':    '_handle_ping',
    'verify':  '_handle_ping',
}


class MisaCrmProcessor(models.AbstractModel):
    """
    Xử lý nghiệp vụ webhook: parse payload → tạo/cập nhật record Odoo.
    Abstract model → không tạo bảng, gọi qua self.env['misa.crm.processor'].
    """
    _name = 'misa.crm.processor'
    _description = 'MISA CRM Webhook Processor'

    # ─── Entry point ──────────────────────────────────────────────────────────

    def process_log(self, log_rec):
        """
        Xử lý 1 bản ghi misa.crm.webhook.log.
        Cập nhật state → done / error sau khi xử lý xong.
        """
        payload = log_rec.get_payload_dict()
        event_type = (
            log_rec.event_type
            or payload.get('event_type')
            or payload.get('event')
            or ''
        ).lower().strip()

        handler_name = EVENT_HANDLERS.get(event_type, '_handle_unknown')
        handler = getattr(self, handler_name, self._handle_unknown)

        log_rec.write({
            'state': 'processing',
            'processed_date': fields.Datetime.now(),
        })
        try:
            result = handler(log_rec, payload)
            vals = {
                'state': 'done',
                'error_message': False,
                'note': result.get('note', ''),
            }
            if result.get('partner_id'):
                vals['partner_id'] = result['partner_id']
            if result.get('sale_order_id'):
                vals['sale_order_id'] = result['sale_order_id']
            log_rec.write(vals)
            _logger.info(
                'MISA CRM webhook processed: event=%s log_id=%s',
                event_type, log_rec.id
            )
        except Exception as e:
            _logger.exception(
                'MISA CRM webhook error: event=%s log_id=%s err=%s',
                event_type, log_rec.id, e
            )
            log_rec.write({
                'state': 'error',
                'error_message': str(e),
            })

    # ─── Handlers ─────────────────────────────────────────────────────────────

    def _handle_ping(self, log_rec, payload):
        log_rec.write({'state': 'ignored'})
        return {'note': 'Ping/test event – bỏ qua'}

    def _handle_unknown(self, log_rec, payload):
        log_rec.write({'state': 'ignored'})
        return {'note': f'Không nhận dạng được event_type: {log_rec.event_type}'}

    def _handle_customer(self, log_rec, payload):
        """
        Tạo hoặc cập nhật res.partner từ payload khách hàng MISA CRM.

        MISA CRM gửi dữ liệu khách hàng với các trường phổ biến:
          customer_id / id / CustomerId
          customer_name / name / CustomerName
          phone / Phone / mobile
          email / Email
          address / Address
          tax_code / TaxCode / vat
          customer_code / CustomerCode / code
        """
        data = payload.get('data') or payload  # data wrapper hoặc flat

        # Chuẩn hoá field names (CRM có thể dùng camelCase hoặc snake_case)
        crm_id    = str(data.get('customer_id') or data.get('CustomerId') or
                        data.get('id') or '')
        name      = (data.get('customer_name') or data.get('CustomerName') or
                     data.get('name') or 'Khách hàng CRM')
        phone     = data.get('phone') or data.get('Phone') or data.get('mobile') or ''
        email     = data.get('email') or data.get('Email') or ''
        address   = data.get('address') or data.get('Address') or data.get('full_address') or ''
        vat       = data.get('tax_code') or data.get('TaxCode') or data.get('vat') or ''
        ref       = data.get('customer_code') or data.get('CustomerCode') or data.get('code') or ''
        website   = data.get('website') or data.get('Website') or ''
        note_crm  = data.get('note') or data.get('description') or ''

        if not crm_id and not name:
            raise ValidationError('Payload thiếu customer_id và name')

        # Tìm partner theo crm_id (lưu ở ref / comment) hoặc VAT hoặc tên
        partner = self._find_partner_by_crm_id(crm_id)

        vals = {
            'name':    name,
            'phone':   phone,
            'email':   email,
            'vat':     vat,
            'ref':     ref,
            'website': website,
            'comment': note_crm,
            'customer_rank': 1,
            # Lưu CRM ID vào field x_misa_crm_id nếu đã tạo field đó,
            # hoặc vào comment nếu chưa có
        }
        # Thêm địa chỉ nếu có
        if address:
            vals['street'] = address

        if partner:
            partner.write(vals)
            note = f'Cập nhật partner ID={partner.id} từ CRM customer_id={crm_id}'
        else:
            vals['company_type'] = 'person'
            partner = self.env['res.partner'].create(vals)
            note = f'Tạo mới partner ID={partner.id} từ CRM customer_id={crm_id}'

        _logger.info(note)
        return {'partner_id': partner.id, 'note': note}

    def _handle_order(self, log_rec, payload):
        """
        Tạo hoặc cập nhật sale.order từ payload đơn hàng MISA CRM.

        MISA CRM gửi dữ liệu đơn hàng với các trường phổ biến:
          order_id / OrderId / id
          order_code / OrderCode / order_number
          customer_id / CustomerId
          order_date / OrderDate
          total_amount / TotalAmount / total
          status / Status
          details / items / SaleOrderDetails → danh sách sản phẩm
        """
        data = payload.get('data') or payload

        crm_order_id   = str(data.get('order_id') or data.get('OrderId') or
                              data.get('id') or '')
        order_code     = (data.get('order_code') or data.get('OrderCode') or
                          data.get('order_number') or crm_order_id or 'CRM-ORDER')
        crm_cust_id    = str(data.get('customer_id') or data.get('CustomerId') or '')
        order_date_raw = data.get('order_date') or data.get('OrderDate') or ''
        status         = (data.get('status') or data.get('Status') or '').lower()
        note_crm       = data.get('note') or data.get('description') or ''
        details        = (data.get('details') or data.get('items') or
                          data.get('SaleOrderDetails') or [])

        # Tìm / xác định partner
        partner = self._find_partner_by_crm_id(crm_cust_id)
        if not partner and crm_cust_id:
            # Tạo placeholder partner
            partner = self.env['res.partner'].create({
                'name': f'Khách hàng CRM [{crm_cust_id}]',
                'customer_rank': 1,
            })

        # Tìm đơn hàng hiện tại (theo client_order_ref = CRM order code)
        existing = self.env['sale.order'].search(
            [('client_order_ref', '=', order_code)], limit=1
        )

        order_date = self._parse_datetime(order_date_raw)

        order_vals = {
            'partner_id':       partner.id if partner else self.env.ref('base.public_partner').id,
            'client_order_ref': order_code,
            'note':             note_crm,
            'date_order':       order_date or fields.Datetime.now(),
        }

        if existing and existing.state == 'draft':
            existing.write(order_vals)
            order = existing
            note = f'Cập nhật đơn hàng ID={order.id} từ CRM order_id={crm_order_id}'
        elif existing:
            note = (f'Đơn hàng {order_code} đã tồn tại ở trạng thái {existing.state}, '
                    f'bỏ qua cập nhật.')
            return {'sale_order_id': existing.id, 'note': note}
        else:
            order = self.env['sale.order'].create(order_vals)
            note = f'Tạo mới đơn hàng ID={order.id} từ CRM order_id={crm_order_id}'

        # Đồng bộ dòng sản phẩm (chỉ khi draft)
        if order.state == 'draft' and details:
            self._sync_order_lines(order, details)

        _logger.info(note)
        return {'sale_order_id': order.id, 'note': note}

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _find_partner_by_crm_id(self, crm_id):
        """Tìm partner Odoo theo CRM ID (lưu ở field ref hoặc comment)."""
        if not crm_id:
            return None
        # Tìm theo tag comment chứa crm_id
        partner = self.env['res.partner'].search(
            [('comment', 'like', f'[MISA-CRM-ID:{crm_id}]')], limit=1
        )
        if partner:
            return partner
        # Tìm theo ref nếu trùng
        partner = self.env['res.partner'].search(
            [('ref', '=', crm_id)], limit=1
        )
        return partner

    def _sync_order_lines(self, order, details):
        """Đồng bộ dòng sản phẩm từ CRM vào sale.order."""
        # Xoá dòng cũ trước khi ghi lại
        order.order_line.unlink()
        SaleOrderLine = self.env['sale.order.line']
        for item in details:
            product_code = (item.get('product_code') or item.get('ProductCode') or
                            item.get('item_code') or '')
            product_name = (item.get('product_name') or item.get('ProductName') or
                            item.get('name') or 'Sản phẩm CRM')
            qty           = float(item.get('quantity') or item.get('Quantity') or 1)
            unit_price    = float(item.get('unit_price') or item.get('UnitPrice') or
                                  item.get('price') or 0)
            discount      = float(item.get('discount_rate') or item.get('DiscountRate') or 0)

            # Tìm product theo mã
            product = None
            if product_code:
                product = self.env['product.product'].search(
                    [('default_code', '=', product_code)], limit=1
                )
            if not product and product_name:
                product = self.env['product.product'].search(
                    [('name', 'ilike', product_name)], limit=1
                )

            line_vals = {
                'order_id':    order.id,
                'name':        product_name,
                'product_qty': qty,
                'price_unit':  unit_price,
                'discount':    discount,
            }
            if product:
                line_vals['product_id'] = product.id
            else:
                # Dùng sản phẩm dịch vụ mặc định nếu không tìm thấy
                service_product = self.env.ref(
                    'product.product_product_4', raise_if_not_found=False
                )
                if service_product:
                    line_vals['product_id'] = service_product.id
                line_vals['name'] = product_name

            SaleOrderLine.create(line_vals)

    @staticmethod
    def _parse_datetime(raw):
        """Parse nhiều định dạng ngày tháng phổ biến của MISA CRM."""
        if not raw:
            return None
        formats = [
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%d/%m/%Y %H:%M:%S',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(str(raw)[:19], fmt)
            except ValueError:
                continue
        return None
