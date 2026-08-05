# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _is_zalo_return_picking(self):
        """Kiểm tra picking này có phải là return picking từ đơn Zalo không."""
        self.ensure_one()
        if self.picking_type_id.code != "incoming":
            return False
        # Tìm sale order liên quan qua origin hoặc backorder
        origin = self.origin or ""
        # Return picking thường có origin dạng "WH/OUT/xxxxx"
        if not origin:
            return False
        # Tìm picking gốc (outgoing)
        origin_picking = self.env["stock.picking"].sudo().search([
            ("name", "=", origin),
            ("picking_type_id.code", "=", "outgoing"),
        ], limit=1)
        if not origin_picking:
            return False
        # Tìm sale order từ picking gốc
        sale_order = self.env["sale.order"].sudo().search([
            ("picking_ids", "in", [origin_picking.id]),
        ], limit=1)
        if not sale_order:
            return False
        return bool(sale_order.partner_id.x_is_zalo_account)

    def _get_zalo_sale_order(self):
        """Lấy sale order Zalo liên quan đến return picking này."""
        self.ensure_one()
        origin = self.origin or ""
        if not origin:
            return None
        origin_picking = self.env["stock.picking"].sudo().search([
            ("name", "=", origin),
            ("picking_type_id.code", "=", "outgoing"),
        ], limit=1)
        if not origin_picking:
            return None
        sale_order = self.env["sale.order"].sudo().search([
            ("picking_ids", "in", [origin_picking.id]),
            ("partner_id.x_is_zalo_account", "=", True),
        ], limit=1)
        return sale_order if sale_order else None

    def write(self, vals):
        """Khi return picking được validate (done), tự động complete return trên SO Zalo."""
        res = super().write(vals)
        if "state" in vals and vals["state"] == "done":
            for picking in self:
                if picking.picking_type_id.code != "incoming":
                    continue
                sale_order = picking._get_zalo_sale_order()
                if sale_order and sale_order.x_return_requested and sale_order.x_return_state == "processing":
                    sale_order.write({
                        "x_return_state": "completed",
                        "x_return_completed_date": fields.Datetime.now(),
                    })
                    sale_order.message_post(
                        body=_(
                            "<b>Phiếu trả hàng %s đã hoàn tất - Đổi/trả Zalo hoàn thành</b>"
                        ) % picking.name,
                        message_type="comment",
                        subtype_xmlid="mail.mt_note",
                    )
        return res

    @api.model
    def create(self, vals):
        """Khi tạo return picking mới, tự động link về SO Zalo."""
        picking = super().create(vals)
        if picking.picking_type_id.code == "incoming":
            sale_order = picking._get_zalo_sale_order()
            if sale_order and sale_order.x_return_requested and sale_order.x_return_state in ("approved", False, None):
                # Nếu chưa có return_state hoặc đang approved, set processing
                write_vals = {
                    "x_return_state": "processing",
                    "x_return_picking_id": picking.id,
                }
                if not sale_order.x_return_state:
                    write_vals["x_return_state"] = "processing"
                sale_order.write(write_vals)
                sale_order.message_post(
                    body=_(
                        "<b>Đã tạo phiếu trả hàng %s từ WH/OUT - Đổi/trả Zalo</b>"
                    ) % picking.name,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return picking