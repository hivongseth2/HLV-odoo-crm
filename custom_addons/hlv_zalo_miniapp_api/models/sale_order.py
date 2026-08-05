# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả",
        default=False,
        tracking=True,
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả hàng",
    )

    x_return_state = fields.Selection(
        [
            ("pending", "Chờ duyệt"),
            ("approved", "Đã duyệt"),
            ("processing", "Đang xử lý"),
            ("completed", "Hoàn tất"),
            ("rejected", "Từ chối"),
        ],
        string="Trạng thái đổi/trả",
        default=False,
        tracking=True,
        help="Trạng thái xử lý yêu cầu đổi/trả (chỉ áp dụng cho đơn Zalo)",
    )

    x_return_type = fields.Selection(
        [
            ("return", "Trả hàng hoàn tiền"),
            ("exchange", "Đổi hàng"),
            ("refund", "Hoàn tiền một phần"),
        ],
        string="Loại đổi/trả",
        tracking=True,
        help="Phân loại yêu cầu đổi/trả (chỉ áp dụng cho đơn Zalo)",
    )

    x_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu trả hàng",
        tracking=True,
        help="Phiếu nhập kho trả hàng được tạo từ yêu cầu đổi/trả Zalo",
    )

    x_return_refund_amount = fields.Float(
        string="Số tiền hoàn lại",
        tracking=True,
        help="Số tiền sẽ hoàn lại cho khách (chỉ áp dụng cho đơn Zalo)",
    )

    x_return_rejected_reason = fields.Text(
        string="Lý do từ chối",
        tracking=True,
        help="Lý do từ chối yêu cầu đổi/trả (chỉ áp dụng cho đơn Zalo)",
    )

    x_return_completed_date = fields.Datetime(
        string="Ngày hoàn tất đổi/trả",
        tracking=True,
        help="Thời điểm hoàn tất xử lý đổi/trả",
    )

    def _is_zalo_order(self):
        """Kiểm tra đơn hàng có phải từ Zalo Mini App không."""
        self.ensure_one()
        return bool(self.partner_id.x_is_zalo_account)

    def action_approve_return(self):
        """Phê duyệt yêu cầu đổi/trả (chỉ cho đơn Zalo)."""
        self.ensure_one()
        if not self._is_zalo_order():
            raise UserError(_("Chức năng này chỉ áp dụng cho đơn hàng Zalo Mini App."))
        if not self.x_return_requested:
            raise UserError(_("Đơn hàng chưa có yêu cầu đổi/trả từ khách."))
        if self.x_return_state and self.x_return_state != "pending":
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % dict(self._fields['x_return_state'].selection).get(self.x_return_state, self.x_return_state))
        self.write({
            "x_return_state": "approved",
        })
        self.message_post(
            body=_("<b>Đã phê duyệt yêu cầu đổi/trả từ Zalo Mini App</b>"),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def action_reject_return(self, reason=""):
        """Từ chối yêu cầu đổi/trả (chỉ cho đơn Zalo)."""
        self.ensure_one()
        if not self._is_zalo_order():
            raise UserError(_("Chức năng này chỉ áp dụng cho đơn hàng Zalo Mini App."))
        if not self.x_return_requested:
            raise UserError(_("Đơn hàng chưa có yêu cầu đổi/trả từ khách."))
        if self.x_return_state and self.x_return_state not in ("pending", "approved"):
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % dict(self._fields['x_return_state'].selection).get(self.x_return_state, self.x_return_state))
        self.write({
            "x_return_state": "rejected",
            "x_return_rejected_reason": reason or "",
        })
        msg = _("<b>Đã từ chối yêu cầu đổi/trả từ Zalo Mini App</b>")
        if reason:
            msg += _("<br/>• <b>Lý do:</b> %s") % reason
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

    def action_complete_return(self):
        """Hoàn tất đổi/trả (chỉ cho đơn Zalo)."""
        self.ensure_one()
        if not self._is_zalo_order():
            raise UserError(_("Chức năng này chỉ áp dụng cho đơn hàng Zalo Mini App."))
        if self.x_return_state not in ("approved", "processing"):
            raise UserError(_("Yêu cầu đổi/trả chưa được phê duyệt hoặc đang xử lý."))
        self.write({
            "x_return_state": "completed",
            "x_return_completed_date": fields.Datetime.now(),
        })
        self.message_post(
            body=_("<b>Đã hoàn tất xử lý đổi/trả từ Zalo Mini App</b>"),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def create(self, vals):
        """Khi tạo đơn Zalo, tự động set return_state = pending nếu x_return_requested = True."""
        res = super().create(vals)
        if res.partner_id.x_is_zalo_account and res.x_return_requested and not res.x_return_state:
            res.x_return_state = "pending"
        return res

    def write(self, vals):
        """Khi cập nhật x_return_requested = True cho đơn Zalo, tự động set return_state = pending."""
        res = super().write(vals)
        if "x_return_requested" in vals and vals["x_return_requested"]:
            for order in self:
                if order.partner_id.x_is_zalo_account and not order.x_return_state:
                    super(SaleOrder, order).write({"x_return_state": "pending"})
        return res
