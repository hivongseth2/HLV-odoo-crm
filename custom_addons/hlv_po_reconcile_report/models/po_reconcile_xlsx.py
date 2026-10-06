# -*- coding: utf-8 -*-
"""Port Python của excel_export.js (extension MISA-Odoo): dựng file Excel đối chiếu PO.
Không import odoo để test độc lập được: python po_reconcile_xlsx.py
"""
import io

import xlsxwriter

COLORS = {
    "critical": "#FFCCCC", "warning": "#FFF2CC", "header": "#4472C4", "white": "#FFFFFF",
    "title": "#2F5496", "section_bg": "#E2EFDA", "section_text": "#375623",
    "stripe1": "#FFFFFF", "stripe2": "#F2F7FB", "diff": "#FFF2CC", "matched": "#CCFFCC",
    "text_critical": "#CC0000", "muted": "#666666",
}
STATUS_LABELS = {
    "matched": "Khớp hoàn toàn", "missing_in_misa": "Thiếu trên MISA", "missing_in_odoo": "Thiếu trên Odoo",
    "qty_mismatch": "Lệch số lượng", "price_mismatch": "Lệch đơn giá", "qty_price_mismatch": "Lệch SL & ĐG",
    "tax_diff": "Lệch tiền thuế", "diff": "Có sai lệch",
}
SEVERITY_LABELS = {"critical": "Nghiêm trọng", "warning": "Cảnh báo", "info": "Thông tin"}
NUM = "#,##0.##"
# (key, header, width, align, num_format)
COLS = [
    ("stt", "STT", 5, "center", None), ("po_name", "Mã Đơn", 20, None, None), ("origin", "Mã Gốc", 18, None, None),
    ("partner", "NCC", 22, None, None), ("date", "Ngày ĐH", 13, "center", None),
    ("status", "Trạng Thái", 20, None, None), ("severity", "Mức Độ", 15, "center", None),
    ("product", "Mã SP", 28, None, None), ("prod_name", "Tên SP", 28, None, None), ("uom_name", "ĐVT", 10, "center", None),
    ("qty_ordered_odoo", "SL Đặt Odoo", 15, "right", NUM), ("qty_ordered_amis", "SL Đặt AMIS", 15, "right", NUM),
    ("qty_odoo", "SL Nhập Odoo", 15, "right", NUM), ("qty_amis", "SL Nhập AMIS", 15, "right", NUM),
    ("price_odoo", "ĐG Odoo", 16, "right", NUM), ("price_amis", "ĐG AMIS", 16, "right", NUM),
    ("vat_odoo", "Thuế % Odoo", 15, "right", None), ("vat_amis", "Thuế % AMIS", 15, "right", None),
    ("tax_odoo", "Thuế Odoo", 15, "right", NUM), ("tax_amis", "Thuế AMIS", 15, "right", NUM),
    ("receipt", "Lịch sử nhập kho", 45, None, None),
]
KEY_IDX = {c[0]: i for i, c in enumerate(COLS)}
# Cặp cột so sánh (key1, key2, ngưỡng) — giống checkDiff trong JS
DIFF_PAIRS = [
    ("qty_ordered_odoo", "qty_ordered_amis", 0.001), ("qty_odoo", "qty_amis", 0.001),
    ("qty_ordered_odoo", "qty_odoo", 0.001), ("qty_ordered_amis", "qty_amis", 0.001),
    ("price_odoo", "price_amis", 100), ("vat_odoo", "vat_amis", 0.01), ("tax_odoo", "tax_amis", 100),
]


