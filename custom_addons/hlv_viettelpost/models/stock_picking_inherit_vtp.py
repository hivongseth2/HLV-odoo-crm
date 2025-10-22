import logging
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_vtp_create_order(self):
        for picking in self:
            carrier = picking.carrier_id
            if carrier.delivery_type != "vtp":
                raise UserError(_("Phiếu này không dùng Viettel Post."))

            token = self.env["ir.config_parameter"].sudo().get_param("vtp.token")
            if not token:
                raise UserError(_("Chưa có token VTP. Vào Cài đặt → Viettel Post → 'Login & Get Token'."))

            api = self.env["vtp.api"]
            base = self.env["ir.config_parameter"].sudo().get_param("vtp.api_base")
            if not base:
                raise UserError(_("Chưa cấu hình vtp_api_base trong Settings."))

            partner = picking.partner_id
            if not partner:
                raise UserError(_("Chưa có người nhận."))

            # --- Payload cơ bản cho Viettel Post ---
            order_data = {
                "ORDER_NUMBER": picking.name,
                "SENDER_FULLNAME": self.env["ir.config_parameter"].sudo().get_param("vtp.shop_name") or "Shop",
                "SENDER_ADDRESS": self.env["ir.config_parameter"].sudo().get_param("vtp.shop_address") or "",
                "SENDER_PHONE": self.env["ir.config_parameter"].sudo().get_param("vtp.shop_phone") or "",
                "RECEIVER_FULLNAME": partner.name,
                "RECEIVER_ADDRESS": partner.street or "",
                "RECEIVER_PHONE": partner.phone or partner.mobile or "",
                "RECEIVER_PROVINCE": partner.state_id.name if partner.state_id else "",
                "RECEIVER_DISTRICT": partner.city or "",
                "RECEIVER_WARD": partner.x_vtp_ward_code if hasattr(partner, "x_vtp_ward_code") else "",
                "PRODUCT_NAME": ", ".join(picking.move_ids_without_package.mapped("product_id.name")),
                "PRODUCT_WEIGHT": picking.shipping_weight or 500,  # gram
                "PRODUCT_PRICE": picking.sale_id.amount_total if picking.sale_id else 0,
                "MONEY_COLLECTION": carrier.vtp_cod and (picking.sale_id.amount_total or 0) or 0,
                "PRODUCT_TYPE": "HH",
                "SERVICE_CODE": carrier.vtp_service_code or "VCN",
            }

            # --- Gửi request tạo đơn ---
            result = api.vtp_post("/order/createOrder", order_data)
            if not result or not result.get("data"):
                raise UserError(_("Tạo vận đơn thất bại. API không trả dữ liệu."))

            data = result.get("data")
            order_number = data.get("ORDER_NUMBER") or data.get("ORDER_CODE")
            if not order_number:
                raise UserError(_("Không nhận được mã vận đơn từ API."))

            picking.carrier_tracking_ref = order_number
            picking.message_post(
                body=_("Đã tạo vận đơn Viettel Post: <b>%s</b>") % order_number
            )
            _logger.info("VTP Created: %s -> %s", picking.name, order_number)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Viettel Post"),
                "message": _("Đã tạo vận đơn Viettel Post thành công."),
                "type": "success",
            },
        }
