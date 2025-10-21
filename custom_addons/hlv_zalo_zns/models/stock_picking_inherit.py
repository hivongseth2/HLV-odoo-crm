import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

def _vn_msisdn(phone_raw: str) -> str:
    if not phone_raw:
        return ""
    p = phone_raw.replace(" ", "").replace("-", "")
    if p.startswith("+84"):
        return p
    if p.startswith("84") and len(p) >= 10:
        return "+" + p
    if p.startswith("0") and len(p) >= 10:
        return "+84" + p[1:]
    return p

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _zns_get_shipping_partner(self):
        """Ưu tiên partner_shipping_id của SO; không có thì lấy partner_id type=delivery; cuối cùng fallback partner_id."""
        self.ensure_one()
        # tìm SO theo origin
        so = None
        if self.origin:
            so = self.env['sale.order'].sudo().search([('name', '=', self.origin)], limit=1)

        if so and so.partner_shipping_id:
            return so.partner_shipping_id

        if self.partner_id:
            if getattr(self.partner_id, 'type', False) == 'delivery':
                return self.partner_id
            child_delivery = self.partner_id.child_ids.filtered(lambda p: getattr(p, 'type', False) == 'delivery')
            if child_delivery:
                return child_delivery[0]
        return self.partner_id

    def action_done(self):
        res = super().action_done()

        for picking in self:
            try:
                config = self.env['hlv.zalo.zns'].sudo().search([], limit=1)
                if not config or not config.template_id:
                    continue

                # chỉ gửi khi xuất hàng
                if getattr(picking, "picking_type_code", "") and picking.picking_type_code != "outgoing":
                    continue

                ship_partner = picking._zns_get_shipping_partner()
                if not ship_partner:
                    _logger.info("ZNS skip: no shipping partner for %s", picking.name)
                    continue

                # địa chỉ: chỉ lấy street theo yêu cầu
                shipping_street = ship_partner.street or ""

                # số ĐH: ưu tiên SO
                so = None
                if picking.origin:
                    so = self.env['sale.order'].sudo().search([('name', '=', picking.origin)], limit=1)
                order_code = so.name if so else picking.name

                # số điện thoại
                msisdn = _vn_msisdn(ship_partner.mobile or ship_partner.phone or "")

                # giá: lấy tổng tiền từ SO nếu có
                price_value = float(so.amount_total) if so else 0.0

                # ngày dạng dd/MM/YYYY (đúng theo template ảnh)
                date_str = fields.Date.context_today(self).strftime("%d/%m/%Y")

                # ---- map đúng key theo template của anh ----
                params = {
                    "name": ship_partner.name or "",
                    "order_code": order_code,
                    "phone_number": msisdn.replace("+84", "0") if msisdn.startswith("+84") else msisdn,  # nếu template muốn số 0xxx
                    "price": price_value,
                    "status": "Đã lấy hàng",
                    "date": date_str,
                    # nếu sau này cần địa chỉ:
                    # "address": shipping_street,
                }

                if not msisdn:
                    _logger.info("ZNS skip: empty phone for %s", picking.name)
                    continue

                config.sudo().send_zns(msisdn, params)

            except Exception as e:
                _logger.exception("Error sending ZNS on picking %s: %s", picking.name, e)

        return res
