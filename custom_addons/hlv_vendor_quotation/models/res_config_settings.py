# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from .purchase_order import VENDOR_ORDER_STATES_PARAM
from .vendor_quote_access import REQUIRE_PASSWORD_PARAM

# Ô tick "đơn ở trạng thái này hiện trên trang NCC" → state của purchase.order (VENDOR_ORDER_STATES).
ORDER_STATE_FIELDS = {
    "hlv_vq_order_state_draft": "draft",
    "hlv_vq_order_state_sent": "sent",
    "hlv_vq_order_state_to_approve": "to approve",
    "hlv_vq_order_state_purchase": "purchase",
    "hlv_vq_order_state_done": "done",
}


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_vq_require_password = fields.Boolean(
        string="NCC nhập mật khẩu khi mở link báo giá",
        config_parameter=REQUIRE_PASSWORD_PARAM,
    )
    # Lưu chung một tham số "draft,sent,..." (VENDOR_ORDER_STATES_PARAM) — xem get_values / set_values.
    hlv_vq_order_state_draft = fields.Boolean(string="Nháp")
    hlv_vq_order_state_sent = fields.Boolean(string="RFQ đã gửi")
    hlv_vq_order_state_to_approve = fields.Boolean(string="Chờ duyệt")
    hlv_vq_order_state_purchase = fields.Boolean(string="Đơn mua hàng")
    hlv_vq_order_state_done = fields.Boolean(string="Đã khóa")

    def get_values(self):
        res = super().get_values()
        visible = self.env["purchase.order"]._hlv_vendor_visible_states()
        res.update({name: state in visible for name, state in ORDER_STATE_FIELDS.items()})
        return res

    def set_values(self):
        super().set_values()
        states = [state for name, state in ORDER_STATE_FIELDS.items() if self[name]]
        if not states:
            # Không tick gì: lưu rỗng thì Odoo xoá tham số và quay về mặc định — báo rõ thay vì âm thầm.
            raise UserError(_("Chọn ít nhất một trạng thái đơn mua hiện trên trang NCC."))
        self.env["ir.config_parameter"].sudo().set_param(VENDOR_ORDER_STATES_PARAM, ",".join(states))
