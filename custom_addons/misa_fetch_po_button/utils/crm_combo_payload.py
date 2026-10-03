# -*- coding: utf-8 -*-
"""Dựng payload "Combo hàng hóa" (layout 128) cho MISA CRM: tạo mới và sửa.

Util thuần: vào dict / list, ra dict / list. Không gọi mạng, không đụng ``self.env``.

Tạo và sửa đều POST ``.../crm/g2/api/business/Product``; khác nhau ở ``MISAEntityState``
của phần đầu (1 tạo, 2 sửa) và của TỪNG dòng con trong bảng ``set_product``:

    0 giữ nguyên · 1 thêm mới (ID null) · 2 sửa (đổi số lượng) · 3 xoá

Khi sửa, MISA cần ĐỦ mọi dòng (kể cả dòng xoá) trong ``Data`` và toàn bộ dòng trước khi
sửa trong ``OldData`` — bắt chước đúng request màn hình CRM gửi lên.
"""

ROW_UNCHANGED = 0
ROW_NEW = 1
ROW_CHANGED = 2
ROW_DELETED = 3

_QTY_EPSILON = 1e-9


def new_component_row(component):
    """Dòng con MỚI (state 1) cho bảng set_product.

    Nhận: ``{'misa_id', 'code', 'name', 'quantity', 'unit_id', 'unit_name'}`` đã tra trên CRM.
    Trả: dict đúng các khoá màn hình CRM gửi khi thêm một dòng.
    """
    return {
        "ProductID": component["misa_id"],
        "ProductIDText": component["code"],
        "TableName": "set_product",
        "ProductCode": component["code"],
        "Description": component.get("name") or component["code"],
        "UnitID": component["unit_id"],
        "UnitIDText": component.get("unit_name") or "",
        "Amount": float(component.get("quantity") or 0.0),
        "ID": None,
        "MISAEntityState": ROW_NEW,
        "AsyncID": "",
        "OwnerID": "",
        "PromotionMasterRowID": "",
        "PromotionRowID": "",
        "ProductSetID": "",
        "ProductSetMasterID": "",
        "ProductInSetMasterID": "",
        "IsSetProduct": False,
        "IsChildProduct": "",
        "ProductIDInSet": "",
        "ExcludeCurrentRecord": "",
        "ExchangeID": 0,
        "IsExchangeProduct": None,
        "ExchangePoint": 0,
        "TotalAmountBasedUPriceAndDATax": False,
        "AmountBasedOnPriceAfterTax": False,
    }


def _existing_row(row, state, amount=None):
    """Dòng con ĐÃ CÓ (lấy từ GetDataSubFormByID) ở trạng thái ``state``."""
    return {
        "ProductID": row.get("ProductID"),
        "ProductIDText": row.get("ProductIDText") or row.get("ProductCode"),
        "TableName": "set_product",
        "ProductCode": row.get("ProductCode"),
        "Description": row.get("Description"),
        "UnitID": row.get("UnitID"),
        "UnitIDText": row.get("UnitIDText"),
        "Amount": float(row.get("Amount") or 0.0) if amount is None else float(amount),
        "ID": row.get("ID"),
        "MISAEntityState": state,
        "AsyncID": row.get("AsyncID"),
        "OwnerID": row.get("OwnerID"),
    }


def _set_product_table(data_rows, old_rows, amount_summary):
    return [{
        "IsSystem": True,
        "DataFields": [],
        "Summary": {"AmountSummary": amount_summary},
        "Data": data_rows,
        "OldData": old_rows,
        "SummaryFields": [],
        "GroupBoxText": "Thông tin hàng hóa",
        "IsRequired": True,
        "ParentIDKey": "CustomID",
        "TableName": "set_product",
        "IsProductChange": True,
    }]


def build_combo_create_payload(combo, components):
    """Payload TẠO combo.

    Nhận: ``combo`` (code, name, category_id/name, unit_id/name, tax_id/name, sale_price,
        cost_price, sale_description, description, form_layout_id/name), ``components`` đã
        tra trên CRM (xem new_component_row).
    Trả: dict JSON gửi thẳng lên CRM.
    """
    rows = [new_component_row(component) for component in components]
    return {
        "Fields": [],
        "FieldsCustom": [],
        "DataCustom": {"Avatar": ""},
        "ProductCode": combo["code"],
        "ProductCategoryID": str(combo["category_id"]),
        "ProductCategoryIDText": combo["category_name"],
        "UsageUnitID": combo["unit_id"],
        "UsageUnitIDText": combo["unit_name"],
        "MinimumStock": 0,
        "ProductName": combo["name"],
        "SaleDescription": combo.get("sale_description"),
        "BrandID": None,
        "BrandIDText": "",
        "UnitPrice": float(combo.get("sale_price") or 0.0),
        "UnitPrice2": 0,
        "PurchasedPrice": float(combo.get("cost_price") or 0.0),
        "TaxID": str(combo["tax_id"]),
        "TaxIDText": combo["tax_name"],
        "UnitCost": float(combo.get("cost_price") or 0.0),
        "UnitPrice1": 0,
        "UnitPriceFixed": float(combo.get("sale_price") or 0.0),
        "PriceAfterTax": False,
        "IsUseTax": False,
        "WarrantyPeriodTypeID": 2,
        "WarrantyPeriodTypeIDText": "Tháng",
        "WarrantyPeriodText": "0 Tháng",
        "WarrantyPeriod": 0,
        "WarrantyDescription": None,
        "Height": 0,
        "Length": 0,
        "Weight": 0,
        "Width": 0,
        "Radius": 0,
        "Description": combo.get("description"),
        "IsPublic": False,
        "SearchKeywords": None,
        "Inactive": False,
        "FormLayoutID": combo.get("form_layout_id", 128),
        "FormLayoutIDText": combo.get("form_layout_name", "Combo hàng hóa"),
        "MappingDatas": [],
        "MISAEntityState": 1,
        "ModifiedDate": None,
        "FormModeState": 1,
        "IsGetFieldFormLayout": True,
        "IsSetProduct": "1",
        "CustomTables": _set_product_table(
            rows, [], sum(row["Amount"] for row in rows)),
        "IsProductChange": True,
        "IsMultiCurrency": False,
    }


