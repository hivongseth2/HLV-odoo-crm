"""Phân loại nguồn hàng và chấm mức nghi ngờ cho module điều tra tồn kho.

Thuần: chỉ nhận kiểu dữ liệu cơ bản, trả dict/str. Không đụng self.env, không
đụng recordset — người gọi tự bóc field ra rồi đưa vào đây.
"""

# Thang nghi ngờ: 0 bình thường, 1 để ý, 2 nghi ngờ, 3 báo động.
SEV_OK = 0
SEV_INFO = 1
SEV_WARN = 2
SEV_ALERT = 3

SEVERITY_CODE = {SEV_OK: "ok", SEV_INFO: "info", SEV_WARN: "warn", SEV_ALERT: "alert"}
SEVERITY_LABEL = {
    SEV_OK: "Bình thường",
    SEV_INFO: "Để ý",
    SEV_WARN: "Nghi ngờ",
    SEV_ALERT: "Báo động",
}

# usage của stock.location -> (mã nguồn, nhãn, mức nghi ngờ, có truy ngược tiếp không)
_USAGE_SOURCE = {
    "supplier": ("mua", "Nhập mua từ nhà cung cấp", SEV_OK, False),
    "customer": ("khach_tra", "Nhận về từ khách hàng", SEV_INFO, False),
    "production": ("san_xuat", "Sản xuất / tháo lắp ra", SEV_OK, False),
    "inventory": ("dieu_chinh", "Điều chỉnh kiểm kho", SEV_ALERT, False),
    "internal": ("noi_bo", "Chuyển từ vị trí nội bộ", SEV_OK, True),
    "transit": ("trung_chuyen", "Về từ vị trí trung chuyển", SEV_INFO, True),
    "view": ("view", "Vị trí view (không nên có hàng)", SEV_WARN, False),
}

_UNKNOWN_SOURCE = ("khac", "Nguồn không xác định", SEV_WARN, False)

# Mã bất thường -> nhãn + giải thích. Dùng chung cho cả trang điều tra lẫn
# trang quét, để một lỗi chỉ có đúng một tên gọi trong toàn hệ thống.
ANOMALY_META = {
    "lech_so_sach": {
        "label": "Lệch sổ sách",
        "severity": SEV_ALERT,
        "explain": "Tồn thực tế trong stock.quant khác tổng cộng dồn các move đã "
                   "hoàn tất. Hàng vào/ra vị trí này bằng con đường không phải move: "
                   "sửa thẳng DB, import hỏng, hoặc move bị xoá.",
    },
    "xuat_khong_nguon": {
        "label": "Xuất nhiều hơn đã nhập",
        "severity": SEV_ALERT,
        "explain": "Có lượt xuất khỏi vị trí mà trước đó không hề có lượt nhập nào "
                   "đủ bù. Sổ cái của vị trí này không tự nhất quán.",
    },
    "nhap_tu_dieu_chinh": {
        "label": "Hàng đến từ điều chỉnh kiểm kho",
        "severity": SEV_ALERT,
        "explain": "Lượng đang tồn có nguồn là một lần chỉnh tồn thủ công, tức hàng "
                   "xuất hiện mà không có phiếu nhập nào đứng sau.",
    },
    "move_khong_phieu": {
        "label": "Move không gắn phiếu",
        "severity": SEV_WARN,
        "explain": "Move đưa hàng vào không thuộc phiếu kho nào và cũng không có "
                   "chứng từ gốc — thường là thao tác tay hoặc script chạy thẳng.",
    },
    "ton_dong_trung_chuyen": {
        "label": "Tồn đọng ở vị trí trung chuyển",
        "severity": SEV_WARN,
        "explain": "Vị trí này (Input/QC/Đóng gói/Output) chỉ để hàng đi ngang qua. "
                   "Hàng nằm lại lâu nghĩa là một phiếu đã dở dang hoặc bị bỏ quên.",
    },
    "ton_am": {
        "label": "Tồn âm",
        "severity": SEV_ALERT,
        "explain": "Vị trí nội bộ đang giữ số lượng âm: đã xuất hàng chưa từng nhập.",
    },
    "giu_cho_vuot_ton": {
        "label": "Giữ chỗ vượt tồn",
        "severity": SEV_WARN,
        "explain": "Lượng giữ chỗ lớn hơn lượng thực có — phiếu khác sẽ không lấy "
                   "được hàng dù nhìn vào vẫn thấy còn.",
    },
    "ngay_lui": {
        "label": "Move ghi lùi ngày",
        "severity": SEV_WARN,
        "explain": "Ngày hiệu lực của move sớm hơn hẳn lúc nó được tạo. Hàng 'xuất "
                   "hiện' ở một kỳ đã chốt, làm lệch mọi báo cáo theo thời gian.",
    },
    "mat_dau_vet": {
        "label": "Mất dấu vết khi truy ngược",
        "severity": SEV_ALERT,
        "explain": "Truy ngược đến vị trí nguồn thì không tìm được lượt nhập nào "
                   "tương ứng — chuỗi nguồn gốc đứt tại đây.",
    },
}


