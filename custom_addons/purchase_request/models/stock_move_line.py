# Copyright 2017 ForgeFlow, S.L.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from markupsafe import Markup

from odoo import _, api, models
from odoo.tools import html_escape


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    @api.model
    def _purchase_request_confirm_done_message_content(self, message_data):
        title = _(
            "Đã nhập kho {picking_name} cho yêu cầu {request_name}"
        ).format(
            picking_name=message_data["picking_name"],
            request_name=message_data["request_name"],
        )

        message_body = _(
            "Các sản phẩm thuộc YCMH {request_name} "
            "vừa được nhập vào {location_name} "
            "từ phiếu nhập kho {picking_name}:"
        ).format(
            request_name=message_data["request_name"],
            location_name=message_data["location_name"],
            picking_name=message_data["picking_name"],
        )

        product_line = Markup(
            "<ul><li><b>{}</b>: " + _("Số lượng thực nhập") + " {} {}</li></ul>"
        ).format(
            html_escape(message_data["product_name"]),
            message_data["product_qty"],
            html_escape(message_data["product_uom"]),
        )

        return Markup("<h3>{}</h3>{}{}").format(title, message_body, product_line)

    @api.model
    def _purchase_request_confirm_done_messages_content(self, messages_data):
        if not messages_data:
            return ""
        
        first_data = messages_data[0]
        title = _(
            "Đã nhập kho {picking_name} cho yêu cầu {request_name}"
        ).format(
            picking_name=first_data["picking_name"],
            request_name=first_data["request_name"],
        )

        message_body = _(
            "Các sản phẩm thuộc YCMH {request_name} "
            "vừa được nhập vào {location_name} "
            "từ phiếu nhập kho {picking_name}:"
        ).format(
            request_name=first_data["request_name"],
            location_name=first_data["location_name"],
            picking_name=first_data["picking_name"],
        )

        product_lines = "<ul>"
        for data in messages_data:
            product_lines += Markup(
                "<li><b>{}</b>: " + _("Số lượng thực nhập") + " {} {}</li>"
            ).format(
                html_escape(data["product_name"]),
                data["product_qty"],
                html_escape(data["product_uom"]),
            )
        product_lines += "</ul>"

        return Markup("<h3>{}</h3>{}{}").format(title, message_body, Markup(product_lines))

    @api.model
    def _picking_confirm_done_message_content(self, message_data):
        title = _("Đã nhập kho cho YCMH {name}").format(
            name=message_data["request_name"]
        )

        message_body = _(
            "Các sản phẩm thuộc YCMH {request_name} "
            "(người yêu cầu: {requestor}) "
            "vừa được nhập vào {location_name}:"
        ).format(
            request_name=message_data["request_name"],
            requestor=message_data["requestor"],
            location_name=message_data["location_name"],
        )

        product_line = Markup(
            "<ul><li><b>{}</b>: " + _("Số lượng thực nhập") + " {} {}</li></ul>"
        ).format(
            html_escape(message_data["product_name"]),
            message_data["product_qty"],
            html_escape(message_data["product_uom"]),
        )

        return Markup("<h3>{}</h3>{}{}").format(title, message_body, product_line)

    @api.model
    def _picking_confirm_done_messages_content(self, messages_data):
        if not messages_data:
            return ""
            
        first_data = messages_data[0]
        title = _("Đã nhập kho cho YCMH {name}").format(
            name=first_data["request_name"]
        )

        message_body = _(
            "Các sản phẩm thuộc YCMH {request_name} "
            "(người yêu cầu: {requestor}) "
            "vừa được nhập vào {location_name}:"
        ).format(
            request_name=first_data["request_name"],
            requestor=first_data["requestor"],
            location_name=first_data["location_name"],
        )

        product_lines = "<ul>"
        for data in messages_data:
            product_lines += Markup(
                "<li><b>{}</b>: " + _("Số lượng thực nhập") + " {} {}</li>"
            ).format(
                html_escape(data["product_name"]),
                data["product_qty"],
                html_escape(data["product_uom"]),
            )
        product_lines += "</ul>"

        return Markup("<h3>{}</h3>{}{}").format(title, message_body, Markup(product_lines))

    def _prepare_message_data(self, ml, request, allocated_qty):
        return {
            "request_name": request.name,
            "picking_name": ml.picking_id.name,
            "product_name": ml.product_id.display_name,
            "product_qty": allocated_qty,
            "product_uom": ml.product_uom_id.name,
            "location_name": ml.location_dest_id.display_name,
            "requestor": request.requested_by.partner_id.name,
        }

    def allocate(self):
        grouped_messages = {}
        for ml in self.filtered(
            lambda m: m.exists() and m.move_id.purchase_request_allocation_ids
        ):
            # We do sudo because potentially the user that completes the move
            #  may not have permissions for purchase.request.
            to_allocate_qty = ml.quantity
            to_allocate_uom = ml.product_uom_id
            for allocation in ml.move_id.purchase_request_allocation_ids.sudo():
                allocated_qty = 0.0
                if allocation.open_product_qty and to_allocate_qty:
                    to_allocate_uom_qty = to_allocate_uom._compute_quantity(
                        to_allocate_qty, allocation.product_uom_id
                    )
                    allocated_qty = min(
                        allocation.open_product_qty, to_allocate_uom_qty
                    )
                    allocation.allocated_product_qty += allocated_qty
                    to_allocate_uom_qty -= allocated_qty
                    to_allocate_qty = allocation.product_uom_id._compute_quantity(
                        to_allocate_uom_qty, to_allocate_uom
                    )

                request = allocation.purchase_request_line_id.sudo().request_id
                if allocated_qty:
                    message_data = self._prepare_message_data(
                        ml, request, allocated_qty
                    )
                    key = (request, ml.picking_id)
                    if key not in grouped_messages:
                        grouped_messages[key] = []
                    grouped_messages[key].append(message_data)

                allocation._compute_open_product_qty()

        # Send grouped messages to Chatter (internal log notes, no external emails)
        for (request, picking), messages_data in grouped_messages.items():
            if not messages_data:
                continue
                
            message = self._purchase_request_confirm_done_messages_content(
                messages_data
            )
            if message:
                request.sudo().message_post(
                    body=Markup(message),
                    subtype_id=self.env.ref(
                        "purchase_request.mt_request_picking_done"
                    ).id,
                )

            picking_message = self._picking_confirm_done_messages_content(
                messages_data
            )
            if picking_message:
                picking.sudo().message_post(
                    body=Markup(picking_message),
                    subtype_id=self.env.ref("mail.mt_note").id,
                )

    def _action_done(self):
        res = super()._action_done()
        self.allocate()
        return res
