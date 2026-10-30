# -*- coding: utf-8 -*-
"""Khai báo tool MISA CRM cho trợ lý quản trị (định dạng Messages API).

Chỉ là schema: tool thật chạy ở hlv.admin.agent.crm.tools, gọi hlv.misa.crm.connect. Tham số đặt
đúng tên như body của /api/misa-crm/* để kiểm bằng chính body_fields của hlv_misa_crm_connect.
"""

_KEYWORD = {"type": "string", "description": "Từ khoá (kiểu 'chứa'): ngắn thì dễ ra hơn"}
_LIMIT = {"type": "integer", "description": "Số kết quả tối đa (1-50), mặc định 10"}
_ID = {"type": "integer", "description": "ID trên MISA (lấy từ kết quả tìm, không tự bịa)"}
_DATE = {"type": "string", "description": "Ngày dạng YYYY-MM-DD"}

_LINES = {
    "type": "array",
    "description": (
        "Dòng hàng. Mỗi dòng: mã ĐÚNG như MISA, SL > 0, và đúng MỘT trong price_after_tax (đơn giá "
        "SAU VAT — ưu tiên) hoặc price (đơn giá chưa VAT). Combo: một dòng mã combo, giá cả bộ — Odoo "
        "tự thêm các dòng mã con (tiền 0) như form MISA."
    ),
    "items": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Mã hàng đúng như MISA"},
            "qty": {"type": "number", "description": "Số lượng (> 0)"},
            "price_after_tax": {"type": "number", "description": "Đơn giá sau VAT (VNĐ)"},
            "price": {"type": "number", "description": "Đơn giá chưa VAT (VNĐ) — chỉ khi không có giá sau VAT"},
            "description": {"type": "string", "description": "Diễn giải dòng (tuỳ chọn)"},
            "customer_item": {"type": "string", "description": "Báo giá: tên hàng theo cách khách gọi (tuỳ chọn)"},
        },
        "required": ["code", "qty"],
    },
    "minItems": 1,
}

_QUOTE_HEADER = {
    "quote_date": dict(_DATE, description="Ngày báo giá YYYY-MM-DD (bỏ trống = hôm nay)"),
    "expired_date": dict(_DATE, description="Ngày hết hiệu lực YYYY-MM-DD"),
    "description": {"type": "string", "description": "Diễn giải / ghi chú báo giá"},
    "payment_terms": {"type": "string", "description": "Điều khoản thanh toán"},
    "validity_days": {"type": "string", "description": "Hiệu lực báo giá (vd '15 ngày')"},
    "delivery_days": {"type": "string", "description": "Thời gian giao hàng (vd '3-5 ngày')"},
    "prepaid": {"type": "number", "description": "Số tiền khách trả trước (VNĐ)"},
    "shipping_cost": {"type": "number", "description": "Phí vận chuyển (VNĐ) — MISA bắt buộc khi tạo, không có thì 0"},
    "commission_percent": {"type": "number", "description": "Hoa hồng (%) — MISA bắt buộc khi tạo, không có thì 0"},
}

_WRITE_NOTE = (
    " CHỈ GỌI sau khi người dùng xác nhận OK cho đúng đề xuất ở câu trả lời trước. Các ID và mã "
    "hàng gửi lên phải có NGUYÊN VĂN trong đề xuất đó, không thì trả 'need_confirmation'."
)


def _tool(name, description, properties=None, required=()):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
        },
    }


