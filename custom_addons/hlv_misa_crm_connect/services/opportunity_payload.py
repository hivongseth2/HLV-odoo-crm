# -*- coding: utf-8 -*-
"""Body tạo / sửa Cơ hội (POST Opportunity) trên MISA CRM.

Util thuần: vào dữ liệu đã tra sẵn (khách, giai đoạn, dòng hàng), ra dict body. Không gọi mạng.
Chép từ request thật khi bấm Lưu ở trang "Thêm Cơ hội" và khi sửa một cơ hội (DevTools, 10/2026).
"""
from .misa_form import product_line, product_table, record_state, vn_date_utc

TABLE = "opportunity_product"
# "Mẫu tiêu chuẩn" của Cơ hội — mẫu form mà mọi request bắt được đều dùng.
FORM_LAYOUT_ID = 47
FORM_LAYOUT_NAME = "Mẫu tiêu chuẩn"
# Cột form gửi khi mở cơ hội để sửa (GetDataSubFormByID) — chép nguyên văn.
SUBFORM_COLUMNS = (
    "SortOrder,ProductID,ProductIDText,Description,ProductCode,UnitID,UnitIDText,Amount,Price,"
    "DescriptionProduct,TaxPercentID,TaxPercentIDText,TaxOC,Tax,PriceAfterTax,Height,ToCurrencyOC,ToCurrency,"
    "Width,TotalOC,Length,Total,Radius,Weight,IsTradeDiscount,DiscountPercent,DiscountOC,Mass,Discount,"
    "UsageUnitID,UsageUnitIDText,Ratio,OperatorID,OperatorIDText,UsageUnitAmount,UsageUnitPrice,"
    "IsDiscountPerUnit,IsDiscountOverallAutoSplit,IsDiscountDirectly,DiscountPerUnit,DiscountAfterTax,"
    "PriceAfterDiscount,ToCurrencyOCAfterDiscount,ToCurrencyAfterDiscount,IsNoteRow,ID,AsyncID,ProductSetID,"
    "ProductSetMasterID,ProductInSetMasterID,IsSetProduct,IsChildProduct,ProductIDInSet"
)
SUBFORM_AGGREGATES = (
    "AmountSummary,ToCurrencyAfterDiscountSummary,ToCurrencySummary,DiscountAfterTaxSummary,DiscountSummary,"
    "TaxSummary,TotalSummary,UsageUnitAmountSummary,ToCurrencySummaryOC,DiscountSummaryOC,TaxSummaryOC,"
    "TotalSummaryOC,ToCurrencyOCAfterDiscountSummary,ID"
)


def opportunity_line(sort_order, product, qty, amounts, description=None):
    """Một dòng hàng mới của cơ hội. Xem misa_form.product_line."""
    return product_line(TABLE, sort_order, product, qty, amounts, description)


def opportunity_payload(header, rows, old_rows=None, record=None):
    """Body POST Opportunity — tạo (``record`` None) hoặc sửa.

    Nhận ``header``: {"account": {"id", "name"}, "stage": {"id", "text", "probability" (%)},
    "closing_date" ("YYYY-MM-DD" hoặc chuỗi ngày MISA), "name" (None -> "Bán hàng cho <khách>" như
    form tự điền), "lead_source": {"id", "text"} | None, "description", "custom_field13"}.
    ``rows``: dòng gửi trong Data (tạo: ``opportunity_line``; sửa: misa_form.edit_rows).
    ``old_rows``: dòng như lúc mở form (chỉ khi sửa).
    ``record`` khi sửa: {"id", "code", "modified_date", "version"} lấy từ FormDataNew lúc mở form.
    """
    account, stage, source = header["account"], header["stage"], header.get("lead_source")
    body = {
        "Fields": [], "FieldsCustom": [], "DataCustom": {"CustomField13": header.get("custom_field13")},
        "IsUseForeignCurrency": False, "ExchangeRate": 1, "CurrencyTypeID": 1, "CurrencyTypeIDText": "VND",
        "AccountID": account["id"], "AccountIDText": account["name"],
        "OpportunityName": header.get("name") or "Bán hàng cho %s" % account["name"],
        "ProductCategoryID": None, "ProductCategoryIDText": "",
        "StageID": stage["id"], "StageIDText": stage["text"],
        # Form gửi tỷ lệ dạng phân số (10% -> 0.1); MISA lưu lại thành 10.
        "Probability": (stage.get("probability") or 0) / 100.0,
        "ClosingDate": vn_date_utc(header["closing_date"]),
        "LeadSourceID": str(source["id"]) if source else None,
        "LeadSourceIDText": source["text"] if source else "",
        "Description": header.get("description") or None,
        "IsPublic": False,
        "OpportunityCode": record["code"] if record else None,
        "AccountReferedID": None if record else 0, "AccountReferedIDText": "",
        "FormLayoutID": FORM_LAYOUT_ID, "FormLayoutIDText": FORM_LAYOUT_NAME,
        "MappingDatas": [],
        "IsGetFieldFormLayout": True, "IsProductChange": True, "IsMultiCurrency": False,
        "CustomTables": [product_table(TABLE, rows, old_rows)],
    }
    body.update(record_state(record))
    return body



def stage_history_payload(opportunity_id, stage, closing_date):
    """Body POST Opportunity/stageHistory — form gửi sau khi tạo / đổi giai đoạn để ghi lịch sử."""
    return {
        "OpportunityID": opportunity_id, "StageID": stage["id"], "Stage": stage["text"],
        "Probability": stage.get("probability") or 0, "ExpectedRevenue": None,
        "ClosingDate": vn_date_utc(closing_date),
    }
