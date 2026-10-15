# -*- coding: utf-8 -*-
"""Hàng hóa trên MISA CRM: tìm hàng (mọi hàng / chỉ hàng còn tồn), giá cho một khách, tra một mã."""
from odoo import models
from odoo.addons.misa_fetch_po_button.utils.crm_product import exact_code_match

from ..services.crm_payloads import (
    MAX_PAGE_SIZE, product_row, product_search_payload, product_stock_search_payload, stock_row,
)
from ..services.misa_form import line_amounts
from .misa_crm_client import CrmInputError

MAX_CODE_PAGES = 10


class MisaCrmProduct(models.AbstractModel):
    _inherit = "hlv.misa.crm.connect"

    def api_product_search(self, keyword, page=1, limit=10, in_stock_only=False):
        """Hàng khớp ``keyword`` ở mã / tên (kiểu "chứa").

        ``in_stock_only``: như popup "Chọn hàng hóa" — chỉ hàng còn tồn, không combo, kèm
        ``stock_qty`` (tìm thêm cả từ khoá tìm kiếm của hàng). Không: như ô mã hàng trên dòng —
        mọi hàng kể cả hết tồn và combo.
        Trả {"items": [...], "page", "total"}; ``total`` chỉ có khi ``in_stock_only`` (MISA chỉ đếm ở đó).
        """
        if in_stock_only:
            payload = product_stock_search_payload(keyword, page, limit)
            response = self._crm("POST", "Stock/productLedger/Paging", payload=payload,
                                 params={"saveWarehouse": "true"})
            rows = response.get("Data") or []
            return {"items": [stock_row(row) for row in rows], "page": payload["Page"],
                    "total": response.get("Total")}
        payload = product_search_payload(keyword, page, limit)
        rows = self._crm_data("POST", "Product/grid", payload=payload) or []
        return {"items": [product_row(row) for row in rows], "page": payload["page"], "total": None}

    def api_product_prices(self, account_id, product_ids):
        """Gợi ý giá khi chọn hàng cho một khách — đúng ba lệnh form gọi khi chọn hàng.

        Trả {"products": [{id, code, name, unit_id, unit, tax_id}], "price_book": <Data thô>,
        "recent_prices": <Data thô>}. Hai phần giá để nguyên như MISA trả (lúc ghi request chỉ
        thấy giá trị rỗng nên chưa rõ cấu trúc). ``account_id`` None -> bỏ phần giá.
        """
        ids = [int(pid) for pid in product_ids]
        details = self._crm_data("POST", "Product/getProductDetailByProductIDs/Opportunity", payload={
            "Products": [{"ID": pid} for pid in ids], "IsGetDetailStockQuantity": False,
        }) or []
        # MISA luôn trả kèm các dòng hệ thống (CKĐH, CKTL, DOIDIEM) — chỉ giữ hàng được hỏi.
        products = [{
            "id": row.get("ProductID"),
            "code": (row.get("ProductCode") or "").strip(),
            "name": row.get("ProductName"),
            "unit_id": row.get("UsageUnitID"),
            "unit": row.get("UsageUnitIDText"),
            "tax_id": row.get("TaxID"),
            "description": row.get("SaleDescription"),
        } for row in details if row.get("ProductID") in ids]
        result = {"products": products, "price_book": None, "recent_prices": None}
        if account_id:
            body = [str(pid) for pid in ids]
            result["price_book"] = self._crm_data(
                "POST", "Product/GetPriceBookByAccountID/%d" % int(account_id), payload=body,
                params={"saleProjectID": "undefined"})
            result["recent_prices"] = self._crm_data(
                "POST", "Product/getRecentPrice/%d/0/true" % int(account_id), payload=body)
        return result

    def _new_lines(self, lines, make_row):
        """Dòng hàng mới từ ``lines`` của bên gọi ({"code", "qty", "price_after_tax" | "price", …}).

        Tra từng mã trên MISA (sai mã -> 404, combo -> 400) và tính tiền theo thuế của hàng; dòng
        dựng bằng ``make_row(thứ_tự, hàng, sl, tiền, line)``. Tra hết TRƯỚC khi ghi gì lên MISA.
        """
        rows = []
        for index, line in enumerate(lines, start=1):
            product = self._product_by_code(line["code"])
            if product["is_combo"]:
                # Dòng combo trên form kéo theo các dòng con — chưa có request mẫu, không tự đoán.
                raise CrmInputError(400, "combo_not_supported",
                                    "Mã %s là combo — API chưa hỗ trợ thêm combo." % line["code"])
            amounts = line_amounts(line["qty"], product["tax_percent"],
                                   price=line.get("price"), price_after_tax=line.get("price_after_tax"))
            rows.append(make_row(index, product, line["qty"], amounts, line))
        return rows

    def _product_by_code(self, code):
        """Hàng có mã đúng bằng ``code`` (không phân biệt hoa thường, bỏ khoảng trắng hai đầu).

        Không có -> CrmInputError 404. Không lấy hàng gần giống: gắn nhầm hàng khó gỡ hơn báo lỗi.
        """
        # Tìm "chứa": mã ngắn (vd "4530") khớp cả trăm hàng — mã đúng có thể nằm ở trang sau.
        for page in range(1, MAX_CODE_PAGES + 1):
            payload = product_search_payload(code, page, MAX_PAGE_SIZE)
            rows = self._crm_data("POST", "Product/grid", payload=payload) or []
            found = exact_code_match([product_row(row) for row in rows], code)
            if found:
                return found
            if len(rows) < MAX_PAGE_SIZE:
                break
        raise CrmInputError(404, "product_not_found", "Không có mã hàng '%s' trên MISA." % code)
