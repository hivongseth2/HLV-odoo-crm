# -*- coding: utf-8 -*-
import json
import time
import hashlib
import hmac
import logging

import requests as req_lib

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _generate_sign(self, partner_id, api_path, timestamp, access_token, shop_id, partner_key):
        """Tạo HMAC-SHA256 sign theo spec Shopee Open API v2."""
        base_string = f"{partner_id}{api_path}{timestamp}{access_token}{shop_id}"
        sign = hmac.new(
            partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return sign

    def _get_shopee_shop_credentials(self):
        """Đọc credentials từ shopee_shop_id trên đơn hàng."""
        self.ensure_one()
        shop = self.shopee_shop_id
        if not shop:
            raise UserError(_("Đơn hàng '%s' chưa được liên kết với Shop Shopee.") % self.name)

        access_token = getattr(shop, 'access_token', False)
        shop_identifier = getattr(shop, 'shop_identifier', False)

        account = getattr(shop, 'account_id', False)
        if not account:
            raise UserError(_("Shop '%s' chưa được liên kết với Shopee Account.") % shop.display_name)

        partner_id = getattr(account, 'partner_identifier', False)
        partner_key = getattr(account, 'partner_key', False)

        missing = []
        if not partner_id:
            missing.append('partner_identifier (Shopee Account)')
        if not partner_key:
            missing.append('partner_key (Shopee Account)')
        if not access_token:
            missing.append('access_token (Shopee Shop)')
        if not shop_identifier:
            missing.append('shop_identifier (Shopee Shop)')
        if missing:
            raise UserError(
                _("Thiếu thông tin cấu hình:\n%s") % '\n'.join(f"- {m}" for m in missing)
            )

        return {
            'partner_id': partner_id,
            'partner_key': partner_key,
            'access_token': access_token,
            'shop_identifier': shop_identifier,
        }

    def _call_escrow_api_direct(self, creds, order_sn):
        """Gọi Shopee get_escrow_detail API để lấy thông tin thanh toán chi tiết."""
        api_path = '/api/v2/payment/get_escrow_detail'
        ts = int(time.time())
        sign = self._generate_sign(
            creds['partner_id'], api_path, ts,
            creds['access_token'], creds['shop_identifier'],
            creds['partner_key'],
        )

        params = {
            'partner_id': creds['partner_id'],
            'timestamp': ts,
            'access_token': creds['access_token'],
            'shop_id': creds['shop_identifier'],
            'sign': sign,
            'order_sn': order_sn,
        }

        _logger.info("Shopee API get_escrow_detail – order_sn=%s", order_sn)

        try:
            resp = req_lib.get(
                f"https://partner.shopeemobile.com{api_path}",
                params=params, timeout=30,
            )
            body = resp.json()
        except Exception as e:
            raise UserError(_("Lỗi gọi Shopee Escrow API cho %s:\n%s") % (order_sn, str(e)))

        if body.get('error'):
            raise UserError(
                _("Shopee Escrow API lỗi cho %s:\n%s - %s")
                % (order_sn, body.get('error'), body.get('message'))
            )

        return body.get('response', {})

    def _get_tax_included_for_shopee(self, company):
        """Tìm thuế bán hàng có price_include=True."""
        Tax = self.env['account.tax'].sudo()
        tax = Tax.search([
            ('type_tax_use', '=', 'sale'),
            ('price_include', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)
        if tax:
            return tax

        default_tax = company.account_sale_tax_id
        if default_tax:
            tax = Tax.search([
                ('type_tax_use', '=', 'sale'),
                ('price_include', '=', True),
                ('amount', '=', default_tax.amount),
                ('company_id', '=', company.id),
            ], limit=1)
            if tax:
                return tax
        return False

    def _update_lines_from_escrow_items(self, escrow_data):
        """Cập nhật giá và chiết khấu cho các sale.order.line từ escrow items."""
        self.ensure_one()
        order_income = escrow_data.get('order_income', {})
        item_list = order_income.get('items', [])

        for item_data in item_list:
            model_sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')
            if not model_sku:
                continue

            line = self.order_line.filtered(lambda l: l.product_id.default_code == model_sku)
            if not line:
                continue

            original_price = item_data.get('original_price', 0)
            discounted_price = item_data.get('discounted_price', 0)

            discount = 0.0
            if original_price and discounted_price and original_price > 0:
                discount = (original_price - discounted_price) / original_price * 100.0

            line_vals = {
                'price_unit': original_price,
                'discount': discount,
            }

            tax_included = self._get_tax_included_for_shopee(self.company_id)
            if tax_included:
                line_vals['tax_id'] = [(6, 0, tax_included.ids)]

            line.sudo().write(line_vals)
            _logger.info(
                "Shopee: Đã update giá dòng %s: price=%s, discount=%s%%",
                model_sku, original_price, discount,
            )

    def _apply_escrow_voucher_direct(self, escrow_data):
        """Áp dụng voucher của Shop từ escrow response."""
        self.ensure_one()
        order_income = escrow_data.get('order_income', {})
        seller_voucher = order_income.get('voucher_from_seller', 0)

        if not seller_voucher:
            buyer_payment = escrow_data.get('buyer_payment_info', {})
            seller_voucher = abs(buyer_payment.get('seller_voucher', 0))

        total_voucher = abs(seller_voucher)

        if total_voucher <= 0:
            return

        lines = self.order_line.filtered(lambda l: not l.display_type and l.price_unit > 0)
        if not lines:
            return

        total_before_voucher = sum(
            l.price_unit * l.product_uom_qty * (1 - l.discount / 100.0)
            for l in lines
        )

        if total_before_voucher <= 0:
            return

        voucher_distributed = 0.0
        lines_list = list(lines)

        for i, line in enumerate(lines_list):
            line_total = line.price_unit * line.product_uom_qty
            if line_total <= 0:
                continue

            line_subtotal_before = line_total * (1 - line.discount / 100.0)

            if i < len(lines_list) - 1:
                line_voucher_share = (line_subtotal_before / total_before_voucher) * total_voucher
            else:
                line_voucher_share = total_voucher - voucher_distributed

            voucher_distributed += line_voucher_share

            new_subtotal = line_subtotal_before - line_voucher_share
            if new_subtotal < 0:
                new_subtotal = 0.0

            new_discount = (1 - new_subtotal / line_total) * 100.0
            line.sudo().write({'discount': new_discount})

        _logger.info(
            "Shopee: Đã áp dụng voucher -%s vào discount các dòng của đơn %s",
            total_voucher, self.name,
        )

    def action_update_price_from_escrow(self):
        """Gọi Shopee API get_escrow_detail để cập nhật lại giá cho đơn hàng hiện tại."""
        for order in self:
            if not order.shopee_order_ref:
                raise UserError(
                    _("Đơn hàng '%s' không có mã tham chiếu Shopee (shopee_order_ref).")
                    % order.name
                )

            creds = order._get_shopee_shop_credentials()
            escrow_data = order._call_escrow_api_direct(creds, order.shopee_order_ref)

            if escrow_data and escrow_data.get('order_income', {}).get('items'):
                order._update_lines_from_escrow_items(escrow_data)

            if escrow_data:
                order._apply_escrow_voucher_direct(escrow_data)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Cập nhật giá Shopee"),
                'message': _("Đã cập nhật giá từ Escrow thành công cho %d đơn hàng.") % len(self),
                'type': 'success',
                'sticky': False,
            },
        }
