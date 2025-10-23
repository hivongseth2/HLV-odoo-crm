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
        _logger.info("[VTP] BẮT ĐẦU TẠO ĐƠN CHO PICKING %s", self.name)
        res = self.carrier_id.send_shipping(self)
        _logger.info("[VTP] Kết quả send_shipping: %s", res)
        tracking = None
        if isinstance(res, list) and res:
            tracking = res[0].get("tracking_number")
        elif isinstance(res, dict):
            tracking = res.get("tracking_number")
        if not tracking:
            raise UserError(_("Không nhận được mã vận đơn từ Viettel Post. Kiểm tra cấu hình và log."))
        self.carrier_tracking_ref = tracking
        self.message_post(body=_("Đã tạo vận đơn Viettel Post: <b>%s</b>") % tracking)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Viettel Post"), "message": _("Đã tạo vận đơn Viettel Post."), "type": "success"},
        }
