# -*- coding: utf-8 -*-
from odoo import fields, models, _


class StockQuant(models.Model):
    _inherit = "stock.quant"

    hold_request_qty = fields.Float(
        string="Đã giữ (Giữ hàng theo Sale)",
        compute="_compute_hold_request_qty",
        help=(
            "Số lượng tại đúng vị trí này đang bị khóa bởi các yêu cầu Giữ hàng theo Sale "
            "đang hiệu lực (trang /search_stock) — để kho biết phần nào trong 'Số lượng dự trữ' "
            "là do sale giữ chỗ, không phải do đơn bán thông thường."
        ),
    )

    def _compute_hold_request_qty(self):
        by_key = {}
        if self:
            move_lines = self.env["stock.move.line"].sudo().search([
                ("picking_id.is_stock_hold_picking", "=", True),
                ("picking_id.state", "not in", ("done", "cancel")),
                ("product_id", "in", self.product_id.ids),
                ("location_id", "in", self.location_id.ids),
            ])
            for ml in move_lines:
                key = (ml.product_id.id, ml.location_id.id)
                by_key[key] = by_key.get(key, 0.0) + ml.quantity
        for quant in self:
            quant.hold_request_qty = by_key.get((quant.product_id.id, quant.location_id.id), 0.0)

    def action_view_hold_requests(self):
        self.ensure_one()
        holds = self.env["stock.hold.request"].sudo().search([
            ("state", "=", "approved"),
            ("product_id", "=", self.product_id.id),
            ("hold_picking_id.move_line_ids.location_id", "=", self.location_id.id),
        ])
        return {
            "type": "ir.actions.act_window",
            "name": _("Yêu cầu giữ hàng tại vị trí này"),
            "res_model": "stock.hold.request",
            "view_mode": "list,form",
            "domain": [("id", "in", holds.ids)],
            "context": {"create": False},
        }
