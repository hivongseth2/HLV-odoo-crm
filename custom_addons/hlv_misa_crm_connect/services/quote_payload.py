# -*- coding: utf-8 -*-
"""Body tạo / sửa Báo giá (POST Quote) trên MISA CRM.

Util thuần: vào dữ liệu đã tra sẵn, ra dict body. Không gọi mạng.
Chép từ request thật khi tạo báo giá mới, sửa báo giá, và sinh báo giá từ cơ hội (DevTools, 10/2026).
Báo giá của HLV có trường tự định nghĩa (DataCustom); vài trường là CÔNG THỨC form tự tính trước
khi gửi — ở đây tính lại y như vậy (``formula_fields``).
"""
from decimal import Decimal

from .misa_form import (
    STATE_NEW, money, product_line, product_table, record_state, saved_row, serial_type_cell, vn_date_utc,
)

TABLE = "quote_product"
# "Mẫu tiêu chuẩn" của Báo giá.
FORM_LAYOUT_ID = 44
FORM_LAYOUT_NAME = "Mẫu tiêu chuẩn"
DEFAULT_STAGE = {"id": 1, "text": "Bản thảo"}
# Tổng riêng của bảng hàng báo giá (cột công thức giá mua / lãi lỗ, luôn 0 khi hàng chưa có giá mua).
EXTRA_SUMMARY = ("CustomField3Summary", "CustomField4Summary")
# Dòng đọc lại từ MISA để trống mấy ô này; form điền giá trị mặc định khi gửi lại (dòng cơ hội
# không có cột giá mua / lãi lỗ của báo giá -> 0).
SAVED_ROW_DEFAULTS = {"DiscountPercent": 0, "BatchNumber": "", "ExistAmount": 0, "CustomField3": 0, "CustomField4": 0}
SUBFORM_COLUMNS = (
    "SortOrder,CustomField1,DescriptionProduct,ProductID,ProductIDText,Description,UnitID,UnitIDText,Amount,"
    "Price,PriceAfterTax,ToCurrency,TaxPercentID,TaxPercentIDText,ProductCode,ToCurrencyOC,CustomField3,"
    "IsTradeDiscount,DiscountPercent,Discount,DiscountOC,CustomField4,TaxOC,TotalOC,Tax,Total,IsPromotion,"
    "PromotionID,PromotionIDText,StockQuantityDetail,SerialNumber,Height,Width,Length,DiscountAfterTax,Radius,"
    "Weight,Mass,UsageUnitID,UsageUnitIDText,Ratio,OperatorID,OperatorIDText,UsageUnitAmount,IsDiscountOverall,"
    "UsageUnitPrice,IsDiscountPerUnit,IsDiscountDirectly,IsDiscountOverallAutoSplit,DiscountPerUnit,"
    "PriceAfterDiscount,ToCurrencyOCAfterDiscount,ToCurrencyAfterDiscount,IsPromotionDiscount,BatchNumber,"
    "ExpireDate,ExistAmount,IsNoteRow,ID,AsyncID,PromotionMasterRowID,PromotionRowID,ExcludeCurrentRecord,"
    "ProductSetID,ProductSetMasterID,ProductInSetMasterID,IsSetProduct,IsChildProduct,ProductIDInSet,"
    "QuantityOrdered"
)
SUBFORM_AGGREGATES = (
    "ToCurrencyOCAfterDiscountSummary,CustomField4Summary,CustomField3Summary,ToCurrencyAfterDiscountSummary,"
    "TaxPercentOverallID,TaxPercentOverallIDText,DiscountPercentOverall,IsDiscountDirectlyOverall,TotalOverallOC,"
    "TotalOverall,TaxOverallOC,TaxOverall,DiscountOverallOC,DiscountOverall,ToCurrencySummary,"
    "DiscountAfterTaxSummary,DiscountSummary,AmountSummary,TaxSummary,TotalSummary,TaxSummaryOC,"
    "DiscountSummaryOC,UsageUnitAmountSummary,ToCurrencySummaryOC,TotalSummaryOC,PromotionOverAllID,"
    "PromotionOverAllIDText,IsPromotionDiscountOverAll,ID,QuantityOrdered"
)


def _quote_cells(customer_item=None):
    """Ô riêng của dòng báo giá. CustomField1 = "Tên khách hàng yêu cầu"; CustomField3/4 (thành
    tiền giá mua, lãi lỗ) là công thức theo giá mua của hàng — form gửi 0 khi hàng chưa có giá mua."""
    return {
        "CustomField1": customer_item or None, "CustomField3": 0, "CustomField4": 0,
        "IsPromotion": None, "PromotionID": None, "StockQuantityDetail": None, "SerialNumber": "",
        "BatchNumber": "", "ExpireDate": None, "ExistAmount": None, "IsDiscountOverall": None,
        "IsPromotionDiscount": None, "serial_type": serial_type_cell(),
    }


def quote_line(sort_order, product, qty, amounts, description=None, customer_item=None):
    """Một dòng hàng mới của báo giá. Xem misa_form.product_line; ``customer_item`` = tên hàng
    theo cách khách gọi (cột "Tên khách hàng yêu cầu")."""
    row = product_line(TABLE, sort_order, product, qty, amounts, description)
    row.update(_quote_cells(customer_item))
    return row


