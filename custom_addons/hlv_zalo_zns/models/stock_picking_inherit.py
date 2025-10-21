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

    def _zns_send_for_picking(self, picking):
        """Gửi ZNS cho 1 phiếu và log đầy đủ để debug."""
        config = self.env['hlv.zalo.zns'].sudo().search([], limit=1)
        if not config:
            _logger.info("ZNS skip: no config record")
            return
        if not config.template_id:
            _logger.info("ZNS skip: missing template_id")
            return

        # chỉ gửi khi là xuất hàng
        if getattr(picking, "picking_type_code", "") != "outgoing":
            _logger.info("ZNS skip: picking %s is not outgoing (type=%s)", picking.name, picking.picking_type_code)
            return

        ship_partner = picking._zns_get_shipping_partner()
        if not ship_partner:
            _logger.info("ZNS skip: no shipping partner for %s", picking.name)
            return

        # địa chỉ: chỉ lấy street như yêu cầu
        shipping_street = ship_partner.street or ""

        # mã đơn: ưu tiên SO, fallback picking
        so = None
        if picking.origin:
            so = self.env['sale.order'].sudo().search([('name', '=', picking.origin)], limit=1)
        order_code = so.name if so else picking.name

        # số điện thoại
        msisdn = _vn_msisdn(ship_partner.mobile or ship_partner.phone or "")
        if not msisdn:
            _logger.info("ZNS skip: empty phone for %s", picking.name)
            return

        # price lấy từ SO nếu có
        price_value = float(so.amount_total) if so else 0.0

        date_str = fields.Date.context_today(self).strftime("%d/%m/%Y")

        # Map theo template anh đã gửi ảnh
        params = {
            "name": ship_partner.name or "",
            "order_code": order_code,
            "phone_number": msisdn.replace("+84", "0") if msisdn.startswith("+84") else msisdn,
            "price": price_value,
            "status": "Đã lấy hàng",
            "date": date_str,
            # Nếu sau này template thêm địa chỉ:
            # "address": shipping_street,
        }

        _logger.info("ZNS send try: picking=%s, to=%s, params=%s", picking.name, msisdn, params)
        try:
            resp = config.sudo().send_zns(msisdn, params)
            _logger.info("ZNS sent OK: picking=%s, response=%s", picking.name, resp)
        except Exception as e:
            _logger.exception("ZNS send ERROR on %s: %s", picking.name, e)

    # --- Gắn vào luồng validate ---
    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            # chỉ gửi nếu đã DONE sau validate
            if picking.state == 'done':
                self._zns_send_for_picking(picking)
            else:
                _logger.info("ZNS skip: picking %s state after validate = %s", picking.name, picking.state)
        return res
