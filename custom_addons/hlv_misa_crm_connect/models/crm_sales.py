# -*- coding: utf-8 -*-
"""Báo giá (Quote) và đơn hàng (SaleOrder) trên MISA CRM: tìm, xem hàng. Chỉ đọc.

Báo giá dùng lại misa_fetch_po_button (crm_search_quotes, crm_quote_products).
"""
from odoo import models

from ..services.crm_payloads import (
    keep_product_lines, sale_order_line_row, sale_order_lines_payload, sale_order_row, sale_order_search_payload,
)


class MisaCrmSales(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

    def api_quote_search(self, keyword, limit=10):
        """Báo giá khớp ``keyword`` (số BG…, tên khách…). Xem misa.api.utils.crm_search_quotes."""
        return {"items": self._misa().crm_search_quotes(keyword, limit)}

    def api_quote_lines(self, quote_id):
        """Hàng của một báo giá. Xem misa.api.utils.crm_quote_products."""
        return {"items": self._misa().crm_quote_products(quote_id)}

    def api_sale_order_search(self, keyword, limit=10):
        """Đơn hàng khớp ``keyword`` theo ô tìm của trang danh sách đơn. Từ khoá rỗng -> []."""
        if not (keyword or "").strip():
            return {"items": []}
        rows = self._crm_data("POST", "SaleOrder/Grid", "saleorder",
                              payload=sale_order_search_payload(keyword, limit)) or []
        return {"items": [sale_order_row(row) for row in rows if row.get("ID")]}

    def api_sale_order_lines(self, sale_order_id):
        """Hàng của một đơn, bỏ dòng ghi chú và dòng con combo."""
        rows = self._crm_data("POST", "SaleOrder/DataSubPaging", "saleorder",
                              payload=sale_order_lines_payload(int(sale_order_id))) or []
        return {"items": [sale_order_line_row(row) for row in keep_product_lines(rows)]}
