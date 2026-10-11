# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.sale_zalo import ZALO_PARAM
from .purchase_order import VENDOR_ORDER_STATES_PARAM
from .purchase_order_revision import NO_REVISION_STATES, REVISION_STATES_PARAM
from .vendor_quote_access import REQUIRE_PASSWORD_PARAM

# Đuôi tên ô tick → state của purchase.order (VENDOR_ORDER_STATES).
STATE_SUFFIXES = {"draft": "draft", "sent": "sent", "to_approve": "to approve", "purchase": "purchase", "done": "done"}
# Hai nhóm ô tick theo trạng thái đơn mua, mỗi nhóm lưu một tham số "draft,sent,…":
# tiền tố tên ô → (tham số, hàm đọc trạng thái đang dùng trên purchase.order, lỗi khi không tick gì — None = cho phép).
STATE_GROUPS = {
    "hlv_vq_order_state_": (VENDOR_ORDER_STATES_PARAM, "_hlv_vendor_visible_states",
                            "Chọn ít nhất một trạng thái đơn mua hiện trên trang NCC."),
    "hlv_vq_revision_state_": (REVISION_STATES_PARAM, "_hlv_revision_states", None),
}


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_vq_require_password = fields.Boolean(
        string="NCC nhập mật khẩu khi mở link báo giá",
        config_parameter=REQUIRE_PASSWORD_PARAM,
    )
    hlv_vq_zalo_notify_sale = fields.Boolean(
        string="Báo sale qua Zalo khi NCC có thay đổi",
        config_parameter=ZALO_PARAM,
    )
    # Đơn ở trạng thái nào hiện trên trang NCC (VENDOR_ORDER_STATES_PARAM).
    hlv_vq_order_state_draft = fields.Boolean(string="Nháp")
    hlv_vq_order_state_sent = fields.Boolean(string="RFQ đã gửi")
    hlv_vq_order_state_to_approve = fields.Boolean(string="Chờ duyệt")
    hlv_vq_order_state_purchase = fields.Boolean(string="Đơn mua hàng")
    hlv_vq_order_state_done = fields.Boolean(string="Đã khóa")
    # NCC đổi SL / giá trên đơn ở trạng thái nào thì tạo phiên bản chờ thu mua duyệt (REVISION_STATES_PARAM).
    hlv_vq_revision_state_draft = fields.Boolean(string="Nháp", default=True)
    hlv_vq_revision_state_sent = fields.Boolean(string="RFQ đã gửi", default=True)
    hlv_vq_revision_state_to_approve = fields.Boolean(string="Chờ duyệt", default=True)
    hlv_vq_revision_state_purchase = fields.Boolean(string="Đơn mua hàng", default=True)
    hlv_vq_revision_state_done = fields.Boolean(string="Đã khóa", default=True)

    def get_values(self):
        res = super().get_values()
        Order = self.env["purchase.order"]
        for prefix, (_param, reader, _error) in STATE_GROUPS.items():
            current = getattr(Order, reader)()
            res.update({prefix + suffix: state in current for suffix, state in STATE_SUFFIXES.items()})
        return res

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        for prefix, (param, _reader, error) in STATE_GROUPS.items():
            states = [state for suffix, state in STATE_SUFFIXES.items() if self[prefix + suffix]]
            if not states and error:
                raise UserError(_(error))
            # Lưu rỗng thì Odoo xoá tham số và quay về mặc định — bỏ tick hết (được phép) lưu dấu "none".
            params.set_param(param, ",".join(states) or NO_REVISION_STATES)
