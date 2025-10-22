import math
from odoo import models, fields, api

class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(selection_add=[("vtp", "Viettel Post")], ondelete={"vtp": "set default"}, )
    vtp_service_code = fields.Char("VTP Service Code")
    vtp_cod = fields.Boolean("Thu hộ COD", default=False)

    def rate_shipment(self, order):
        self.ensure_one()
        if self.delivery_type != "vtp":
            return super().rate_shipment(order)

        api = self.env["vtp.api"]
        # Weight in grams, minimum 200g
        weight_grams = max(200, math.ceil((order._get_estimated_weight() or 0) * 1000))
        ICP = self.env["ir.config_parameter"].sudo()
        payload = {
            "SENDER_PROVINCE": ICP.get_param("vtp.shop_province_code") or "",
            "SENDER_DISTRICT": ICP.get_param("vtp.shop_district_code") or "",
            "SENDER_WARD": ICP.get_param("vtp.shop_ward_code") or "",
            "RECEIVER_PROVINCE": (order.partner_shipping_id.state_id and order.partner_shipping_id.state_id.name) or "",
            "RECEIVER_DISTRICT": order.partner_shipping_id.city or "",
            "RECEIVER_WARD": getattr(order.partner_shipping_id, "x_vtp_ward_code", "") or "",
            "WEIGHT": int(weight_grams),
            "SERVICE_CODE": self.vtp_service_code or "",
            "MONEY_COLLECTION": order.amount_total if self.vtp_cod else 0,
        }
        res = api.vtp_calculate_fee(payload)
        price = float((res.get("data") or {}).get("TOTAL_FEE", 0.0))
        return {
            "success": True,
            "price": price,
            "error_message": False,
            "warning_message": False,
        }

    def send_shipping(self, pickings):
        res = []
        api = self.env["vtp.api"]
        ICP = self.env["ir.config_parameter"].sudo()
        for picking in pickings:
            partner = picking.partner_id
            weight_grams = max(
                200,
                int(sum(m.product_uom_qty * (m.product_id.weight or 0) * 1000 for m in picking.move_ids_without_package))
            )
            payload = {
                "SENDER_NAME": self.env.user.company_id.name,
                "SENDER_PHONE": ICP.get_param("vtp.shop_phone") or "",
                "SENDER_ADDRESS": ICP.get_param("vtp.shop_address") or "",
                "SENDER_WARD": ICP.get_param("vtp.shop_ward_code") or "",
                "SENDER_DISTRICT": ICP.get_param("vtp.shop_district_code") or "",
                "RECEIVER_NAME": partner.name,
                "RECEIVER_PHONE": partner.phone or partner.mobile or "",
                "RECEIVER_ADDRESS": partner.contact_address or partner.street or "",
                "RECEIVER_WARD": getattr(partner, "x_vtp_ward_code", "") or "",
                "RECEIVER_DISTRICT": getattr(partner, "x_vtp_district_code", "") or "",
                "SERVICE_CODE": self.vtp_service_code or "",
                "PRODUCT_NAME": picking.origin or picking.name,
                "WEIGHT": weight_grams,
                "MONEY_COLLECTION": picking.sale_id.amount_total if self.vtp_cod else 0,
                "ORDER_NOTE": picking.note or "",
            }
            data = api.vtp_create_order(payload)
            vtp_code = (data.get("data") or {}).get("ORDER_NUMBER") or data.get("ORDER_NUMBER")
            if not vtp_code:
                raise ValueError(f"Không nhận được mã vận đơn từ VTP: {data}")
            picking.carrier_tracking_ref = vtp_code
            picking.message_post(body=f"Đã tạo vận đơn Viettel Post: {vtp_code}")
            res.append({'exact_price': 0.0, 'tracking_number': vtp_code})
        return res

    def cancel_shipment(self, picking):
        if self.delivery_type != "vtp":
            return super().cancel_shipment(picking)
        api = self.env["vtp.api"]
        if picking.carrier_tracking_ref:
            api.vtp_cancel_order(picking.carrier_tracking_ref, note="Cancel from Odoo")
            picking.message_post(body="Đã yêu cầu hủy vận đơn Viettel Post")
        return True