def quote_line_from_opportunity(sort_order, opportunity_row):
    """Dòng báo giá chép từ một dòng cơ hội đã lưu (giữ nguyên SL, giá, thuế, chiết khấu) — như
    MISA làm khi bấm "Tạo báo giá" trên cơ hội. Nhận: dòng cơ hội đọc từ GetDataSubFormByID."""
    # Giá trị của dòng cơ hội thắng; ô chỉ báo giá mới có thì lấy mặc định. MISA chép để trống
    # mã quy cách (SerialNumber) chứ không phải chuỗi rỗng như dòng thêm tay.
    row = dict(_quote_cells(), SerialNumber=None)
    row.update(saved_row(opportunity_row, TABLE, SAVED_ROW_DEFAULTS))
    row.update({"SortOrder": sort_order, "ID": None, "AsyncID": "", "MISAEntityState": STATE_NEW})
    return row


def saved_quote_row(read_row):
    """Dòng báo giá đã lưu -> dạng gửi lại trong OldData (kèm ô serial_type như form)."""
    row = saved_row(read_row, TABLE, SAVED_ROW_DEFAULTS)
    row["serial_type"] = serial_type_cell()
    return row


def formula_fields(table_summary, prepaid, shipping_cost, commission_percent):
    """Ba trường công thức của báo giá, tính như form MISA (FormulaContent trong cấu hình form):

    - CustomField16 "Còn phải thu" = TotalSummary − CustomField8 (khách TT trước)
    - CustomField21 "Chi phí hoa hồng dự kiến" = ToCurrencySummary × CustomField19 (% hoa hồng)
    - CustomField20 "Lãi lỗ tổng đơn" = CustomField4Summary − CustomField18 (chi phí giao) − CF21
    Công thức MISA nhân thẳng với số % (không chia 100) — giữ nguyên để khớp số trên MISA.
    Nhận: summary bảng hàng, các số (None = 0). Trả: dict ba trường.
    """
    def dec(value):
        return Decimal(str(value or 0))

    commission = dec(table_summary.get("ToCurrencySummary")) * dec(commission_percent)
    return {
        "CustomField16": money(dec(table_summary.get("TotalSummary")) - dec(prepaid)),
        "CustomField21": money(commission),
        "CustomField20": money(dec(table_summary.get("CustomField4Summary")) - dec(shipping_cost) - commission),
    }


def _text_or_none(value):
    return None if value in (None, "") else str(value)


def quote_payload(header, rows, old_rows=None, record=None):
    """Body POST Quote — tạo (``record`` None) hoặc sửa.

    Nhận ``header``: {"account": {"id", "name", "address", "tax_code"}, "opportunity": {"id", "name"}
    | None, "quote_date", "expired_date" (ngày hoặc None), "stage": {"id", "text"}, "description",
    "prepaid" (khách TT trước), "shipping_cost" (chi phí giao hàng dự kiến), "commission_percent"
    (% hoa hồng dự kiến), "validity_days", "payment_terms", "delivery_days"}.
    ``rows`` / ``old_rows`` / ``record``: như opportunity_payload.opportunity_payload.
    """
    account, opportunity = header["account"], header.get("opportunity")
    table = product_table(TABLE, rows, old_rows, required=True, extra_zero=EXTRA_SUMMARY)
    custom = {
        "CustomField14": header.get("payment_terms") or None,
        "CustomField13": _text_or_none(header.get("validity_days")),
        "CustomField17": _text_or_none(header.get("delivery_days")),
        "CustomField19": header.get("commission_percent"),
        "CustomField18": header.get("shipping_cost"),
    }
    custom.update(formula_fields(table["Summary"], header.get("prepaid"), header.get("shipping_cost"),
                                 header.get("commission_percent")))
    stage = header.get("stage") or DEFAULT_STAGE
    body = {
        "Fields": [], "FieldsCustom": [], "DataCustom": custom,
        "IsUseForeignCurrency": False, "ExchangeRate": 1, "CurrencyTypeID": 1, "CurrencyTypeIDText": "VND",
        "QuoteCode": record["code"] if record else None,
        "ExpiredDate": vn_date_utc(header.get("expired_date")),
        "AccountID": account["id"], "AccountIDText": account["name"],
        "Address": account.get("address"),
        "OpportunityID": opportunity["id"] if opportunity else None,
        "OpportunityIDText": opportunity["name"] if opportunity else "",
        "CustomField8": header.get("prepaid") or 0,
        "QuoteDate": vn_date_utc(header["quote_date"]),
        "StageID": stage["id"], "StageIDText": stage["text"],
        "TaxCode": account.get("tax_code"),
        "ContactID": None, "ContactIDText": "",
        "Description": header.get("description") or None,
        "IsPublic": False,
        "FormLayoutID": FORM_LAYOUT_ID, "FormLayoutIDText": FORM_LAYOUT_NAME,
        "MappingDatas": [],
        "IsGetFieldFormLayout": True, "IsProductChange": True, "IsMultiCurrency": False,
        "CustomTables": [table],
    }
    body.update(record_state(record))
    return body
