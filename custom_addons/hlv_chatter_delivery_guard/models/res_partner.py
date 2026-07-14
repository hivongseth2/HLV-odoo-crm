# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    hlv_block_outbound_delivery = fields.Boolean(
        string="Không được xuất hàng",
        tracking=True,
        help=(
            "Chặn xử lý các phiếu PICK, PACK, OUT và các phiếu xuất khác cho "
            "liên hệ này. Tất cả liên hệ con cũng tự động bị chặn."
        ),
    )
    hlv_outbound_delivery_blocked = fields.Boolean(
        string="Đang bị chặn xuất hàng",
        compute="_compute_hlv_outbound_delivery_blocked",
        recursive=True,
        help="Được bật khi chính liên hệ này hoặc một liên hệ cha đã bị đánh dấu chặn.",
    )

    def _hlv_outbound_delivery_block_source(self):
        """Return the closest blocked partner in the current partner's ancestry."""
        self.ensure_one()
        partner = self
        visited_ids = set()
        while partner and partner.id not in visited_ids:
            visited_ids.add(partner.id)
            if partner.hlv_block_outbound_delivery:
                return partner
            partner = partner.parent_id
        return self.env["res.partner"]

    @api.depends(
        "hlv_block_outbound_delivery",
        "parent_id",
        "parent_id.hlv_block_outbound_delivery",
        "parent_id.hlv_outbound_delivery_blocked",
    )
    def _compute_hlv_outbound_delivery_blocked(self):
        for partner in self:
            partner.hlv_outbound_delivery_blocked = bool(
                partner._hlv_outbound_delivery_block_source()
            )