def diff_combo_rows(old_rows, components):
    """So dòng con hiện có với danh sách mới, gán trạng thái từng dòng.

    Nhận:
        old_rows: dòng con hiện tại từ GetDataSubFormByID (có ID, AsyncID, ProductID, Amount).
        components: danh sách MỚI đầy đủ, đã tra trên CRM (misa_id, code, name, quantity,
            unit_id, unit_name). Hàng nào không có trong danh sách mới là bị xoá.
    Trả: ``(data_rows, old_data, amount_summary, changes)``
        changes = ``{'added': [(code, qty)], 'removed': [(code, qty)],
                     'changed': [(code, old_qty, new_qty)]}`` để báo người dùng / ghi log.
    Biên: một hàng xuất hiện nhiều dòng trong combo cũ -> dòng đầu được giữ/sửa, các dòng
        sau bị xoá (gộp về một dòng, giống cách tạo combo gộp mã trùng).
    """
    wanted = {}
    order = []
    for component in components:
        key = int(component["misa_id"])
        if key not in wanted:
            order.append(key)
            wanted[key] = component

    kept_rows, deleted_rows, old_data, matched = [], [], [], set()
    changes = {"added": [], "removed": [], "changed": []}
    for row in old_rows:
        old_data.append(_existing_row(row, ROW_UNCHANGED))
        key = int(row.get("ProductID"))
        old_qty = float(row.get("Amount") or 0.0)
        code = (row.get("ProductCode") or "").strip()
        if key in wanted and key not in matched:
            matched.add(key)
            new_qty = float(wanted[key]["quantity"])
            if abs(new_qty - old_qty) <= _QTY_EPSILON:
                kept_rows.append(_existing_row(row, ROW_UNCHANGED))
            else:
                kept_rows.append(_existing_row(row, ROW_CHANGED, new_qty))
                changes["changed"].append((code, old_qty, new_qty))
        else:
            deleted_rows.append(_existing_row(row, ROW_DELETED))
            changes["removed"].append((code, old_qty))

    added_rows = []
    for key in order:
        if key not in matched:
            component = wanted[key]
            added_rows.append(new_component_row(component))
            changes["added"].append((component["code"].strip(), float(component["quantity"])))

    # Thứ tự giống màn hình CRM: dòng giữ/sửa, dòng thêm, dòng xoá ở cuối.
    data_rows = kept_rows + added_rows + deleted_rows
    amount_summary = sum(row["Amount"] for row in data_rows if row["MISAEntityState"] != ROW_DELETED)
    return data_rows, old_data, amount_summary, changes


# Khoá phần đầu combo chép từ CurrentData (FormDataNew) sang payload sửa, đúng như màn
# hình CRM gửi. Thiếu khoá nào MISA có thể hiểu là xoá giá trị đó.
_HEADER_KEYS = (
    "ProductCode", "ProductCategoryID", "ProductCategoryIDText", "UsageUnitID",
    "UsageUnitIDText", "MinimumStock", "ProductName", "SaleDescription", "BrandID",
    "UnitPrice", "UnitPrice2", "PurchasedPrice", "TaxID", "TaxIDText", "UnitCost",
    "UnitPrice1", "UnitPriceFixed", "PriceAfterTax", "IsUseTax", "WarrantyPeriodTypeID",
    "WarrantyPeriodTypeIDText", "WarrantyPeriodText", "WarrantyDescription", "Description",
    "IsPublic", "SearchKeywords", "Inactive", "FormLayoutID", "FormLayoutIDText",
)
_ZERO_IF_NULL = ("WarrantyPeriod", "Height", "Length", "Weight", "Width", "Radius")


def build_combo_update_payload(current, data_rows, old_data, amount_summary, overrides=None):
    """Payload SỬA combo.

    Nhận: ``current`` = CurrentData của FormDataNew (để giữ nguyên mọi trường không sửa,
        kèm ModifiedDate / Version cho MISA kiểm có ai sửa xen giữa không); dòng con từ
        diff_combo_rows; ``overrides`` = trường phần đầu cần đổi (vd ``{'ProductName': ...}``).
    Trả: dict JSON gửi thẳng lên CRM.
    """
    payload = {key: current.get(key) for key in _HEADER_KEYS}
    payload.update({key: current.get(key) or 0 for key in _ZERO_IF_NULL})
    payload["BrandIDText"] = current.get("BrandIDText") or ""
    payload.update(overrides or {})
    payload.update({
        "Fields": [],
        "FieldsCustom": [],
        "DataCustom": {"Avatar": ""},
        "MappingDatas": [],
        "MISAEntityState": 2,
        "ID": str(current["ID"]),
        "ModifiedDate": current.get("ModifiedDate"),
        "Version": current.get("Version") or 0,
        "FormModeState": 2,
        "IsGetFieldFormLayout": True,
        "IsSetProduct": True,
        "CustomTables": _set_product_table(data_rows, old_data, amount_summary),
        "IsProductChange": True,
        "IsMultiCurrency": False,
    })
    return payload
