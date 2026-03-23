# -*- coding: utf-8 -*-
"""
wizard/shopee_order_fetch_wizard.py

Wizard UI để lấy thông tin đơn hàng Shopee và tạo Sale Order.
File này chỉ chứa fields + action methods; toàn bộ logic
được ủy thác cho services/shopee_api.py và services/shopee_order_builder.py.
"""
import json
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_api, shopee_escrow, shopee_order_builder

_logger = logging.getLogger(__name__)


class ShopeeOrderFetchWizard(models.TransientModel):
    _name = 'shopee.order.fetch.wizard'
    _description = 'Lấy thông tin đơn hàng Shopee qua API'

    # ──────────────────────────────────────────────────
    #  Fields
    # ──────────────────────────────────────────────────

    shop_id = fields.Many2one(
        'shopee.shop',
        string='Shop Shopee',
        required=False,
        help="Chọn shop Shopee để lấy access_token và shop_identifier.",
    )
    order_sn_list = fields.Text(
        string='Mã đơn hàng Shopee',
        required=False,
        help="Nhập mã đơn hàng Shopee, mỗi dòng 1 mã hoặc cách nhau bởi dấu phẩy. Tối đa 50 đơn.",
    )
    response_optional_fields = fields.Char(
        string='Response Optional Fields',
        default=shopee_api.DEFAULT_OPTIONAL_FIELDS,
        help="Các trường tùy chọn muốn lấy từ Shopee API, cách nhau bởi dấu phẩy.",
    )
    result_display = fields.Text(
        string='Kết quả API',
        readonly=True,
    )

    # ── Fields dùng cho test mock (đã comment để production) ──
    mock_json = fields.Text(
        string='Mock JSON - Order Detail',
        help="Dán JSON response từ Shopee get_order_detail API vào đây để test tạo đơn.",
    )
    mock_escrow_json = fields.Text(
        string='Mock JSON - Escrow Detail',
        help="Dán JSON response từ Shopee get_escrow_detail API vào đây để áp dụng voucher.",
    )
    sale_order_ids = fields.Many2many(
        'sale.order',
        string='Mã đơn Odoo (thủ công)',
        help="Chọn các đơn Odoo tương ứng với các mã Shopee ở trên (theo thứ tự từ trên xuống)."
    )

    # ──────────────────────────────────────────────────
    #  Helpers nội bộ của Wizard
    # ──────────────────────────────────────────────────

    def _parse_order_sn_list(self):
        """Parse order SN list từ input text (hỗ trợ nhiều dòng hoặc dấu phẩy)."""
        self.ensure_one()
        raw = self.order_sn_list or ''
        sns = []
        for line in raw.replace('\r', '').split('\n'):
            for sn in line.split(','):
                sn = sn.strip()
                if sn:
                    sns.append(sn)
        if not sns:
            raise UserError(_("Vui lòng nhập ít nhất 1 mã đơn hàng Shopee."))
        if len(sns) > 50:
            raise UserError(_("Shopee API chỉ hỗ trợ tối đa 50 đơn hàng mỗi lần gọi."))
        return sns

    def _return_self(self):
        """Trả về action mở lại wizard hiện tại (dùng để hiển thị kết quả)."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ──────────────────────────────────────────────────
    #  Actions
    # ──────────────────────────────────────────────────

    def action_fetch_order(self):
        """Gọi Shopee API get_order_detail và hiển thị kết quả. Không ghi DB."""
        self.ensure_one()
        creds = shopee_api.get_credentials_from_wizard(self)
        sns = self._parse_order_sn_list()
        status_code, body, params = shopee_api.call_order_detail(
            creds, ','.join(sns), self.response_optional_fields
        )

        result = {
            'shopee_http_status': status_code,
            'shopee_response': body,
            'request_params_sent': {k: v for k, v in params.items() if k != 'sign'},
        }
        self.result_display = json.dumps(result, indent=2, ensure_ascii=False)
        return self._return_self()

    def action_fetch_and_create_order(self):
        """Gọi Shopee API, sau đó tạo Sale Order từ response."""
        self.ensure_one()
        creds = shopee_api.get_credentials_from_wizard(self)
        sns = self._parse_order_sn_list()
        status_code, body, _params = shopee_api.call_order_detail(
            creds, ','.join(sns), self.response_optional_fields
        )

        if status_code != 200:
            raise UserError(
                _("Shopee API trả về lỗi (HTTP %s):\n%s")
                % (status_code, json.dumps(body, indent=2, ensure_ascii=False))
            )
        error_msg = body.get('error', '')
        if error_msg:
            raise UserError(
                _("Shopee API error: %s\n%s") % (error_msg, body.get('message', ''))
            )

        order_list = body.get('response', {}).get('order_list', [])
        if not order_list:
            raise UserError(_("Shopee API không trả về đơn hàng nào."))

        shop = self.shop_id
        created_orders = []
        skipped_orders = []

        for order_data in order_list:
            order_sn = order_data.get('order_sn', '')

            existing = self.env['sale.order'].sudo().search(
                [('shopee_order_ref', '=', order_sn)], limit=1
            )
            if existing:
                skipped_orders.append(f"{order_sn} (đã tồn tại: {existing.name})")
                continue

            try:
                with self.env.cr.savepoint():
                    escrow_data = shopee_api.call_escrow_detail(creds, order_sn)
                    so = shopee_order_builder.create_order_from_data(
                        self.env, order_data, shop, escrow_data=escrow_data
                    )
                    created_orders.append(f"{order_sn} → {so.name}")
            except Exception as e:
                _logger.error("Shopee: Lỗi tạo đơn %s: %s", order_sn, str(e), exc_info=True)
                skipped_orders.append(f"{order_sn} (LỖI: {str(e)})")

        lines = []
        if created_orders:
            lines.append("ĐÃ TẠO:")
            lines.extend(f"  • {o}" for o in created_orders)
        if skipped_orders:
            lines.append("\nBỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)

        self.sudo().result_display = '\n'.join(lines)
        return self._return_self()

    # ── Actions đã comment để production ──────────────

    def action_update_price_from_escrow(self):
        """Cập nhật giá hàng loạt từ Escrow cho nhiều đơn theo mã. (Ẩn trên production)"""
        self.ensure_one()
        creds = shopee_api.get_credentials_from_wizard(self)
        sns = self._parse_order_sn_list()

        updated_orders = []
        skipped_orders = []
        # manual_orders = list(self.sale_order_ids)

        for order_sn in sns:
            so = self.env['sale.order'].sudo().search(
                [('shopee_order_ref', '=', order_sn)], limit=1
            )
            if not so:
                skipped_orders.append(f"{order_sn} (Không tìm thấy trong hệ thống)")
                continue

            escrow_data = shopee_api.call_escrow_detail(creds, order_sn)
            if not escrow_data:
                skipped_orders.append(f"{order_sn} (Không có dữ liệu Escrow)")
                continue

            if escrow_data.get('order_income', {}).get('items'):
                shopee_escrow.update_order_lines_from_escrow(so, escrow_data)
            shopee_escrow.apply_escrow_voucher(so, escrow_data)
            updated_orders.append(f"{order_sn} → Đã cập nhật giá")

        lines = []
        if updated_orders:
            lines.append("ĐÃ CẬP NHẬT GIÁ:")
            lines.extend(f"  • {o}" for o in updated_orders)
        if skipped_orders:
            lines.append("\nBỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)

        self.sudo().result_display = '\n'.join(lines)
        return self._return_self()

    def action_test_create_order(self):
        """Tạo đơn hàng từ mock JSON (dùng cho staging test). (Ẩn trên production)"""
        self.ensure_one()
        if not self.mock_json:
            raise UserError(_("Vui lòng cung cấp Mock JSON (Order Detail)."))

        try:
            raw = json.loads(self.mock_json)
        except json.JSONDecodeError as e:
            raise UserError(_("Order Detail JSON không hợp lệ:\n%s") % str(e))

        # Hỗ trợ lấy order_list linh hoạt từ nhiều cấu trúc JSON khác nhau
        order_list = []
        if isinstance(raw, list):
            order_list = raw
        elif isinstance(raw, dict):
            # Dạng JSON lấy từ nút "Lấy dữ liệu" của wizard
            if 'shopee_response' in raw and isinstance(raw['shopee_response'], dict):
                inner = raw['shopee_response']
                if 'response' in inner and isinstance(inner['response'], dict) and 'order_list' in inner['response']:
                    order_list = inner['response']['order_list']
            # Dạng JSON chuẩn của Shopee
            elif 'response' in raw and isinstance(raw['response'], dict) and 'order_list' in raw['response']:
                order_list = raw['response']['order_list']
            # Dạng object chỉ có order_list
            elif 'order_list' in raw:
                order_list = raw['order_list']
            # Dạng object là 1 order detail duy nhất
            elif 'order_sn' in raw:
                order_list = [raw]

        if not order_list:
            raise UserError(_("Không tìm thấy order_list (hoặc order_sn) trong JSON."))

        escrow_data = None
        if self.mock_escrow_json:
            try:
                escrow_raw = json.loads(self.mock_escrow_json)
                if isinstance(escrow_raw, dict) and 'response' in escrow_raw:
                    escrow_data = escrow_raw['response']
                else:
                    escrow_data = escrow_raw
            except json.JSONDecodeError as e:
                _logger.warning("Escrow JSON parse error: %s", str(e))

        shop = self.shop_id
        created_orders = []
        skipped_orders = []

        for order_data in order_list:
            order_sn = order_data.get('order_sn', '')
            existing = self.env['sale.order'].sudo().search(
                [('shopee_order_ref', '=', order_sn)], limit=1
            )
            if existing:
                skipped_orders.append(f"{order_sn} (đã tồn tại: {existing.name})")
                continue
            try:
                with self.env.cr.savepoint():
                    so = shopee_order_builder.create_order_from_data(
                        self.env, order_data, shop, escrow_data=escrow_data
                    )
                    created_orders.append(f"{order_sn} → {so.name}")
            except Exception as e:
                _logger.error("Shopee Mock: Lỗi tạo đơn %s: %s", order_sn, str(e), exc_info=True)
                skipped_orders.append(f"{order_sn} (LỖI: {str(e)})")

        lines = ["KẾT QUẢ TEST (Mock Data):"]
        if created_orders:
            lines.append("\nĐÃ TẠO:")
            lines.extend(f"  • {o}" for o in created_orders)
        if skipped_orders:
            lines.append("\nBỎ QUA:")
            lines.extend(f"  • {o}" for o in skipped_orders)

        self.sudo().result_display = '\n'.join(lines)
        return self._return_self()
