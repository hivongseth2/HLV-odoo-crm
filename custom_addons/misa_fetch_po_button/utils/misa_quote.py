# -*- coding: utf-8 -*-
"""Đọc báo giá (Quote) trên MISA CRM: tìm báo giá theo số (BG…), lấy hàng và khách của một báo
giá — để trang hợp đồng (/hop-dong) lấy hàng của báo giá vào hợp đồng. Chỉ đọc.

Cùng cách gọi với cơ hội (misa_opportunity.py): token CRM đã lưu, hết hạn thì đăng nhập lại một lần.
"""
import base64
import uuid

from odoo import models

GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/Quote/Grid"
LINES_URL = "https://amisapp.misa.vn/crm/g1/api/business/Quote/DataSubPaging"
_GRID_COLUMNS = "ID,QuoteCode,QuoteName,QuoteDate,AccountID,AccountIDText,TotalSummary,StageIDText,OwnerIDText"
_LINE_COLUMNS = (
    "ID,SortOrder,ProductID,ProductIDText,Description,DescriptionProduct,UnitID,UnitIDText,Amount,Price,"
    "ToCurrency,Discount,TaxPercentIDText,Tax,Total,IsNoteRow,IsSetProduct,IsChildProduct"
)
QUOTE_LIMIT = 10
LINE_LIMIT = 200


def _columns(names):
    return base64.b64encode(names.encode("utf-8")).decode("ascii")


def _tax_percent(text):
    """"8%" -> 8.0; "KCT", "" hoặc lạ -> None."""
    digits = (text or "").replace("%", "").replace(",", ".").strip()
    try:
        return float(digits)
    except ValueError:
        return None


class MisaQuote(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def crm_search_quotes(self, keyword, limit=QUOTE_LIMIT):
        """Báo giá khớp keyword (số báo giá BG…, tên khách…) theo ô tìm của CRM.
        Trả [{"id", "code", "date", "account_id", "account", "total", "stage", "owner"}]; keyword rỗng → [].
        UserError khi không gọi được CRM."""
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        rows = self._crm_read_call(self._post_quote_grid, keyword, limit)
        return [
            {
                "id": row.get("ID"),
                "code": row.get("QuoteCode") or row.get("QuoteName") or "",
                "date": (row.get("QuoteDate") or "")[:10],
                "account_id": row.get("AccountID"),
                "account": row.get("AccountIDText") or "",
                "total": float(row.get("TotalSummary") or 0),
                "stage": row.get("StageIDText") or "",
                "owner": row.get("OwnerIDText") or "",
            }
            for row in rows if row.get("ID")
        ]

    def crm_quote_products(self, quote_id):
        """Hàng của một báo giá theo thứ tự trên CRM: [{"code", "name", "note", "unit", "qty",
        "price" (đơn giá chưa VAT đã trừ chiết khấu dòng), "tax_percent", "is_combo"}].
        Bỏ dòng ghi chú và dòng con của combo. UserError khi không gọi được CRM."""
        rows = self._crm_read_call(self._post_quote_lines, int(quote_id))
        products = []
        for row in sorted(rows, key=lambda r: r.get("SortOrder") or 0):
            if row.get("IsNoteRow") or row.get("IsChildProduct") or not row.get("ProductIDText"):
                continue
            qty = float(row.get("Amount") or 0)
            net = float(row.get("ToCurrency") or 0) - float(row.get("Discount") or 0)
            products.append({
                "code": (row.get("ProductIDText") or "").strip(),
                "name": (row.get("Description") or row.get("ProductIDText") or "").strip(),
                "note": row.get("DescriptionProduct") or "",
                "unit": row.get("UnitIDText") or "",
                "qty": qty,
                "price": net / qty if qty else float(row.get("Price") or 0),
                "tax_percent": _tax_percent(row.get("TaxPercentIDText")),
                "is_combo": bool(row.get("IsSetProduct")),
            })
        return products

    def crm_account_codes(self, account_id):
        """Mã khách (AccountNumber) và MST của khách CRM, để tìm khách tương ứng trong Odoo.
        Trả {"account_number", "taxcode"}; không lấy được → giá trị None."""
        identity = self.get_account_identity(account_id, self._get_cached_crm_headers()) or {}
        return {"account_number": identity.get("account_number"), "taxcode": identity.get("taxcode")}

    # ------------------------------------------------------------------
    def _post_quote_grid(self, headers, keyword, limit):
        return self._post_crm_read(headers, GRID_URL, {
            "Columns": _columns(_GRID_COLUMNS),
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": 0, "Page": 1, "PageSize": limit,
            "Filters": [], "Formula": "",
            "LayoutCode": "Quote", "LayoutCodeCheckPermission": "Quote",
            "DefaultTotal": True, "IsMappingData": False, "MappingValueObject": {},
            "IsApproved": False, "CustomPagingData": {}, "IsUsedELTS": True,
            "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True, "IsGetCache": True,
            "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
            # Ô tìm của trang danh sách báo giá trên CRM (gõ số báo giá / tên khách).
            "AISearchKeyword": keyword, "SkipNormalSearch": False,
        }, "quote")

    def _post_quote_lines(self, headers, quote_id):
        return self._post_crm_read(headers, LINES_URL, {
            "Columns": _columns(_LINE_COLUMNS),
            "Sorts": [], "Start": 0, "Page": 1, "PageSize": LINE_LIMIT,
            "Filters": [], "DefaultTotal": False, "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": str(quote_id), "TableName": "quote_product",
                "MasterKey": "CustomID", "SumColumn": "",
            },
            "IsApproved": False,
            # Không cần dòng tổng — để trống phần cột tổng hợp của bảng con.
            "CustomPagingData": {"SubFormConfig": {
                "ColumnFieldSubForm": "", "ColumnAggregateSubForm": "", "TableName": "quote_product",
                "IsSystem": True, "ParentIDKey": "CustomID", "IsBringSerialType": False, "AggregateField": [],
            }},
            "IsUsedELTS": True, "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True,
            "IsGetCache": True, "IsCheckInactive": False, "IsConverted": False,
            "SessionID": str(uuid.uuid4()), "AISearchKeyword": "", "SkipNormalSearch": False,
        }, "quote")
