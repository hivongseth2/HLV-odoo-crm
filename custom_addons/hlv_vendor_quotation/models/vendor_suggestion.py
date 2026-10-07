# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .vendor_quote_utils import rank_vendor_suggestions

SUGGEST_LIMIT = 10
PURCHASED_STATES = ("purchase", "done")


class VendorSuggestion(models.AbstractModel):
    """Gợi ý NCC nên hỏi giá, từ lịch sử đơn mua và bảng giá NCC của sản phẩm."""

    _name = "hlv.vendor.suggestion"
    _description = "Gợi ý nhà cung cấp theo lịch sử mua hàng"

    @api.model
    def suggest(self, products, exclude_partners=None, limit=SUGGEST_LIMIT):
        """Trả list dict như rank_vendor_suggestions, partner_id là công ty NCC (commercial).

        Đọc đơn mua bằng sudo vì sale không có quyền xem đơn mua; chỉ trả tên NCC, số mặt
        hàng, số đơn và ngày — không trả giá mua, để giá vốn không lộ ra phía sale.
        """
        if not products:
            return []
        exclude_ids = set((exclude_partners or self.env["res.partner"]).commercial_partner_id.ids)
        coverage, order_stats = [], {}

        PoLine = self.env["purchase.order.line"].sudo()
        domain = [
            ("product_id", "in", products.ids),
            ("state", "in", PURCHASED_STATES),
            ("display_type", "=", False),
        ]
        for partner, product in PoLine._read_group(domain, ["partner_id", "product_id"]):
            coverage.append((partner.commercial_partner_id.id, product.id, "po"))
        # Đếm đơn theo NCC riêng: đếm trong nhóm (NCC, sản phẩm) sẽ đếm trùng đơn nhiều dòng.
        for partner, order_count, last_date in PoLine._read_group(
            domain, ["partner_id"], ["order_id:count_distinct", "date_planned:max"]
        ):
            vendor_id = partner.commercial_partner_id.id
            prev_count, prev_date = order_stats.get(vendor_id, (0, None))
            dates = [d for d in (prev_date, fields.Date.to_date(last_date)) if d]
            order_stats[vendor_id] = (prev_count + order_count, max(dates) if dates else None)

        sellers = self.env["product.supplierinfo"].sudo().search([
            "|",
            ("product_id", "in", products.ids),
            "&", ("product_id", "=", False), ("product_tmpl_id", "in", products.product_tmpl_id.ids),
        ])
        for seller in sellers:
            matched = products.filtered(
                lambda p, s=seller: p == s.product_id if s.product_id else p.product_tmpl_id == s.product_tmpl_id
            )
            for product in matched:
                coverage.append((seller.partner_id.commercial_partner_id.id, product.id, "pricelist"))

        active_vendor_ids = set(self.env["res.partner"].sudo().search([
            ("id", "in", list({row[0] for row in coverage})),
        ]).ids)
        coverage = [
            row for row in coverage if row[0] in active_vendor_ids and row[0] not in exclude_ids
        ]
        return rank_vendor_suggestions(coverage, order_stats, limit)
