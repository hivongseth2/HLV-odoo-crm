# models/stock_picking_inherit.py
import logging
from odoo import models, fields
from urllib.parse import quote

_logger = logging.getLogger(__name__)

def _vn_msisdn(phone_raw: str) -> str:
    """Chuẩn hoá số VN về +84, giữ nguyên quốc tế khác."""
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

    # Cờ chống gửi trùng (không copy sang phiếu khác)
    zns_sent = fields.Boolean(string="ZNS Sent", default=False, copy=False)

    # ---- Tìm SO gốc cho phiếu (ưu tiên group → origin → sale_line) ----
    def _zns_resolve_sale_order(self):
        self.ensure_one()
        so = False
        if self.group_id and getattr(self.group_id, "sale_id", False):
            so = self.group_id.sale_id
        if not so and self.origin:
            so = self.env['sale.order'].sudo().search([('name', '=', self.origin)], limit=1)
        if not so:
            so_rs = self.mapped('move_ids_without_package.sale_line_id.order_id')
            so = so_rs[:1] if so_rs else False
        return so

    def _zns_resolve_purchase_order(self):
        self.ensure_one()
        po_rs = self.mapped('move_ids_without_package.purchase_line_id.order_id')
        return po_rs[:1] if po_rs else False

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

    # ---- Gửi ZNS cho phiếu OUT ----
    def _zns_send_for_out_picking(self, picking):
    # Chỉ gửi khi là OUT & chưa gửi trước đó
        if getattr(picking, "picking_type_code", "") != "outgoing":
            _logger.info("ZNS skip: %s is not outgoing (type=%s)", picking.name, picking.picking_type_code)
            return
        if picking.zns_sent:
            _logger.info("ZNS skip: %s already sent (zns_sent=True)", picking.name)
            return

        # Lấy SO và kiểm tra cờ x_studio_zns
        so = picking._zns_resolve_sale_order()
        if not so:
            _logger.info("ZNS skip: %s has no related sale order", picking.name)
            return
        if not bool(so.sudo().x_studio_zns):
            _logger.info("ZNS skip: SO %s has x_studio_zns=False", so.name)
            return

        config = self.env['hlv.zalo.zns'].sudo().search([], limit=1)
        if not config:
            _logger.info("ZNS skip: no config record")
            return
        if not config.template_id:
            _logger.info("ZNS skip: missing template_id")
            return

        ship_partner = picking._zns_get_shipping_partner()
        if not ship_partner:
            _logger.info("ZNS skip: no shipping partner for %s", picking.name)
            return

        order_code = so.name
        shipping_fee = so.x_studio_misa_delivery or ""
        msisdn = _vn_msisdn(ship_partner.mobile or ship_partner.phone or "")
        if not msisdn:
            _logger.info("ZNS skip: empty phone for %s", picking.name)
            return

        amount = float(so.amount_total) if so else 0.0
        price_value = int(round(amount))
        date_str = fields.Date.context_today(self).strftime("%d/%m/%Y")
        id_encoded = quote(str(so.id), safe="")  # encode UTF-8 theo yêu cầu Zalo

        params = {
            "name": ship_partner.name or "",
            "order_code": order_code,
            "phone_number": msisdn.replace("+84", "0") if msisdn.startswith("+84") else msisdn,
            "price": price_value,
            "status": "Đang giao hàng",
            "date": date_str,
            "id": id_encoded,
            "address":ship_partner.street or "",
            "shipping_fee":shipping_fee or "Không có thông tin"
        }

        _logger.info("ZNS send try (OUT): %s to=%s params=%s", picking.name, msisdn, params)
        try:
            resp = config.sudo().send_zns(msisdn, params)
            _logger.info("ZNS sent OK: %s resp=%s", picking.name, resp)
            picking.sudo().write({"zns_sent": True})
        except Exception as e:
            _logger.exception("ZNS send ERROR on %s: %s", picking.name, e)


    # ---- Gắn vào button_validate để chắc chắn chạy ----
    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            # Chỉ khi đã DONE và là OUT
            if picking.state == 'done' and picking.picking_type_code == 'outgoing':
                picking._zns_send_for_out_picking(picking)
            else:
                _logger.info(
                    "ZNS skip after validate: %s state=%s type=%s",
                    picking.name, picking.state, picking.picking_type_code
                )
        return res
