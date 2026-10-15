# -*- coding: utf-8 -*-
"""Đơn hàng (SaleOrder) trên MISA CRM: tìm, xem hàng. Chỉ đọc."""
from odoo import models

from ..services.crm_payloads import (
    keep_product_lines, sale_order_line_row, sale_order_lines_payload, sale_order_row, sale_order_search_payload,
)


class MisaCrmSaleOrder(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

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
