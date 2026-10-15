# -*- coding: utf-8 -*-
"""Body gửi MISA CRM cho các lệnh tìm, và cách đọc dòng MISA trả về thành dict gọn.

Util thuần: vào giá trị, ra dict. Không đụng ``self.env``, không gọi mạng.
Body chép từ request thật của trang "Thêm Cơ hội" trên amisapp.misa.vn (DevTools, 10/2026).
"""
import uuid

from odoo.addons.misa_fetch_po_button.utils.crm_product import parse_tax_rate
from odoo.addons.misa_fetch_po_button.utils.misa_opportunity import _columns as encode_columns

ACCOUNT_COLUMNS = (
    "ID,AccountName,AccountNumber,TaxCode,OfficeTel,OfficeEmail,BillingAddress,ShippingAddress,"
    "OwnerID,Debt,DebtLimit"
)
ACCOUNT_SEARCH_FIELDS = ("AccountName", "TaxCode", "AccountNumber", "OfficeTel", "BillingAddress")
PRODUCT_COLUMNS = (
    "ID,ProductCode,ProductName,UsageUnitID,UsageUnitIDText,TaxID,TaxIDText,UnitPrice,PriceAfterTax,"
    "PurchasedPrice,SaleDescription,IsSetProduct,ProductCategoryID,ProductCategoryIDText,"
    "ProductPropertiesID,ProductPropertiesIDText,OwnerID,DefaultStockID,DefaultStockIDText"
)
PRODUCT_SEARCH_FIELDS = ("ProductCode", "ProductName")
STOCK_COLUMNS = (
    "ID,ProductCode,ProductName,ProductCategoryIDText,UsageUnitIDText,StockQuantitySummary,"
    "FormLayoutID,FormLayoutIDText,OwnerID,OwnerIDText"
)
# Popup "Chọn hàng hóa" tìm thêm cả từ khoá tìm kiếm của hàng (gridlayout/FieldsQuickSearch/Product).
STOCK_SEARCH_FIELDS = ("ProductCode", "ProductName", "SearchKeywords")
MAX_PAGE_SIZE = 100


def page_size(limit, default=10):
    """Số dòng một trang: ``limit`` ép về 1..MAX_PAGE_SIZE.

    Nhận: số / chuỗi số / None. Trả: int. None, rỗng hoặc không phải số -> ``default``.
    """
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, MAX_PAGE_SIZE))


