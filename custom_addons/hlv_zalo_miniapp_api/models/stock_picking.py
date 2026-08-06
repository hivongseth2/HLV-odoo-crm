# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    x_is_zalo_picking = fields.Boolean(
        string="Phiếu giao hàng Zalo",
        compute="_compute_x_is_zalo_picking",
        store=True,
        help="Đánh dấu phiếu kho này thuộc đơn hàng Zalo Mini App",
    )

    x_zalo_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả Zalo",
        default=False,
        tracking=True,
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả cho phiếu xuất kho này",
    )

    x_zalo_return_state = fields.Selection(
        [
            ("pending", "Chờ duyệt"),
            ("approved", "Đã duyệt"),
            ("processing", "Đang xử lý"),
            ("completed", "Hoàn tất"),
            ("rejected", "Từ chối"),
        ],
        string="Trạng thái đổi/trả Zalo",
        default=False,
        tracking=True,
        help="Trạng thái xử lý yêu cầu đổi/trả của phiếu xuất kho Zalo",
    )

    x_zalo_return_type = fields.Selection(
        [
            ("return", "Trả hàng hoàn tiền"),
            ("exchange", "Đổi hàng"),
            ("refund", "Hoàn tiền một phần"),
        ],
        string="Loại đổi/trả Zalo",
        tracking=True,
        help="Phân loại yêu cầu đổi/trả của phiếu xuất kho Zalo",
    )

    x_zalo_return_refund_amount = fields.Float(
        string="Số tiền hoàn lại",
        tracking=True,
        help="Số tiền sẽ hoàn lại cho khách (chỉ áp dụng cho phiếu Zalo)",
    )

    x_zalo_return_note = fields.Text(
        string="Ghi chú đổi/trả Zalo",
        tracking=True,
        help="Ghi chú từ khách hàng Zalo khi yêu cầu đổi/trả",
    )

    x_zalo_return_rejected_reason = fields.Text(
        string="Lý do từ chối",
        tracking=True,
        help="Lý do từ chối yêu cầu đổi/trả Zalo",
    )

    x_zalo_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu trả hàng (WH/IN)",
        tracking=True,
        help="Phiếu nhập kho trả hàng được tạo từ wizard trả hàng chuẩn Odoo",
    )

    x_zalo_return_completed_date = fields.Datetime(
        string="Ngày hoàn tất đổi/trả Zalo",
        tracking=True,
        help="Thời điểm hoàn tất xử lý đổi/trả phiếu kho Zalo",
    )

    @api.depends("sale_id", "sale_id.partner_id.x_is_zalo_account", "partner_id.x_is_zalo_account", "picking_type_id.code")
    def _compute_x_is_zalo_picking(self):
        for picking in self:
            is_zalo = False
            if picking.sale_id and picking.sale_id.partner_id.x_is_zalo_account:
                is_zalo = True
            elif picking.partner_id and picking.partner_id.x_is_zalo_account:
                is_zalo = True
            picking.x_is_zalo_picking = is_zalo

    def _get_origin_outgoing_picking(self):
        """Tìm phiếu xuất kho OUT gốc của return picking này."""
        self.ensure_one()
        origin = self.origin or ""
        if not origin:
            return self.env["stock.picking"]
        origin_picking = self.env["stock.picking"].sudo().search([
            ("name", "=", origin),
            ("picking_type_id.code", "=", "outgoing"),
        ], limit=1)
        return origin_picking

    def action_approve_zalo_return(self):
        """Phê duyệt yêu cầu đổi/trả Zalo & mở wizard stock.return.picking chuẩn Odoo."""
        self.ensure_one()
        if not self.x_is_zalo_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu kho thuộc đơn hàng Zalo Mini App."))
        if not self.x_zalo_return_requested:
            raise UserError(_("Phiếu kho này chưa có yêu cầu đổi/trả từ khách Zalo."))
        if self.x_zalo_return_state and self.x_zalo_return_state not in ("pending", "draft"):
            state_label = dict(self._fields["x_zalo_return_state"].selection).get(self.x_zalo_return_state, self.x_zalo_return_state)
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % state_label)

        self.write({"x_zalo_return_state": "approved"})

        msg = Markup(_("<b>Đã phê duyệt yêu cầu đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

        # Trả về action mở wizard trả hàng chuẩn Odoo (stock.return.picking)
        return {
            "name": _("Trả hàng (Return Picking)"),
            "view_mode": "form",
            "res_model": "stock.return.picking",
            "type": "ir.actions.act_window",
            "target": "new",
            "context": dict(self.env.context, active_id=self.id, active_model="stock.picking"),
        }

    def action_reject_zalo_return(self, reason=""):
        """Từ chối yêu cầu đổi/trả Zalo."""
        self.ensure_one()
        if not self.x_is_zalo_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu kho Zalo Mini App."))
        if not self.x_zalo_return_requested:
            raise UserError(_("Phiếu kho này chưa có yêu cầu đổi/trả từ khách."))
        if self.x_zalo_return_state and self.x_zalo_return_state not in ("pending", "approved"):
            state_label = dict(self._fields["x_zalo_return_state"].selection).get(self.x_zalo_return_state, self.x_zalo_return_state)
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % state_label)

        self.write({
            "x_zalo_return_state": "rejected",
            "x_zalo_return_rejected_reason": reason or "",
        })

        msg = Markup(_("<b>Đã từ chối yêu cầu đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        if reason:
            msg += Markup(_("<br/>• <b>Lý do:</b> %s")) % reason
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

    def action_complete_zalo_return(self):
        """Hoàn tất đổi/trả Zalo thủ công."""
        self.ensure_one()
        if not self.x_is_zalo_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu kho Zalo Mini App."))
        if self.x_zalo_return_state not in ("approved", "processing"):
            raise UserError(_("Yêu cầu đổi/trả chưa được phê duyệt hoặc đang xử lý."))
        self.write({
            "x_zalo_return_state": "completed",
            "x_zalo_return_completed_date": fields.Datetime.now(),
        })
        msg = Markup(_("<b>Đã hoàn tất xử lý đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

    @api.model
    def create(self, vals):
        """Khi tạo phiếu nhập kho (return picking), tự động link về phiếu xuất kho Zalo gốc."""
        picking = super().create(vals)
        if picking.picking_type_id.code == "incoming":
            origin_picking = picking._get_origin_outgoing_picking()
            if origin_picking and origin_picking.x_zalo_return_requested:
                write_vals = {
                    "x_zalo_return_state": "processing",
                    "x_zalo_return_picking_id": picking.id,
                }
                origin_picking.write(write_vals)
                msg = Markup(_(
                    "<b>Đã tạo phiếu trả hàng %s từ phiếu xuất kho %s - Đổi/trả Zalo</b>"
                )) % (picking.name, origin_picking.name)
                origin_picking.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
                if origin_picking.sale_id:
                    origin_picking.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        return picking

    def write(self, vals):
        """Khi phiếu return picking được validate (done), tự động complete return trên phiếu OUT Zalo."""
        res = super().write(vals)
        if "state" in vals and vals["state"] == "done":
            for picking in self:
                if picking.picking_type_id.code != "incoming":
                    continue
                origin_picking = picking._get_origin_outgoing_picking()
                if origin_picking and origin_picking.x_zalo_return_requested and origin_picking.x_zalo_return_state in ("processing", "approved"):
                    origin_picking.write({
                        "x_zalo_return_state": "completed",
                        "x_zalo_return_completed_date": fields.Datetime.now(),
                    })
                    msg = Markup(_(
                        "<b>Phiếu trả hàng %s đã hoàn tất - Đổi/trả Zalo hoàn thành cho phiếu xuất %s</b>"
                    )) % (picking.name, origin_picking.name)
                    origin_picking.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
                    if origin_picking.sale_id:
                        origin_picking.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        return res