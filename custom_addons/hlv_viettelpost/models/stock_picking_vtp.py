import logging
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_vtp_create_order(self):
        self.ensure_one()
        if not self.carrier_id or self.carrier_id.delivery_type != "vtp":
            raise UserError(_("Phiếu này không dùng Viettel Post."))

        # gọi hàm gửi hàng chuẩn (đã có trong delivery_vtp.py)
        res = self.carrier_id.send_shipping(self)
        # send_shipping có thể trả list; chuẩn hoá một chút
        if isinstance(res, list) and res:
            tracking = res[0].get("tracking_number")
        else:
            tracking = res.get("tracking_number") if isinstance(res, dict) else None

        msg = _("Đã tạo vận đơn Viettel Post.")
        if tracking:
            msg = _("Đã tạo vận đơn Viettel Post: <b>%s</b>") % tracking
        self.message_post(body=msg)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Viettel Post"), "message": msg, "type": "success"},
        }