CRM_READ_TOOLS = [
    _tool("crm_tim_khach", "Tìm khách hàng trên MISA CRM theo tên / MST / mã KH / SĐT / địa chỉ.",
          {"keyword": _KEYWORD, "limit": _LIMIT}, ["keyword"]),
    _tool("crm_xem_khach", "Xem một khách trên MISA CRM (MST, địa chỉ, SĐT, email).",
          {"id": _ID}, ["id"]),
    _tool("crm_tim_hang",
          "Tìm hàng trên MISA CRM theo mã / tên. chi_hang_con_ton=true: chỉ hàng còn tồn (kèm tồn, không combo).",
          {"keyword": _KEYWORD, "limit": _LIMIT,
           "chi_hang_con_ton": {"type": "boolean", "description": "true = chỉ hàng còn tồn"}},
          ["keyword"]),
    _tool("crm_gia_cho_khach",
          "Giá gợi ý khi chọn hàng cho một khách: bảng giá áp cho khách + giá bán gần nhất. Cần ID hàng "
          "MISA (từ crm_tim_hang).",
          {"account_id": dict(_ID, description="ID khách (bỏ trống = chỉ lấy thông tin hàng)"),
           "product_ids": {"type": "array", "items": {"type": "integer"}, "description": "ID hàng MISA"}},
          ["product_ids"]),
    _tool("crm_danh_muc_co_hoi", "Danh sách giai đoạn cơ hội (kèm % thành công) và nguồn gốc — lấy ID để tạo / sửa."),
    _tool("crm_tim_co_hoi", "Tìm cơ hội theo số cơ hội, tên, khách.",
          {"keyword": _KEYWORD, "limit": _LIMIT}, ["keyword"]),
    _tool("crm_xem_hang_co_hoi", "Hàng của một cơ hội.", {"id": _ID}, ["id"]),
    _tool("crm_danh_muc_bao_gia", "Danh sách tình trạng báo giá — lấy ID cho stage_id."),
    _tool("crm_tim_bao_gia", "Tìm báo giá theo số báo giá (BG...), tên khách.",
          {"keyword": _KEYWORD, "limit": _LIMIT}, ["keyword"]),
    _tool("crm_xem_hang_bao_gia", "Hàng của một báo giá.", {"id": _ID}, ["id"]),
    _tool("crm_tim_don_hang", "Tìm đơn hàng MISA CRM theo số đơn, tên khách.",
          {"keyword": _KEYWORD, "limit": _LIMIT}, ["keyword"]),
    _tool("crm_xem_hang_don_hang", "Hàng của một đơn hàng MISA CRM.", {"id": _ID}, ["id"]),
]

CRM_WRITE_TOOLS = [
    _tool("crm_tao_co_hoi",
          "Tạo cơ hội trên MISA CRM kèm hàng. Người phụ trách = tài khoản MISA Odoo đang đăng nhập." + _WRITE_NOTE,
          {"account_id": dict(_ID, description="ID khách"),
           "closing_date": dict(_DATE, description="Ngày dự kiến chốt YYYY-MM-DD"),
           "stage_id": dict(_ID, description="ID giai đoạn (crm_danh_muc_co_hoi), bỏ trống = giai đoạn đầu"),
           "lead_source_id": dict(_ID, description="ID nguồn gốc (tuỳ chọn)"),
           "name": {"type": "string", "description": "Tên cơ hội (bỏ trống = MISA tự đặt)"},
           "description": {"type": "string", "description": "Mô tả (tuỳ chọn)"},
           "lines": _LINES},
          ["account_id", "closing_date", "lines"]),
    _tool("crm_sua_co_hoi",
          "Sửa cơ hội: chỉ gửi trường cần đổi. Gửi lines là THAY toàn bộ hàng cũ." + _WRITE_NOTE,
          {"id": dict(_ID, description="ID cơ hội"), "name": {"type": "string"},
           "stage_id": _ID, "closing_date": _DATE, "lead_source_id": _ID,
           "description": {"type": "string"}, "lines": _LINES},
          ["id"]),
    _tool("crm_tao_bao_gia",
          "Tạo báo giá trên MISA CRM kèm hàng; gắn vào cơ hội nếu có opportunity_id." + _WRITE_NOTE,
          dict(_QUOTE_HEADER, account_id=dict(_ID, description="ID khách"),
               opportunity_id=dict(_ID, description="ID cơ hội để gắn (tuỳ chọn)"),
               stage_id=dict(_ID, description="ID tình trạng (bỏ trống = Bản thảo)"), lines=_LINES),
          ["account_id", "lines", "shipping_cost", "commission_percent"]),
    _tool("crm_tao_bao_gia_tu_co_hoi",
          "Tạo báo giá từ một cơ hội: chép khách + hàng (SL, giá, thuế, chiết khấu) của cơ hội." + _WRITE_NOTE,
          dict(_QUOTE_HEADER, opportunity_id=dict(_ID, description="ID cơ hội"),
               stage_id=dict(_ID, description="ID tình trạng (bỏ trống = Bản thảo)")),
          ["opportunity_id", "shipping_cost", "commission_percent"]),
    _tool("crm_sua_bao_gia",
          "Sửa báo giá: chỉ gửi trường cần đổi. Gửi lines là THAY toàn bộ hàng cũ." + _WRITE_NOTE,
          dict(_QUOTE_HEADER, id=dict(_ID, description="ID báo giá"), stage_id=_ID, lines=_LINES),
          ["id"]),
]

