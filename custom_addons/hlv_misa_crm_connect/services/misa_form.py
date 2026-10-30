# -*- coding: utf-8 -*-
"""Phần chung của form MISA CRM có bảng hàng (Cơ hội, Báo giá): tính tiền dòng, dựng dòng, tổng,
và gộp dòng khi SỬA.

Util thuần: vào dữ liệu, ra dict / list. Không gọi mạng, không đụng ``self.env``.
Mọi body chép từ request thật bắt bằng DevTools (10/2026). Form MISA tự tính tiền rồi gửi cả dòng
lẫn tổng — server không tính hộ, nên ở đây phải tính y như form.

Trạng thái một dòng (``MISAEntityState``) khi lưu: 0 = giữ nguyên (chỉ trong OldData), 1 = thêm,
2 = sửa, 3 = xoá. Sửa phải gửi kèm ``OldData`` = các dòng như lúc mở form.
"""
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

STATE_NEW, STATE_EDIT, STATE_DELETE = 1, 2, 3
VN_UTC_OFFSET = timedelta(hours=7)
# Trường chỉ có ở kết quả đọc dòng (GetDataSubFormByID), form không gửi lại khi lưu.
_READ_ONLY_ROW_KEYS = {"Avatar", "CustomID", "ProductName"}


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


def vn_date_utc(value):
    """Ngày (giờ VN) -> chuỗi UTC form CRM gửi: 0h ngày đó ở VN = 17h hôm trước UTC.

    Nhận: "YYYY-MM-DD", chuỗi MISA trả ("2026-11-15T00:00:00.000+07:00" — lấy 10 ký tự đầu), date,
    hoặc rỗng. Trả: "2026-11-14T17:00:00.000Z"; rỗng / None -> None. Sai định dạng -> ValueError.
    """
    if not value:
        return None
    day = value if isinstance(value, date) else date.fromisoformat(str(value).strip()[:10])
    moment = datetime(day.year, day.month, day.day) - VN_UTC_OFFSET
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def product_line(table, sort_order, product, qty, amounts, description=None):
    """Một dòng hàng MỚI như form gửi khi Lưu.

    Nhận: tên bảng ("opportunity_product" / "quote_product"), thứ tự (1, 2…), hàng đã tra
    (crm_payloads.product_row), SL, kết quả ``line_amounts``, diễn giải (None -> tên hàng).
    Trả: dict dòng, trạng thái "thêm".
    """
    qty = float(qty)
    tax_id = product.get("tax_id")
    return {
        "SortOrder": sort_order, "TableName": table,
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
        "IsNoteRow": None, "ID": None, "MISAEntityState": STATE_NEW, "AsyncID": "",
        "OwnerID": product.get("owner_id"),
        "PromotionMasterRowID": "", "PromotionRowID": "", "ProductSetID": "", "ProductSetMasterID": "",
        "ProductInSetMasterID": "", "IsSetProduct": False, "IsChildProduct": "", "ProductIDInSet": "",
        "ExcludeCurrentRecord": "", "ExchangeID": 0, "IsExchangeProduct": None, "ExchangePoint": 0,
        "TotalAmountBasedUPriceAndDATax": False, "AmountBasedOnPriceAfterTax": False,
    }


# ── Combo trên bảng hàng (request "Thêm Cơ hội" có combo, DevTools 30/10/2026) ──────────────────
# Chọn một combo, form gửi MỘT dòng cha (giá, thuế của chính combo) rồi các dòng con ngay sau, nối với
# nhau bằng một mã nhóm form tự sinh: dòng cha mang nó ở ProductSetMasterID, dòng con ở
# ProductInSetMasterID. Dòng con có tiền = 0 và KHÔNG được cộng vào dòng tổng.

def new_set_master_id():
    """Mã nhóm mới cho một combo trên bảng hàng (chuỗi GUID như form sinh)."""
    return str(uuid.uuid4())


def combo_parent_fields(master_id):
    """Trường đánh dấu dòng cha của combo, ghi đè lên dòng ``product_line`` của mã combo."""
    return {"ProductSetMasterID": master_id, "IsSetProduct": True}


