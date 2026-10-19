# -*- coding: utf-8 -*-
"""Tìm đơn hàng trên MISA CRM cho ô "Mã đơn hàng của khách" của trang /hoi-gia-ncc (Cài đặt chọn nguồn MISA CRM).

Gọi CRM bằng token chung của misa_fetch_po_button (misa.api.utils._crm_read_call: hết hạn thì đăng nhập
lại một lần, lỗi → UserError đọc được), cùng cách tìm cơ hội / báo giá. Chỉ đọc.
"""
import base64
import uuid

GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/Grid"
_GRID_COLUMNS = "ID,SaleOrderNo,SaleOrderName,SaleOrderDate,AccountIDText,OwnerIDText"
ORDER_LIMIT = 20


def search_crm_sale_orders(misa, keyword, limit=ORDER_LIMIT):
    """misa: misa.api.utils (sudo). Đơn hàng CRM khớp keyword theo ô tìm của trang danh sách đơn (số DH…,
    tên khách…), mới sửa trước. Trả [{"crm_id" (chuỗi), "code", "partner", "date", "owner"}]; keyword rỗng → []."""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    rows = misa._crm_read_call(lambda headers: misa._post_crm_read(headers, GRID_URL, _grid_payload(keyword, limit),
                                                                   "saleorder"))
    return [
        {
            "crm_id": str(row["ID"]),
            "code": row.get("SaleOrderNo") or row.get("SaleOrderName") or "",
            "partner": row.get("AccountIDText") or "",
            "date": (row.get("SaleOrderDate") or "")[:10],
            "owner": row.get("OwnerIDText") or "",
        }
        for row in rows if row.get("ID")
    ]


def _grid_payload(keyword, limit):
    return {
        "Columns": base64.b64encode(_GRID_COLUMNS.encode("utf-8")).decode("ascii"),
        "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
        "Start": 0, "Page": 1, "PageSize": limit,
        "Filters": [], "Formula": "",
        "LayoutCode": "SaleOrder", "LayoutCodeCheckPermission": "SaleOrder",
        "DefaultTotal": True, "IsMappingData": False, "MappingValueObject": {},
        "IsApproved": False, "CustomPagingData": {}, "IsUsedELTS": True,
        "ListGmailPage": [], "ListFacebookPage": {}, "IsListPaging": True, "IsGetCache": True,
        "IsCheckInactive": False, "IsConverted": False, "SessionID": str(uuid.uuid4()),
        "AISearchKeyword": keyword, "SkipNormalSearch": False,
    }