CRM_TOOLS = CRM_READ_TOOLS + CRM_WRITE_TOOLS
CRM_TOOL_NAMES = frozenset(tool["name"] for tool in CRM_TOOLS)
CRM_WRITE_TOOL_NAMES = frozenset(tool["name"] for tool in CRM_WRITE_TOOLS)

_WRITE_LABELS = {
    "crm_tao_co_hoi": "Đã tạo cơ hội",
    "crm_sua_co_hoi": "Đã sửa cơ hội",
    "crm_tao_bao_gia": "Đã tạo báo giá",
    "crm_tao_bao_gia_tu_co_hoi": "Đã tạo báo giá (từ cơ hội)",
    "crm_sua_bao_gia": "Đã sửa báo giá",
}


def crm_event_text(name, result):
    """Dòng ghi chú hệ thống sau một lệnh ghi CRM thành công.

    Nhận: tên tool ghi, dict kết quả (``id``, ``code``, ``total``, ``warning``? của hlv.misa.crm.connect).
    Trả: vd "Đã tạo báo giá BG00123 trên MISA (ID 456, tổng 1.200.000 đ)".
    Biên: thiếu số chứng từ -> bỏ phần số; thiếu tổng -> bỏ phần tổng.
    """
    parts = ["ID %s" % result.get("id")]
    total = result.get("total")
    if isinstance(total, (int, float)):
        parts.append("tổng %s đ" % "{:,.0f}".format(total).replace(",", "."))
    code = (" %s" % result["code"]) if result.get("code") else ""
    text = "%s%s trên MISA (%s)" % (_WRITE_LABELS.get(name, name), code, ", ".join(parts))
    if result.get("warning"):
        text += ". Lưu ý: %s" % result["warning"]
    return text


def write_tool_proposal_values(name, args):
    """Các giá trị lệnh ghi CRM phải có nguyên văn trong đề xuất trước.

    Nhận: tên tool ghi, dict tham số Claude gửi.
    Trả: list chuỗi — ID khách / cơ hội / báo giá và mã hàng từng dòng. Giá và SL không đòi
        (Claude viết 1.200.000 hay 1200000 đều đúng, so nguyên văn sẽ chặn oan).
    Biên: tham số thiếu / sai kiểu -> bỏ qua giá trị đó (bước kiểm body báo lỗi sau).
    """
    keys = {
        "crm_tao_co_hoi": ("account_id",),
        "crm_sua_co_hoi": ("id",),
        "crm_tao_bao_gia": ("account_id", "opportunity_id"),
        "crm_tao_bao_gia_tu_co_hoi": ("opportunity_id",),
        "crm_sua_bao_gia": ("id",),
    }.get(name, ())
    values = [str(args[key]) for key in keys if isinstance(args.get(key), (int, str)) and args.get(key) != ""]
    lines = args.get("lines")
    if isinstance(lines, list):
        values += [line["code"] for line in lines if isinstance(line, dict) and isinstance(line.get("code"), str)]
    return values