def _product_rows(item):
    """Ghép dòng Odoo với dòng AMIS cùng mã (mỗi dòng AMIS match 1 dòng Odoo chưa match)."""
    rows = []
    for ol in (item.get("odoo") or {}).get("lines") or []:
        rows.append({
            "code": ol.get("code"), "product": ol.get("orig_code") or ol.get("code"),
            "prod_name": ol.get("name") or "", "uom_name": ol.get("uom_name") or "",
            "qty_ordered_odoo": ol.get("qty") or 0, "qty_odoo": ol.get("qty_received") or 0,
            "price_odoo": ol.get("price_unit") or 0, "tax_odoo": ol.get("price_tax") or 0,
            "vat_odoo": ol.get("vat_rate") or 0,
            "receipt": "; ".join("%s (%s): %s" % (r["picking"], r["date"], r["qty"]) for r in ol.get("receipt_history") or []),
            "_matched": False,
        })
    for al in (item.get("amis") or {}).get("lines") or []:
        amis_vals = {
            "qty_ordered_amis": al.get("qty") or 0, "qty_amis": al.get("qty_receipt") or 0,
            "price_amis": al.get("price_unit") or 0, "tax_amis": al.get("price_tax") or 0,
            "vat_amis": al.get("vat_rate") or 0,
        }
        row = next((r for r in rows if r["code"] == al.get("code") and not r["_matched"]), None)
        if row:
            row.update(amis_vals, _matched=True)
        else:
            rows.append(dict(amis_vals, code=al.get("code"), product=al.get("orig_code") or al.get("code"),
                             prod_name=al.get("name") or "", qty_ordered_odoo=0, qty_odoo=0, price_odoo=0,
                             tax_odoo=0, vat_odoo=0, receipt="", _matched=True))
    for row in rows:
        if not row["_matched"]:
            row.update(qty_ordered_amis=0, qty_amis=0, price_amis=0, tax_amis=0, vat_amis=0)
    return rows


