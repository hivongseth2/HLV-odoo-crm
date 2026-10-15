# -*- coding: utf-8 -*-
"""Body tạo Cơ hội (POST Opportunity) trên MISA CRM, kèm cách tính tiền từng dòng hàng.

Util thuần: vào dữ liệu đã tra sẵn (khách, giai đoạn, hàng), ra dict body. Không gọi mạng.
Body chép từ request thật khi bấm Lưu ở trang "Thêm Cơ hội" (DevTools, 10/2026): form CRM tự
tính tiền rồi gửi cả dòng lẫn tổng — server không tính hộ, nên ở đây phải tính y như form.
"""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# "Mẫu tiêu chuẩn" của Cơ hội — mẫu form mà mọi request bắt được đều dùng.
FORM_LAYOUT_ID = 47
FORM_LAYOUT_NAME = "Mẫu tiêu chuẩn"
VN_UTC_OFFSET = timedelta(hours=7)


def money(value):
    """Làm tròn tiền 2 chữ số, nửa lên (như form CRM: 380000/1.08 -> 351851.85).

    Nhận: số. Trả: float. Không dùng round() vì float 0.125 làm tròn xuống.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def line_amounts(qty, tax_percent, price=None, price_after_tax=None):
    """Tiền một dòng hàng.

    Nhận: số lượng, % VAT (None = KCT, tính như 0), và MỘT trong hai: ``price_after_tax`` (đơn giá
    sau VAT — ưu tiên) hoặc ``price`` (đơn giá chưa VAT).
    Trả: {"price", "price_after_tax", "to_currency", "tax", "total"}.
    Có giá sau VAT: thành tiền = giá sau VAT × SL đúng tuyệt đối, phần lẻ dồn vào tiền thuế
    (đúng số khách thấy trên báo giá). Chỉ có giá chưa VAT: thuế = thành tiền chưa VAT × %.
    Biên: cả hai None -> giá 0.
    """
    rate = Decimal(str(tax_percent or 0)) / 100
    qty = Decimal(str(qty))
    if price_after_tax is not None:
        after = Decimal(str(price_after_tax))
        unit = Decimal(str(money(after / (1 + rate))))
        to_currency = money(unit * qty)
        total = money(after * qty)
        return {
            "price": float(unit), "price_after_tax": money(after), "to_currency": to_currency,
            "tax": money(Decimal(str(total)) - Decimal(str(to_currency))), "total": total,
        }
    unit = Decimal(str(price or 0))
    to_currency = money(unit * qty)
    tax = money(Decimal(str(to_currency)) * rate)
    return {
        "price": money(unit), "price_after_tax": money(unit * (1 + rate)), "to_currency": to_currency,
        "tax": tax, "total": money(Decimal(str(to_currency)) + Decimal(str(tax))),
    }


def closing_date_utc(value):
    """Ngày "YYYY-MM-DD" (giờ VN) -> chuỗi UTC form CRM gửi: 0h ngày đó ở VN = 17h hôm trước UTC.

    Nhận: chuỗi ngày ISO hoặc date. Trả: "2026-10-31T17:00:00.000Z". Sai định dạng -> ValueError.
    """
    day = value if isinstance(value, date) else date.fromisoformat(str(value).strip()[:10])
    moment = datetime(day.year, day.month, day.day) - VN_UTC_OFFSET
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def opportunity_line(sort_order, product, qty, amounts, description=None):
    """Một dòng bảng "Thông tin hàng hóa" (opportunity_product) như form gửi khi Lưu.

    Nhận: thứ tự (1, 2…), hàng đã tra (crm_payloads.product_row), SL, kết quả ``line_amounts``,
    diễn giải (None -> tên hàng). Trả: dict dòng.
    """
    qty = float(qty)
    tax_id = product.get("tax_id")
    return {
        "SortOrder": sort_order, "TableName": "opportunity_product",
        "ProductID": product["id"], "ProductIDText": product.get("code"), "ProductCode": product.get("code"),
        "Description": description or product.get("description") or product.get("name"),
        "DescriptionProduct": None,
        "UnitID": product.get("unit_id"), "UnitIDText": product.get("unit"),
        "UsageUnitID": product.get("unit_id"), "UsageUnitIDText": product.get("unit"),
        "Amount": qty, "UsageUnitAmount": qty, "Ratio": 1, "OperatorID": 1, "OperatorIDText": "Nhân",
        "Price": amounts["price"], "UsageUnitPrice": amounts["price"],
        "PriceAfterTax": amounts["price_after_tax"],
        "TaxPercentID": str(tax_id) if tax_id not in (None, "") else None,
        "TaxPercentIDText": product.get("tax") if tax_id not in (None, "") else None,
        "Tax": amounts["tax"], "TaxOC": amounts["tax"],
        "ToCurrency": amounts["to_currency"], "ToCurrencyOC": amounts["to_currency"],
        "PriceAfterDiscount": amounts["price"],
        "ToCurrencyAfterDiscount": amounts["to_currency"], "ToCurrencyOCAfterDiscount": amounts["to_currency"],
        "Total": amounts["total"], "TotalOC": amounts["total"],
        "Discount": 0, "DiscountOC": 0, "DiscountPercent": 0, "DiscountPerUnit": 0, "DiscountAfterTax": 0,
        "IsTradeDiscount": None, "IsDiscountPerUnit": False, "IsDiscountOverallAutoSplit": None,
        "IsDiscountDirectly": False,
        "Height": 0, "Width": 0, "Length": 0, "Radius": 0, "Weight": 0, "Mass": 0,
        "IsNoteRow": None, "ID": None, "MISAEntityState": 1, "AsyncID": "",
        "OwnerID": product.get("owner_id"),
        "PromotionMasterRowID": "", "PromotionRowID": "", "ProductSetID": "", "ProductSetMasterID": "",
        "ProductInSetMasterID": "", "IsSetProduct": False, "IsChildProduct": "", "ProductIDInSet": "",
        "ExcludeCurrentRecord": "", "ExchangeID": 0, "IsExchangeProduct": None, "ExchangePoint": 0,
        "TotalAmountBasedUPriceAndDATax": False, "AmountBasedOnPriceAfterTax": False,
    }


def _summary(rows):
    def total(key):
        return money(sum(Decimal(str(row[key] or 0)) for row in rows))

    qty, to_currency, tax, grand = total("Amount"), total("ToCurrency"), total("Tax"), total("Total")
    return {
        "AmountSummary": qty, "UsageUnitAmountSummary": qty,
        "ToCurrencySummary": to_currency, "ToCurrencySummaryOC": to_currency,
        "ToCurrencyAfterDiscountSummary": to_currency, "ToCurrencyOCAfterDiscountSummary": to_currency,
        "DiscountSummary": 0, "DiscountSummaryOC": 0, "DiscountAfterTaxSummary": 0,
        "TaxSummary": tax, "TaxSummaryOC": tax, "TotalSummary": grand, "TotalSummaryOC": grand,
    }


def opportunity_create_payload(account, stage, closing_date, rows, name=None, lead_source=None,
                               description=None):
    """Body POST Opportunity.

    Nhận: khách {"id", "name"}, giai đoạn {"id", "text", "probability" (%)}, ngày kết thúc
    "YYYY-MM-DD", các dòng ``opportunity_line``, tên cơ hội (None -> "Bán hàng cho <khách>" như
    form tự điền), nguồn gốc {"id", "text"} hoặc None, mô tả.
    Trả: dict body. Không có dòng hàng -> bảng hàng rỗng (MISA vẫn nhận).
    """
    return {
        "Fields": [], "FieldsCustom": [], "DataCustom": {"CustomField13": None},
        "IsUseForeignCurrency": False, "ExchangeRate": 1, "CurrencyTypeID": 1, "CurrencyTypeIDText": "VND",
        "AccountID": account["id"], "AccountIDText": account["name"],
        "OpportunityName": name or "Bán hàng cho %s" % account["name"],
        "ProductCategoryID": None, "ProductCategoryIDText": "",
        "StageID": stage["id"], "StageIDText": stage["text"],
        # Form gửi tỷ lệ dạng phân số (10% -> 0.1); MISA lưu lại thành 10.
        "Probability": (stage.get("probability") or 0) / 100.0,
        "ClosingDate": closing_date_utc(closing_date),
        "LeadSourceID": str(lead_source["id"]) if lead_source else None,
        "LeadSourceIDText": lead_source["text"] if lead_source else "",
        "Description": description or None,
        "IsPublic": False, "OpportunityCode": None, "AccountReferedID": 0, "AccountReferedIDText": "",
        "FormLayoutID": FORM_LAYOUT_ID, "FormLayoutIDText": FORM_LAYOUT_NAME,
        "MappingDatas": [], "MISAEntityState": 1, "ModifiedDate": None, "FormModeState": 1,
        "IsGetFieldFormLayout": True, "IsProductChange": True, "IsMultiCurrency": False,
        "CustomTables": [{
            "IsSystem": True, "DataFields": [], "OldData": [], "SummaryFields": [],
            "GroupBoxText": "Thông tin hàng hóa", "IsRequired": False, "ParentIDKey": "CustomID",
            "TableName": "opportunity_product", "IsProductChange": True,
            "Summary": _summary(rows), "Data": rows,
        }],
    }


def stage_history_payload(opportunity_id, stage, closing_date):
    """Body POST Opportunity/stageHistory — form gửi ngay sau khi tạo để ghi lịch sử giai đoạn."""
    return {
        "OpportunityID": opportunity_id, "StageID": stage["id"], "Stage": stage["text"],
        "Probability": stage.get("probability") or 0, "ExpectedRevenue": None,
        "ClosingDate": closing_date_utc(closing_date),
    }
