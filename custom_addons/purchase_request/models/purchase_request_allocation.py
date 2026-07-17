# Copyright 2019 ForgeFlow, S.L.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import html_escape


class PurchaseRequestAllocation(models.Model):
    _name = "purchase.request.allocation"
    _description = "Phân bổ yêu cầu mua hàng"

    purchase_request_line_id = fields.Many2one(
        string="Dòng yêu cầu mua hàng",
        comodel_name="purchase.request.line",
        required=True,
        ondelete="cascade",
        copy=True,
        index=True,
    )
    company_id = fields.Many2one(
        string="Công ty",
        comodel_name="res.company",
        readonly=True,
        related="purchase_request_line_id.request_id.company_id",
        store=True,
        index=True,
    )
    stock_move_id = fields.Many2one(
        string="Dịch chuyển kho",
        comodel_name="stock.move",
        ondelete="cascade",
        index=True,
    )
    purchase_line_id = fields.Many2one(
        string="Dòng mua hàng",
        comodel_name="purchase.order.line",
        copy=True,
        ondelete="cascade",
        help="Dòng đơn đặt hàng dịch vụ",
        index=True,
    )
    product_id = fields.Many2one(
        string="Sản phẩm",
        comodel_name="product.product",
        related="purchase_request_line_id.product_id",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        string="Đơn vị tính",
        comodel_name="uom.uom",
        related="purchase_request_line_id.product_uom_id",
        readonly=True,
        required=True,
    )
    requested_product_uom_qty = fields.Float(
        string="Số lượng yêu cầu",
        help="Số lượng của dòng yêu cầu mua hàng được phân bổ cho dịch chuyển kho, theo ĐVT của dòng yêu cầu mua hàng",
    )

    allocated_product_qty = fields.Float(
        string="Số lượng đã phân bổ",
        copy=False,
        help="Số lượng của dòng yêu cầu mua hàng được phân bổ cho dịch chuyển kho, theo ĐVT mặc định của sản phẩm",
    )
    open_product_qty = fields.Float(
        string="Số lượng mở", compute="_compute_open_product_qty"
    )

    purchase_state = fields.Selection(related="purchase_line_id.state")

    @api.depends(
        "requested_product_uom_qty",
        "allocated_product_qty",
        "stock_move_id",
        "stock_move_id.state",
        "stock_move_id.product_uom_qty",
        "stock_move_id.move_line_ids.quantity",
        "purchase_line_id",
        "purchase_line_id.qty_received",
        "purchase_state",
    )
    def _compute_open_product_qty(self):
        for rec in self:
            if rec.purchase_state in ["cancel", "done"]:
                rec.open_product_qty = 0.0
            else:
                rec.open_product_qty = (
                    rec.requested_product_uom_qty - rec.allocated_product_qty
                )
                if rec.open_product_qty < 0.0:
                    rec.open_product_qty = 0.0

    @api.model
    def _purchase_request_confirm_done_message_content(self, message_data):
        message = ""
        message += _(
            "Từ lần nhận cuối cùng, số lượng này đã được "
            "phân bổ cho yêu cầu mua hàng này"
        )
        message += "<ul>"
        message += _(
            "<li><b>%(product_name)s</b>: "
            "Số lượng đã nhận %(product_qty)s %(product_uom)s</li>"
        ) % {
            "product_name": html_escape(message_data["product_name"]),
            "product_qty": message_data["product_qty"],
            "product_uom": message_data["product_uom"],
        }
        message += "</ul>"
        return message

    def _prepare_message_data(self, po_line, request, allocated_qty):
        return {
            "request_name": request.name,
            "po_name": po_line.order_id.name,
            "product_name": po_line.product_id.display_name,
            "product_qty": allocated_qty,
            "product_uom": po_line.product_uom.name,
        }

    def _notify_allocation(self, allocated_qty):
        if not allocated_qty:
            return
        for allocation in self:
            request = allocation.purchase_request_line_id.request_id
            po_line = allocation.purchase_line_id
            message_data = self._prepare_message_data(po_line, request, allocated_qty)
            message = self._purchase_request_confirm_done_message_content(message_data)
            request.sudo().message_post(
                body=Markup(message),
                subtype_id=self.env.ref("mail.mt_note").id,
            )