def build_reconcile_xlsx(res, date_from, date_to):
    """res = dict trả về từ MisaExtensionController._reconcile_po_only_data. Trả về bytes .xlsx."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    cache = {}

    def fmt(**props):
        key = tuple(sorted(props.items()))
        if key not in cache:
            cache[key] = wb.add_format(props)
        return cache[key]

    # ===== SHEET 1: TỔNG HỢP =====
    ws = wb.add_worksheet("Tổng hợp")
    ws.freeze_panes(2, 0)
    ws.set_column(0, 0, 45)
    ws.set_column(1, 1, 15)
    ws.set_row(0, 35)
    ws.merge_range(0, 0, 0, 1, "BÁO CÁO ĐỐI CHIẾU ĐƠN MUA HÀNG",
                   fmt(bold=True, font_size=16, font_color=COLORS["white"], bg_color=COLORS["title"]))
    ws.merge_range(1, 0, 1, 1, "Khoảng thời gian: %s → %s" % (date_from, date_to),
                   fmt(font_color=COLORS["muted"], font_size=11))
    summary = res.get("summary") or {}
    r = 3
    if not summary.get("by_status"):
        ws.write(r, 0, "Không có dữ liệu tổng hợp")
    else:
        sev_map = {"critical": "Critical - Cần xử lý ngay", "warning": "Warning - Cần kiểm tra", "info": "Info - Thông tin"}
        sections = [
            ("TỔNG HỢP", [("Tổng số đơn Odoo", summary.get("total_odoo") or 0),
                          ("Tổng số đơn MISA", summary.get("total_misa") or 0)]),
            ("PHÂN LOẠI THEO TRẠNG THÁI", [(STATUS_LABELS.get(k, k), v) for k, v in summary["by_status"].items()]),
            ("MỨC ĐỘ NGHIÊM TRỌNG", [(sev_map.get(k, k), v) for k, v in (summary.get("by_severity") or {}).items()]),
        ]
        for title, rows in sections:
            ws.set_row(r, 28)
            ws.merge_range(r, 0, r, 1, title, fmt(bold=True, font_size=12, font_color=COLORS["section_text"],
                                                 bg_color=COLORS["section_bg"], border=1))
            r += 1
            for label, val in rows:
                stripe = COLORS["stripe1"] if (r + 1) % 2 == 0 else COLORS["stripe2"]
                ws.write(r, 0, label, fmt(bg_color=stripe, border=1))
                ws.write(r, 1, val, fmt(bg_color=stripe, border=1, bold=True, align="right"))
                r += 1
            r += 1

    # ===== SHEET 2: CHI TIẾT =====
    wd = wb.add_worksheet("Chi tiết")
    wd.freeze_panes(1, 0)
    wd.set_row(0, 25)
    head_fmt = fmt(bold=True, font_color=COLORS["white"], bg_color=COLORS["header"], align="center", valign="vcenter")
    for c, (_k, header, width, _a, _n) in enumerate(COLS):
        wd.set_column(c, c, width)
        wd.write(0, c, header, head_fmt)

    row_idx = 1  # 0-based; tương đương currentGroupStart - 1 trong JS
    for stt, item in enumerate(res.get("reconciled") or [], start=1):
        status = STATUS_LABELS.get(item.get("status") or "unknown", item.get("status") or "unknown")
        severity = SEVERITY_LABELS.get(item.get("severity") or "info", item.get("severity") or "info")
        if severity == "Nghiêm trọng" or "Thiếu" in status:
            group_fill = COLORS["critical"]
        elif severity == "Cảnh báo" or "Lệch" in status:
            group_fill = COLORS["warning"]
        elif "Khớp" in status:
            group_fill = COLORS["matched"]
        else:
            group_fill = COLORS["stripe1"]

        rows = []
        dup = item.get("duplicate_warning")
        if dup:
            rows.append({"product": "CẢNH BÁO: %s" % dup.get("message"), "prod_name": "Kiểm tra và xóa đơn trùng trên Odoo"})
        rows += _product_rows(item)
        if not rows:
            rows.append({})

        odoo = item.get("odoo") or {}
        head_vals = [stt, item.get("po_name") or "", item.get("po_origin") or "",
                     item.get("partner") or odoo.get("partner") or "",
                     item.get("date_order") or odoo.get("date_order") or "", status, severity]
        head_fmt_ = fmt(bold=True, font_size=10, bg_color=group_fill, border=1, valign="vcenter")
        for c, v in enumerate(head_vals):
            if len(rows) > 1:
                wd.merge_range(row_idx, c, row_idx + len(rows) - 1, c, v, head_fmt_)
            else:
                wd.write(row_idx, c, v, head_fmt_)

        stripe = COLORS["stripe1"] if (row_idx + 1) % 2 == 0 else COLORS["stripe2"]
        for i, p in enumerate(rows):
            wd.set_row(row_idx + i, 25)
            diff_cols = set()
            if not dup or i > 0:
                for k1, k2, thresh in DIFF_PAIRS:
                    v1, v2 = p.get(k1), p.get(k2)
                    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) and abs(v1 - v2) > thresh:
                        diff_cols.update((KEY_IDX[k1], KEY_IDX[k2]))
            for c in range(7, len(COLS)):
                key, _h, _w, align, num = COLS[c]
                props = {"font_size": 9, "border": 1, "bg_color": stripe}
                if align:
                    props["align"] = align
                if num:
                    props["num_format"] = num
                if c in diff_cols:
                    props.update(bg_color=COLORS["diff"], font_color=COLORS["text_critical"], bold=True)
                val = p.get(key)
                if val is None or val == "":
                    wd.write_blank(row_idx + i, c, None, fmt(**props))
                else:
                    wd.write(row_idx + i, c, val, fmt(**props))
        row_idx += len(rows)

    wb.close()
    return buf.getvalue()


if __name__ == "__main__":
    sample = {
        "summary": {"total_odoo": 2, "total_misa": 1, "by_status": {"qty_mismatch": 1, "missing_in_misa": 1},
                    "by_severity": {"warning": 1, "critical": 1}},
        "reconciled": [
            {"po_name": "P001", "status": "qty_mismatch", "severity": "warning",
             "duplicate_warning": {"message": "Odoo có nhiều PO cùng mã gốc: P001, P001-1."},
             "odoo": {"partner": "NCC A", "date_order": "2026-10-06", "lines": [
                 {"code": "a1", "orig_code": "A1", "name": "SP A", "qty": 10, "qty_received": 8, "price_unit": 1000,
                  "price_tax": 80, "vat_rate": 10, "receipt_history": [{"picking": "WH/IN/1", "date": "2026-10-06", "qty": 8}]}]},
             "amis": {"lines": [{"code": "a1", "orig_code": "A1", "qty": 10, "qty_receipt": 10, "price_unit": 1000,
                                 "price_tax": 100, "vat_rate": 10},
                                {"code": "b2", "orig_code": "B2", "name": "SP B", "qty": 1, "qty_receipt": 1}]}},
            {"po_name": "P002", "status": "missing_in_misa", "severity": "critical", "odoo": {"lines": []}},
        ],
    }
    rows = _product_rows(sample["reconciled"][0])
    assert [r["product"] for r in rows] == ["A1", "B2"], rows
    assert rows[0]["qty_amis"] == 10 and rows[0]["qty_odoo"] == 8
    assert rows[1]["qty_odoo"] == 0 and rows[1]["qty_amis"] == 1
    data = build_reconcile_xlsx(sample, "2026-10-06", "2026-10-06")
    assert data[:2] == b"PK" and len(data) > 1000
    print("ok", len(data), "bytes")