def classify_source(usage, is_inventory=False, is_scrap=False,
                    has_picking=True, has_origin=True):
    """Xác định hàng vào một vị trí là từ đâu và đáng ngờ tới mức nào.

    Nhận: usage (str, stock.location.usage của vị trí nguồn), is_inventory
    (move.is_inventory), is_scrap (vị trí nguồn là kho phế liệu), has_picking /
    has_origin (move có phiếu / có chứng từ gốc không).

    Trả dict {"code", "label", "severity", "recurse", "notes"}: `recurse` là
    True khi nguồn vẫn nằm trong kho mình, tức còn truy ngược tiếp được;
    `notes` là list chuỗi giải thích thêm, có thể rỗng.

    Biên: usage lạ hoặc rỗng -> code "khac", severity SEV_WARN, recurse False.
    """
    notes = []
    if is_inventory:
        code, label, severity, recurse = _USAGE_SOURCE["inventory"]
    elif is_scrap:
        code, label, severity, recurse = "phe_lieu", "Lấy ngược từ kho phế liệu", SEV_WARN, False
    else:
        code, label, severity, recurse = _USAGE_SOURCE.get(usage or "", _UNKNOWN_SOURCE)

    # Move trôi nổi không phiếu không chứng từ: tự nó chưa sai, nhưng cộng với
    # một nguồn vốn đã đáng ngờ thì đó là thứ cần mở ra xem đầu tiên.
    if not has_picking and not has_origin and code not in ("dieu_chinh",):
        severity = min(SEV_ALERT, severity + 1)
        notes.append("Không gắn phiếu kho và không có chứng từ gốc")
    elif not has_picking:
        notes.append("Không gắn phiếu kho")

    return {
        "code": code,
        "label": label,
        "severity": severity,
        "recurse": recurse,
        "notes": notes,
    }


def anomaly(code, detail="", severity=None):
    """Dựng một dòng bất thường chuẩn từ mã trong ANOMALY_META.

    Nhận mã bất thường, chuỗi chi tiết của trường hợp cụ thể, và mức nghi ngờ
    ghi đè (để hạ mức khi trường hợp nhẹ). Trả dict {"code", "label",
    "severity", "severity_code", "explain", "detail"}.

    Biên: mã lạ -> label chính là mã, explain rỗng, severity mặc định SEV_WARN.
    """
    meta = ANOMALY_META.get(code, {"label": code, "severity": SEV_WARN, "explain": ""})
    sev = meta["severity"] if severity is None else severity
    return {
        "code": code,
        "label": meta["label"],
        "severity": sev,
        "severity_code": SEVERITY_CODE.get(sev, "warn"),
        "explain": meta["explain"],
        "detail": detail,
    }


def worst_severity(items):
    """Mức nghi ngờ cao nhất trong một list dict có khoá "severity".

    Biên: list rỗng -> SEV_OK.
    """
    return max([int(i.get("severity") or 0) for i in items], default=SEV_OK)


def fmt_qty(value, digits=2):
    """Số lượng gọn: bỏ đuôi .00, giữ tối đa `digits` chữ số thập phân.

    Biên: None -> "0".
    """
    number = round(float(value or 0.0), digits)
    if number == int(number):
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0")


def age_label(days):
    """Nhãn tuổi tiếng Việt từ số ngày. Biên: None -> "" ; < 1 -> "hôm nay"."""
    if days is None:
        return ""
    days = int(days)
    if days < 1:
        return "hôm nay"
    if days < 30:
        return f"{days} ngày"
    if days < 365:
        return f"{days // 30} tháng"
    return f"{days // 365} năm"


def build_verdict(origins, anomalies, unexplained, qty_text, uom_text=""):
    """Một câu kết luận tiếng Việt cho kết quả điều tra một vị trí.

    Nhận: origins (list node nguồn gốc, node có "qty", "label", "date_str",
    "reference", "children"), anomalies (list dict từ `anomaly`), unexplained
    (float lượng không truy được nguồn), qty_text/uom_text để ghép câu.

    Trả chuỗi. Biên: không có origin nào -> câu báo không truy được nguồn.
    """
    unit = f" {uom_text}" if uom_text else ""
    if unexplained > 0.001 and not origins:
        return (f"Không truy được nguồn cho {qty_text}{unit} đang tồn: lịch sử move "
                f"không giải thích được lượng này.")
    if not origins:
        return "Vị trí này không còn tồn để truy nguồn."

    main = max(origins, key=lambda n: n.get("qty") or 0.0)
    deepest = main
    while deepest.get("children"):
        deepest = max(deepest["children"], key=lambda n: n.get("qty") or 0.0)

    where = main.get("reference") or main.get("label") or "move không tên"
    parts = [f"{qty_text}{unit} ở đây vào kho qua {where} ngày {main.get('date_str') or '?'}"]
    if deepest is not main:
        root_ref = deepest.get("reference") or ""
        parts.append(f"gốc xa nhất truy được là {deepest.get('label')}"
                     + (f" ({root_ref})" if root_ref else "")
                     + f" ngày {deepest.get('date_str') or '?'}")
    else:
        parts.append(f"nguồn là {main.get('label')}")

    alerts = [a["label"] for a in anomalies if a.get("severity", 0) >= SEV_WARN]
    if alerts:
        parts.append("cần xem lại: " + ", ".join(sorted(set(alerts))))
    if unexplained > 0.001:
        parts.append(f"còn {fmt_qty(unexplained)}{unit} không truy được nguồn")
    return "; ".join(parts) + "."