def keyword_filters(keyword, fields, search_condition=None):
    """Bộ lọc "chứa từ khoá" ở bất kỳ trường nào trong ``fields`` — kiểu ô tìm của form CRM.

    Nhận: từ khoá, tuple tên trường, SearchCondition như form gửi (khách: None, hàng: 2).
    Trả: (Filters, Formula). Từ khoá rỗng -> ([], "") = không lọc.
    Formula đánh số theo thứ tự các bộ lọc ``IsFromFormula``: "( 1 OR  2 )".
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return [], ""
    filters = [{
        "Operator": 1, "Value": keyword, "Property": field, "InputType": 1, "Group": "",
        "Addition": 2, "IsFromFormula": True, "SearchCondition": search_condition,
    } for field in fields]
    return filters, "( %s )" % " OR  ".join(str(i + 1) for i in range(len(fields)))


def _grid_payload(layout, columns, keyword, fields, page, limit, custom_paging=None, search_condition=None):
    filters, formula = keyword_filters(keyword, fields, search_condition)
    size = page_size(limit)
    page = max(1, int(page or 1))
    return {
        "Filters": filters, "Formula": formula,
        "page": page, "pageSize": size, "Start": (page - 1) * size,
        "DefaultTotal": True, "layoutCode": layout, "IsUsedELTS": True,
        "CustomPagingData": custom_paging, "IsCheckInactive": True,
        "IsMappingData": False, "MappingValueObject": {},
        "IsGetAllWhenEmptyCustomColumn": False,
        "Columns": encode_columns(columns),
    }


def account_search_payload(keyword, page=1, limit=10):
    """Body ``Account/grid``: tìm khách theo tên / MST / mã KH / SĐT / địa chỉ (kiểu "chứa").

    Từ khoá rỗng -> danh sách khách mới sửa gần nhất.
    """
    return _grid_payload("Account", ACCOUNT_COLUMNS, keyword, ACCOUNT_SEARCH_FIELDS, page, limit)


def product_search_payload(keyword, page=1, limit=10):
    """Body ``Product/grid``: tìm hàng theo mã / tên (kiểu "chứa"), CẢ hàng hết tồn và combo."""
    return _grid_payload("Product", PRODUCT_COLUMNS, keyword, PRODUCT_SEARCH_FIELDS, page, limit, {
        "IsRelatedListSharing": False, "IsEmployeeAccessLevel": True, "IsFromPriceBook": False,
        "IsDuplicate": False, "MasterID": 0, "IDs": [], "numberUnit": 0, "IsGetProductLedger": True,
        "IsSetProduct": False, "IsSet": False, "ColumnsMappingCustom": [], "ColumnMappingProduct": None,
        "ColumnMappingMaster": "", "IsLimitPaging": True, "IsGetQuantityCanOrder": False,
        "ConfigQuantityFromOrderStatus": "",
    }, search_condition=2)


def _fixed_stock_filter(prop, operator, value, input_type):
    return {
        "Operator": operator, "Value": value, "Property": prop, "InputType": input_type, "Group": "",
        "Addition": 1, "IsFromFormula": False, "FromFilterCustom": True,
    }


def product_stock_search_payload(keyword, page=1, limit=10):
    """Body ``Stock/productLedger/Paging``: như popup "Chọn hàng hóa" — chỉ hàng CÒN TỒN, không
    combo, không ngừng dùng; kèm số tồn. Từ khoá rỗng -> mọi hàng còn tồn.

    Bốn bộ lọc cố định luôn AND; Formula chỉ đánh số các bộ lọc từ khoá (IsFromFormula).
    """
    filters = [
        _fixed_stock_filter("IsSetProduct", 0, False, 17),
        _fixed_stock_filter("InActive", 0, False, 17),
        _fixed_stock_filter("StockQuantitySummary", 2, 0, 12),   # Operator 2 = lớn hơn
        _fixed_stock_filter("IsCheckShowOrderDetail", 0, False, 17),
    ]
    keyword = (keyword or "").strip()
    formula = ""
    if keyword:
        for field in STOCK_SEARCH_FIELDS:
            filters.append({
                "Group": None, "Addition": 1, "InputType": 1, "IsFromFormula": True, "Operator": 1,
                "Property": field, "CustomProperty": "AI" + field, "FieldType": 0,
                "Text": keyword, "Value": keyword, "SearchCondition": 2,
                "FromFilterCustom": True, "IsQuickSearchField": True,
            })
        formula = "(%s)" % " OR ".join("(%d)" % (i + 1) for i in range(len(STOCK_SEARCH_FIELDS)))
    size = page_size(limit)
    page = max(1, int(page or 1))
    return {
        "Columns": encode_columns(STOCK_COLUMNS),
        "Sorts": [], "Start": (page - 1) * size, "Page": page, "PageSize": size,
        "Filters": filters, "Formula": formula,
        "LayoutCode": "Product", "LayoutCodeCheckPermission": "Product",
        "DefaultTotal": False, "IsMappingData": False, "IsApproved": False,
        "CustomPagingData": {
            "IsRelatedListSharing": False, "IsEmployeeAccessLevel": True, "IsFromPriceBook": False,
            "IsDuplicate": False, "MasterID": 0, "IDs": [], "numberUnit": 0, "IsGetProductLedger": True,
            "IsSetProduct": False, "IsSet": False, "ColumnsMappingCustom": [], "ColumnMappingProduct": None,
            "ColumnMappingMaster": "", "IsLimitPaging": True, "IsGetQuantityCanOrder": False,
            "ConfigQuantityFromOrderStatus": "", "QuantityFromOrderStatus": "1,4,5",
            "IncludeDistributorOrder": False, "DeductMinimumStock": False,
            "IsShowOnlyInventory": True, "IsCheckViewDetailByLot": False,
        },
        "IsUsedELTS": True, "ListGmailPage": [], "ListFacebookPage": {}, "IsGetCache": True,
        "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
        "AISearchKeyword": "", "SkipNormalSearch": False,
    }


def sale_order_search_payload(keyword, limit=10):
    """Body ``SaleOrder/Grid``: tìm đơn hàng theo ô tìm của trang danh sách đơn (số đơn, khách…)."""
    return {
        "Columns": encode_columns(
            "ID,SaleOrderNo,SaleOrderName,SaleOrderDate,SaleOrderAmount,AccountID,AccountIDText,"
            "OwnerIDText,RevenueStatusIDText,DeliveryStatusIDText,PayStatusIDText,QuoteIDText,OpportunityIDText"
        ),
        "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
        "Start": 0, "Page": 1, "PageSize": page_size(limit),
        "Filters": [], "Formula": "",
        "LayoutCode": "SaleOrder", "LayoutCodeCheckPermission": "SaleOrder",
        "DefaultTotal": True, "IsMappingData": False, "MappingValueObject": {},
        "IsApproved": False, "CustomPagingData": {}, "IsUsedELTS": True,
        "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True, "IsGetCache": True,
        "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
        "AISearchKeyword": (keyword or "").strip(), "SkipNormalSearch": False,
    }


def sale_order_lines_payload(sale_order_id):
    """Body ``SaleOrder/DataSubPaging``: hàng của một đơn (bảng con sale_order_product)."""
    return {
        "Columns": encode_columns(
            "ID,SortOrder,ProductID,ProductIDText,Description,UnitID,UnitIDText,Amount,Price,"
            "PriceAfterTax,TaxPercentIDText,ToCurrency,Discount,Tax,Total,IsNoteRow,IsSetProduct,IsChildProduct"
        ),
        "Sorts": [], "Start": 0, "Page": 1, "PageSize": 200,
        "Filters": [], "DefaultTotal": False, "IsMappingData": False,
        "MappingValueObject": {
            "MasterID": str(sale_order_id), "TableName": "sale_order_product",
            "MasterKey": "CustomID", "SumColumn": "",
        },
        "IsApproved": False,
        "CustomPagingData": {"SubFormConfig": {
            "ColumnFieldSubForm": "", "ColumnAggregateSubForm": "", "TableName": "sale_order_product",
            "IsSystem": True, "ParentIDKey": "CustomID", "IsBringSerialType": False, "AggregateField": [],
        }},
        "IsUsedELTS": True, "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True,
        "IsGetCache": True, "IsCheckInactive": False, "IsConverted": False,
        "SessionID": str(uuid.uuid4()), "AISearchKeyword": "", "SkipNormalSearch": False,
    }


# ── Đọc dòng MISA trả về ─────────────────────────────────────────────────────
def misa_error_message(data):
    """Câu lỗi người đọc được trong một response MISA CRM (``Success`` false).

    Nhận: dict response (hoặc thứ khác). Trả: chuỗi; gom mọi ``ValidateInfo[].ErrorMessage``,
    không có thì ``UserMessage`` / ``SystemMessage``. Không có gì -> "".
    """
    if not isinstance(data, dict):
        return ""
    messages = [info.get("ErrorMessage") for info in data.get("ValidateInfo") or []
                if isinstance(info, dict) and info.get("ErrorMessage")]
    return "; ".join(messages) or data.get("UserMessage") or data.get("SystemMessage") or ""


def _text(value):
    return (value or "").strip() if isinstance(value, str) else value


def account_row(row):
    """Một dòng khách (Account/grid hoặc Account/{id}) -> dict gọn. Trường không có -> None."""
    return {
        "id": row.get("ID"),
        "name": _text(row.get("AccountName")),
        "code": _text(row.get("AccountNumber")),
        "tax_code": _text(row.get("TaxCode")),
        "phone": _text(row.get("OfficeTel")),
        "email": _text(row.get("OfficeEmail")),
        "billing_address": _text(row.get("BillingAddress")),
        "shipping_address": _text(row.get("ShippingAddress")),
        "owner_id": row.get("OwnerID"),
        "debt": row.get("Debt"),
        "debt_limit": row.get("DebtLimit"),
    }


def product_row(row):
    """Một dòng hàng (Product/grid) -> dict gọn. ``tax_percent`` None = KCT / chưa gắn thuế.

    ``code`` giữ nguyên như MISA lưu trừ khoảng trắng hai đầu (MISA có mã lưu kèm dấu cách đầu).
    """
    return {
        "id": row.get("ID"),
        "code": _text(row.get("ProductCode")),
        "name": _text(row.get("ProductName")),
        "unit_id": row.get("UsageUnitID"),
        "unit": row.get("UsageUnitIDText"),
        "tax_id": row.get("TaxID"),
        "tax": row.get("TaxIDText"),
        "tax_percent": parse_tax_rate(row.get("TaxIDText")),
        "price": row.get("UnitPrice") or 0,
        "is_combo": bool(row.get("IsSetProduct")),
        "category": row.get("ProductCategoryIDText"),
        "description": row.get("SaleDescription"),
        "stock": row.get("DefaultStockIDText"),
        "owner_id": row.get("OwnerID"),
    }


def stock_row(row):
    """Một dòng hàng còn tồn (Stock/productLedger/Paging) -> dict gọn, kèm ``stock_qty``."""
    return dict(product_row(row), stock_qty=row.get("StockQuantitySummary") or 0)


def sale_order_row(row):
    """Một dòng đơn hàng (SaleOrder/Grid) -> dict gọn."""
    return {
        "id": row.get("ID"),
        "code": row.get("SaleOrderNo") or "",
        "name": row.get("SaleOrderName") or "",
        "date": (row.get("SaleOrderDate") or "")[:10],
        "amount": float(row.get("SaleOrderAmount") or 0),
        "account_id": row.get("AccountID"),
        "account": row.get("AccountIDText") or "",
        "owner": row.get("OwnerIDText") or "",
        "revenue_status": row.get("RevenueStatusIDText") or "",
        "delivery_status": row.get("DeliveryStatusIDText") or "",
        "pay_status": row.get("PayStatusIDText") or "",
        "quote": row.get("QuoteIDText") or "",
        "opportunity": row.get("OpportunityIDText") or "",
    }


def sale_order_line_row(row):
    """Một dòng hàng của đơn -> dict gọn; ``price`` chưa VAT, ``price_after_tax`` sau VAT."""
    return {
        "code": _text(row.get("ProductIDText")),
        "description": row.get("Description") or "",
        "unit": row.get("UnitIDText") or "",
        "qty": float(row.get("Amount") or 0),
        "price": float(row.get("Price") or 0),
        "price_after_tax": float(row.get("PriceAfterTax") or 0),
        "tax_percent": parse_tax_rate(row.get("TaxPercentIDText")),
        "discount": float(row.get("Discount") or 0),
        "total": float(row.get("Total") or 0),
        "is_combo": bool(row.get("IsSetProduct")),
    }


def keep_product_lines(rows):
    """Bỏ dòng ghi chú và dòng con của combo (combo đã có một dòng riêng), xếp theo SortOrder."""
    return [
        row for row in sorted(rows or [], key=lambda r: r.get("SortOrder") or 0)
        if not row.get("IsNoteRow") and not row.get("IsChildProduct") and row.get("ProductIDText")
    ]