def combo_child_product(child):
    """Hàng con (một phần tử ``Product/GetProductInProductSet``) -> dạng hàng ``product_line`` nhận.

    Biên: thiếu UnitID thì lấy UsageUnitID; thiếu mô tả bán thì lấy tên hàng.
    """
    return {
        "id": child.get("ID"),
        "code": (child.get("ProductCode") or "").strip(),
        "name": child.get("ProductName"),
        "description": child.get("SaleDescription") or child.get("ProductName"),
        "unit_id": child.get("UnitID") or child.get("UsageUnitID"),
        "unit": child.get("UnitIDText") or child.get("UsageUnitIDText"),
        "tax_id": child.get("TaxID"),
        "tax": child.get("TaxIDText"),
        # Form gửi OwnerID rỗng ở dòng con (dòng cha mới mang người phụ trách).
        "owner_id": "",
    }


def combo_child_qty(per_set, combo_qty):
    """SL dòng con = SL trong một bộ × SL combo. Biên: SL trong bộ trống -> coi là 1.

    Mẫu bắt được chỉ có combo SL 1; nhân theo SL combo là cách form giữ tỉ lệ khi đổi SL dòng cha.
    """
    return float(Decimal(str(per_set or 1)) * Decimal(str(combo_qty)))


def combo_child_fields(child, master_id):
    """Trường nối dòng con với dòng cha, ghi đè lên dòng ``product_line`` của hàng con."""
    return {
        "ProductSetID": child.get("ProductSetID"), "ProductInSetMasterID": master_id,
        "IsChildProduct": True, "ProductIDInSet": child.get("ProductIDInSet"), "OwnerID": "",
    }


def renew_set_master_ids(rows):
    """Cấp mã nhóm combo MỚI cho các dòng chép từ chứng từ khác (vd tạo báo giá từ cơ hội).

    Nhận: list dòng (dict, sửa tại chỗ). Dòng cha và dòng con cùng combo vẫn chung một mã mới.
    Biên: dòng không thuộc combo giữ nguyên.
    """
    renamed = {}
    for row in rows:
        for key in ("ProductSetMasterID", "ProductInSetMasterID"):
            old = row.get(key)
            if old:
                row[key] = renamed.setdefault(old, new_set_master_id())
    return rows


def serial_type_cell():
    """Ô ẩn "serial_type" mà bảng hàng Báo giá gửi kèm mỗi dòng (chuỗi JSON, DataIndex ngẫu nhiên)."""
    return json.dumps({
        "FieldName": "serial_type", "DisplayText": "", "Value": "", "IsHidden": True, "TabOrder": -1,
        "IsSensitiveOrigin": False, "IsSensitive": False, "IsDisabled": False, "IsValidSensitive": False,
        "DataIndex": str(uuid.uuid4()), "OldValue": [], "ToolTipGrid": [],
    }, separators=(",", ":"))


def saved_row(read_row, table, defaults=None):
    """Dòng đã lưu (đọc từ GetDataSubFormByID) -> dạng form gửi lại trong ``OldData``.

    Nhận: dict dòng MISA trả, tên bảng, giá trị thay cho ô đang None (form tự điền, vd Báo giá
    gửi DiscountPercent 0 thay vì null). Trả: dict mới, trạng thái 0 (giữ nguyên).
    Bỏ trường chỉ-đọc (Avatar, CustomID, ProductName, CustomFieldxText).
    """
    row = {key: value for key, value in read_row.items()
           if key not in _READ_ONLY_ROW_KEYS
           and not (key.startswith("CustomField") and key.endswith("Text"))}
    for key, value in (defaults or {}).items():
        if row.get(key) is None:
            row[key] = value
    row["TableName"] = table
    row["MISAEntityState"] = 0
    return row


