# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ZaloReturnRejectWizard(models.TransientModel):
    _name = "zalo.return.reject.wizard"
    _description = "Wizard từ chối yêu cầu đổi/trả Zalo Mini App"

    picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu xuất kho",
        required=True,
        ondelete="cascade",
    )

    reason = fields.Text(
        string="Lý do từ chối",
        required=True,
        help="Nhập lý do từ chối yêu cầu đổi/trả để thông báo cho khách hàng Zalo Mini App",
    )

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_("Vui lòng nhập lý do từ chối yêu cầu đổi/trả."))
        self.picking_id.action_reject_zalo_return(reason=self.reason.strip())
        return {"type": "ir.actions.act_window_close"}
