# -*- coding: utf-8 -*-
"""Chọn cổng (gateway) API của MISA CRM.

MISA chạy cùng một API sau nhiều cổng (``/crm/g1/...``, ``/crm/g2/...``) và tự dời các
màn hình qua lại giữa chúng. Một cổng có lúc trả lỗi máy chủ (HTTP 5xx, hoặc HTTP 200
với ``Code: 500`` không kèm lý do) trong khi cổng kia chạy bình thường — nên không ghim
cứng một cổng mà thử lần lượt.

Util thuần: không gọi mạng, không đụng ``self.env``.
"""

CRM_BASE = "https://amisapp.misa.vn/crm"
CRM_GATEWAYS = ("g1", "g2")


def crm_url(gateway, path):
    """URL đầy đủ. Nhận cổng ('g1'...) và đường dẫn sau ``api/business/`` (vd 'Product')."""
    return "%s/%s/api/business/%s" % (CRM_BASE, gateway, path.lstrip("/"))


def gateway_order(preferred):
    """Thứ tự thử: cổng chạy được lần gần nhất trước, các cổng còn lại sau.

    Biên: preferred rỗng / lạ -> thứ tự mặc định CRM_GATEWAYS.
    """
    if preferred not in CRM_GATEWAYS:
        return list(CRM_GATEWAYS)
    return [preferred] + [g for g in CRM_GATEWAYS if g != preferred]


def is_gateway_failure(status_code, data):
    """Lỗi do cổng / máy chủ MISA (đáng thử cổng khác), không phải do dữ liệu mình gửi.

    Nhận: HTTP status, body đã parse (dict, hoặc None nếu không phải JSON).
    Trả True khi HTTP >= 500, body không phải JSON, hoặc ``Success`` false với
    ``Code >= 500`` mà không có ``ValidateInfo`` (CRM văng lỗi, không chỉ ra trường sai).
    Biên: 401 / 403 (hết phiên) và lỗi kiểm dữ liệu -> False: đổi cổng không giải quyết được.
    """
    if status_code in (401, 403):
        return False
    if status_code >= 500 or not isinstance(data, dict):
        return True
    if data.get("Success"):
        return False
    try:
        code = int(data.get("Code") or 0)
    except (TypeError, ValueError):
        code = 0
    return code >= 500 and not data.get("ValidateInfo")