def edit_rows(old_rows, new_rows):
    """Dòng gửi khi SỬA. Nhận: dòng cũ (``saved_row``), dòng mới (``product_line``) hoặc None.

    ``new_rows`` None = giữ hàng như cũ: gửi lại từng dòng cũ ở trạng thái "sửa" với giá trị cũ.
    Có ``new_rows`` = THAY toàn bộ: dòng cũ ở trạng thái "xoá", dòng mới ở trạng thái "thêm" —
    đúng cách form gửi khi người dùng xoá dòng cũ rồi thêm dòng mới.
    Trả: list dòng cho ``Data``.
    """
    if new_rows is None:
        return [dict(row, MISAEntityState=STATE_EDIT) for row in old_rows]
    return list(new_rows) + [dict(row, MISAEntityState=STATE_DELETE) for row in old_rows]


def _sum(rows, key):
    return money(sum(Decimal(str(row.get(key) or 0)) for row in rows))


def summary(rows, extra_zero=()):
    """Dòng tổng của bảng hàng, chỉ tính dòng không bị xoá và không phải dòng con combo.

    Nhận: dòng gửi đi (``Data``), các trường tổng riêng của form luôn 0 (vd Báo giá:
    CustomField3Summary). Trả: dict tổng như form gửi.
    Dòng con combo: form không cộng (mẫu combo 1 bộ 2 món gửi AmountSummary = 1) — tiền đã nằm ở
    dòng cha, cộng SL dòng con là tổng SL sai.
    """
    rows = [row for row in rows
            if row.get("MISAEntityState") != STATE_DELETE and not row.get("IsChildProduct")]
    to_currency, after_discount = _sum(rows, "ToCurrency"), _sum(rows, "ToCurrencyAfterDiscount")
    discount, tax, total = _sum(rows, "Discount"), _sum(rows, "Tax"), _sum(rows, "Total")
    result = {
        "AmountSummary": _sum(rows, "Amount"), "UsageUnitAmountSummary": _sum(rows, "UsageUnitAmount"),
        "ToCurrencySummary": to_currency, "ToCurrencySummaryOC": to_currency,
        "ToCurrencyAfterDiscountSummary": after_discount, "ToCurrencyOCAfterDiscountSummary": after_discount,
        "DiscountSummary": discount, "DiscountSummaryOC": discount,
        "DiscountAfterTaxSummary": _sum(rows, "DiscountAfterTax"),
        "TaxSummary": tax, "TaxSummaryOC": tax, "TotalSummary": total, "TotalSummaryOC": total,
    }
    result.update({key: 0 for key in extra_zero})
    return result


def product_table(table, rows, old_rows=None, required=False, extra_zero=()):
    """Khối ``CustomTables[0]`` (bảng "Thông tin hàng hóa"). ``old_rows`` chỉ khi sửa."""
    block = {
        "IsSystem": True, "DataFields": [], "SummaryFields": [], "GroupBoxText": "Thông tin hàng hóa",
        "IsRequired": required, "ParentIDKey": "CustomID", "TableName": table, "IsProductChange": True,
        "Summary": summary(rows, extra_zero), "Data": rows,
    }
    block["OldData"] = list(old_rows or [])
    return block


def record_state(record):
    """Phần đánh dấu tạo / sửa của body form.

    Nhận: None (tạo) hoặc {"id", "modified_date", "version"} lấy từ FormDataNew lúc mở form (sửa).
    Sửa cần đúng ModifiedDate + Version lúc mở: MISA dùng chúng để chặn ghi đè khi người khác vừa
    sửa cùng bản ghi.
    """
    if not record:
        return {"MISAEntityState": 1, "ModifiedDate": None, "FormModeState": 1}
    return {
        "MISAEntityState": 2, "ID": str(record["id"]), "ModifiedDate": record["modified_date"],
        "Version": record.get("version") or 0, "FormModeState": 2,
    }


def payload_total(payload):
    """Tổng tiền (sau VAT) của body form vừa dựng — số trả lại cho bên gọi."""
    return payload["CustomTables"][0]["Summary"]["TotalSummary"]


def subform_request(table, columns, aggregates):
    """Body GetDataSubFormByID: đọc dòng hàng đã lưu khi mở form sửa."""
    return [{
        "ColumnFieldSubForm": columns, "ColumnAggregateSubForm": aggregates, "TableName": table,
        "IsSystem": True, "ParentIDKey": "CustomID", "IsBringSerialType": False,
    }]
