# -*- coding: utf-8 -*-
"""File Excel cho trang "Lịch sử báo giá" của NCC — đúng bảng đang xem, đủ mọi dòng (không phân trang).

Hàm thuần: nhận dữ liệu đã tính (vendor_history / history_utils), trả bytes .xlsx. Không đụng env.
"""

import io
import re

import xlsxwriter

from ..models.vendor_quote_utils import local_date_text

# Ký tự Excel cấm trong tên sheet — tên mặt hàng hay có "/" (VD "125MM/1050W"), để nguyên là xlsxwriter báo lỗi.
SHEET_NAME_BANNED = re.compile(r"[\[\]:*?/\\]")

# (tiêu đề cột, độ rộng, kiểu ô: "text" | "int" | "money" | "num")
PRODUCT_COLUMNS = [
    ("STT", 6, "int"), ("Mặt hàng", 50, "text"), ("Lượt hỏi", 10, "int"), ("Có giá", 9, "int"),
    ("Được chọn / lên đơn", 12, "int"), ("Không được chọn", 12, "int"), ("Chờ chọn", 10, "int"),
    ("Tỉ lệ thành công", 18, "text"), ("Lượt đơn mua", 12, "int"), ("Giá gần nhất (sau VAT)", 18, "money"),
]
LINE_COLUMNS = [
    ("STT", 6, "int"), ("Ngày gửi", 12, "text"), ("Báo giá", 16, "text"), ("Người hỏi", 26, "text"),
    ("Mã hàng", 16, "text"), ("Mặt hàng", 46, "text"), ("SL", 9, "num"), ("ĐVT", 8, "text"),
    ("Đơn giá sau VAT", 16, "money"), ("Kết quả", 18, "text"), ("Đơn mua", 18, "text"),
]
PRICE_COLUMNS = [
    ("STT", 6, "int"), ("Ngày gửi", 12, "text"), ("Báo giá", 16, "text"), ("Người hỏi", 26, "text"),
    ("SL", 9, "num"), ("ĐVT", 8, "text"), ("Đơn giá sau VAT", 16, "money"), ("Chênh lệch", 14, "money"),
    ("Chênh lệch %", 12, "num"), ("Kết quả", 18, "text"), ("Đơn mua", 18, "text"),
]


def product_rows(products):
    """Bảng "Mặt hàng hay được hỏi" (aggregate_products) → các dòng theo PRODUCT_COLUMNS."""
    return [[index, p["product"], p["asked"], p["priced"], p["won"], p["lost"], p["pending"], p["rate_text"],
             p["orders"], round(p["last_price"]) if p["last_price"] else None]
            for index, p in enumerate(products, start=1)]


def line_rows(facts, outcome_labels):
    """Bảng "Mặt hàng đã báo giá" (line_facts) → các dòng theo LINE_COLUMNS."""
    return [[index, local_date_text(f["at"]), f["quote_name"], f["sale"], f["code"], f["product"], f["qty"], f["uom"],
             round(f["price_incl"]) if f["price_incl"] else None, outcome_labels.get(f["outcome"], ""),
             ", ".join(f["order_names"])]
            for index, f in enumerate(facts, start=1)]


def price_rows(prices, outcome_labels):
    """Bảng "Biến động giá" (price_history) → các dòng theo PRICE_COLUMNS. Lần đầu: chênh lệch trống."""
    return [[index, local_date_text(r["at"]), r["quote_name"], r["sale"], r["qty"], r["uom"], round(r["price_incl"]),
             r["delta"] if r["pct"] is not None else None, r["pct"], outcome_labels.get(r["outcome"], ""),
             ", ".join(r["order_names"])]
            for index, r in enumerate(prices["rows"], start=1)]


def build_workbook(title, subtitle, columns, rows):
    """Một sheet: dòng tiêu đề, dòng mô tả bộ lọc, bảng (đầu bảng đậm, cố định khi cuộn, có lọc). Trả bytes .xlsx.

    title: tên sheet + tiêu đề (tên sheet bỏ ký tự Excel cấm — SHEET_NAME_BANNED — và cắt 31 ký tự); subtitle: chữ
    mô tả ("" = bỏ);
    columns: list (tiêu đề, độ rộng, kiểu); rows: list list giá trị cùng thứ tự cột (None = ô trống).
    """
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet(SHEET_NAME_BANNED.sub(" ", title)[:31].strip(" '") or "Sheet1")
    styles = {
        "title": workbook.add_format({"bold": True, "font_size": 14}),
        "sub": workbook.add_format({"italic": True, "font_color": "#555555"}),
        "head": workbook.add_format({"bold": True, "bg_color": "#F3F5F8", "border": 1, "text_wrap": True, "valign": "vcenter"}),
        "text": workbook.add_format({"border": 1, "valign": "top", "text_wrap": True}),
        "int": workbook.add_format({"border": 1, "valign": "top", "num_format": "0"}),
        "num": workbook.add_format({"border": 1, "valign": "top", "num_format": "#,##0.##"}),
        "money": workbook.add_format({"border": 1, "valign": "top", "num_format": "#,##0"}),
    }
    sheet.write(0, 0, title, styles["title"])
    if subtitle:
        sheet.write(1, 0, subtitle, styles["sub"])
    head_row = 3
    for col, (label, width, _kind) in enumerate(columns):
        sheet.set_column(col, col, width)
        sheet.write(head_row, col, label, styles["head"])
    for offset, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            kind = columns[col][2]
            if value is None or value == "":
                sheet.write_blank(head_row + offset, col, None, styles[kind])
            else:
                sheet.write(head_row + offset, col, value, styles[kind])
    sheet.freeze_panes(head_row + 1, 0)
    sheet.autofilter(head_row, 0, head_row + max(len(rows), 1), len(columns) - 1)
    workbook.close()
    return output.getvalue()
