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

    # ---- Tìm SO gốc cho phiếu (ưu tiên group → origin → sale_line) ----
    def _zns_resolve_sale_order(self):
        self.ensure_one()
        so = False
        if self.group_id and getattr(self.group_id, "sale_id", False):
            so = self.group_id.sale_id
        if not so and self.origin:
            so = self.env['sale.order'].sudo().search([('name', '=', self.origin)], limit=1)
        if not so:
            so = self.mapped('move_lines.sale_line_id.order_id')[:1] or False
        return so

    # ---- Lấy partner giao hàng (từ SO nếu có) ----
    def _zns_get_shipping_partner(self):
        self.ensure_one()
        so = self._zns_resolve_sale_order()
        if so and so.partner_shipping_id:
            return so.partner_shipping_id
        if self.partner_id:
            if getattr(self.partner_id, 'type', False) == 'delivery':
                return self.partner_id
            child_delivery = self.partner_id.child_ids.filtered(lambda p: getattr(p, 'type', False) == 'delivery')
            if child_delivery:
                return child_delivery[0]
        return self.partner_id

    # ---- Gửi cho 1 picking (PICK hoặc OUT) ----
    def _zns_send_for_picking(self, picking):
        config = self.env['hlv.zalo.zns'].sudo().search([], limit=1)
        if not config:
            _logger.info("ZNS skip: no config record")
            return
        if not config.template_id:
            _logger.info("ZNS skip: missing template_id")
            return

        # xác định loại: PICK (internal) hay OUT (outgoing)
        seq_code = (picking.picking_type_id and picking.picking_type_id.sequence_code) or ""
        is_pick = (seq_code == "PICK") or ("/PICK/" in (picking.name or ""))
        is_out = (picking.picking_type_code == "outgoing")

        if not (is_pick or is_out):
            _logger.info("ZNS skip: picking %s type=%s seq=%s (not PICK/OUT)",
                         picking.name, picking.picking_type_code, seq_code)
            return

        ship_partner = picking._zns_get_shipping_partner()
        if not ship_partner:
            _logger.info("ZNS skip: no shipping partner for %s", picking.name)
            return

        # chỉ lấy street theo yêu cầu
        shipping_street = ship_partner.street or ""

        # số đơn: ưu tiên SO, fallback picking
        so = picking._zns_resolve_sale_order()
        order_code = so.name if so else picking.name

        # số điện thoại
        msisdn = _vn_msisdn(ship_partner.mobile or ship_partner.phone or "")
        if not msisdn:
            _logger.info("ZNS skip: empty phone for %s", picking.name)
            return

        # price từ SO nếu có
        price_value = float(so.amount_total) if so else 0.0

        # status theo loại
        status_text = "Đã chuẩn bị hàng" if is_pick else "Đã lấy hàng"

        date_str = fields.Date.context_today(self).strftime("%d/%m/%Y")

        params = {
            "name": ship_partner.name or "",
            "order_code": order_code,
            "phone_number": msisdn.replace("+84", "0") if msisdn.startswith("+84") else msisdn,
            "price": price_value,
            "status": status_text,
            "date": date_str,
            # "address": shipping_street,  # mở nếu template có param address
        }

        _logger.info("ZNS send try: %s (%s/%s) to=%s params=%s",
                     picking.name, picking.picking_type_code, seq_code, msisdn, params)
        try:
            resp = config.sudo().send_zns(msisdn, params)
            _logger.info("ZNS sent OK: %s resp=%s", picking.name, resp)
        except Exception as e:
            _logger.exception("ZNS send ERROR on %s: %s", picking.name, e)

    # --- Gắn vào button_validate để chắc chắn chạy ---
    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            # chỉ gửi khi đã done
            if picking.state == 'done':
                picking._zns_send_for_picking(picking)
            else:
                _logger.info("ZNS skip: %s state=%s (after validate)", picking.name, picking.state)
        return res
