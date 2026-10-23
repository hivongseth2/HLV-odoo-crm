# -*- coding: utf-8 -*-
"""Hàm thuần cho việc lấy hoá đơn mua vào ĐÃ THANH TOÁN từ MISA (trang "Nhận hoá đơn" — pu_invoice) để ghi nhận trả
công nợ NCC. Không đụng env / mạng: dựng payload, đọc dòng MISA trả về, gom tiền theo đơn mua, chia phần còn nợ.

Payload chép từ request thật của trang actapp.misa.vn/app/PU/PUVoucher/ReceiveInvoice (HAR 2026-10-23) — số property
là mã cột nội bộ của MISA, không có tài liệu: đổi thì chụp lại HAR rồi sửa ở đây."""

from datetime import date, datetime, time, timedelta

from odoo.addons.misa_invoice_status_report.models.misa_api_utils_ext import _normalize_inv_no

LIST_URL = "https://actapp.misa.vn/g1/api/pu/v1/pu_invoice/paging_filter_v2"
DETAIL_URL = "https://actapp.misa.vn/g1/api/pu/v1/pu_invoice/get_paging_detail"
PAGE_SIZE = 100
# Trần số trang mỗi lần tìm — MISA trả dữ liệu lạ thì không lặp vô hạn.
MAX_PAGES = 50
# Chứng từ "Nhận hoá đơn mua hàng" của MISA.
PU_INVOICE_REFTYPE = 3400
# Cột chi tiết trang hoá đơn (mã hàng, diễn giải, tiền, VAT, số đơn mua, số phiếu nhập…) — đúng bộ trang MISA xin.
DETAIL_COLUMNS = [2157, 1355, 1195, 1065, 5196, 5364, 5350, 3846, 3833, 3866, 3404, 2358]
VN_OFFSET = timedelta(hours=7)


def utc_iso(day, end_of_day=False):
    """Mốc ngày giờ VN → chuỗi UTC kiểu MISA ("2026-04-30T17:00:00.00Z" cho đầu ngày 01/05/2026).

    Nhận: day — date. end_of_day: True → cuối ngày (23:59:59 giờ VN).
    Trả: chuỗi ISO UTC có đuôi Z.
    """
    moment = datetime.combine(day, time.max if end_of_day else time.min) - VN_OFFSET
    return moment.strftime("%Y-%m-%dT%H:%M:%S.00Z")


def list_payload(date_from, date_to, search, page):
    """Body tìm hoá đơn mua vào theo khoảng ngày + chữ tìm nhanh (số HĐ / tên / MST — MISA tìm kiểu CHỨA).

    Nhận: date_from, date_to — date (giờ VN, gồm cả hai đầu); search — chuỗi, rỗng = không lọc chữ; page — từ 1.
    Trả: dict gửi thẳng cho LIST_URL.
    """
    payload = {
        "isOnlyData": True,
        "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},"
                "{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},"
                "{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
        "filter": [
            {"property": 4041, "value": PU_INVOICE_REFTYPE, "operator": 7, "operand": 1, "data_type": 4},
            {"property": 2023, "value": 0, "operator": 7, "operand": 1, "data_type": 1},
            {"property": 3972, "value": utc_iso(date_from), "operator": 10, "operand": 1, "data_type": 3},
            {"property": 3972, "value": utc_iso(date_to, end_of_day=True), "operator": 12, "operand": 1, "data_type": 3},
        ],
        "pageIndex": page,
        "pageSize": PAGE_SIZE,
        "useSp": False,
        "view": 3,
        "summaryColumns": [5133],
        "loadMode": 2,
    }
    if search:
        payload["customFilter"] = [{
            "property": 4018, "value": search, "operator": 1, "operand": 1, "data_type": 1, "childrens": [
                {"property": 2189, "value": search, "operator": 1, "operand": 2, "data_type": 1},
                {"property": 57, "value": search, "operator": 1, "operand": 2, "data_type": 1},
            ],
        }]
    return payload


def detail_payload(refid, page):
    """Body đọc dòng hàng của một hoá đơn (refid MISA), trang page (từ 1)."""
    return {
        "columns": DETAIL_COLUMNS,
        "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
        "filter": [{"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}],
        "pageIndex": page,
        "pageSize": PAGE_SIZE,
        "useSp": False,
        "view": 4,
        "summaryColumns": [5196, 5350],
        "loadMode": 2,
    }


def is_last_page(rows):
    """MISA trả Total = 0 khi isOnlyData — biết hết dữ liệu chỉ bằng trang ngắn hơn PAGE_SIZE."""
    return len(rows or []) < PAGE_SIZE


def normalize_tax_code(value):
    """MST để so: bỏ khoảng trắng / gạch / chấm. None / rỗng → ""."""
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def invoice_key(tax_code, inv_no):
    """Khoá duy nhất một hoá đơn mua vào: "<MST>_<số HĐ>" (số HĐ bỏ số 0 đứng đầu — "00007446" = "7446").

    Số HĐ trùng giữa các NCC là chuyện thường (mỗi NCC tự đánh số) nên phải kèm MST. Thiếu MST hoặc số HĐ → "".
    """
    tax = normalize_tax_code(tax_code)
    number = _normalize_inv_no(str(inv_no or ""))
    return f"{tax}_{number}" if tax and number else ""


def _misa_date(value):
    """"2026-10-21T00:00:00.000+07:00" → date(2026, 10, 21) (ngày theo giờ VN MISA ghi). Rỗng / sai → None."""
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def parse_invoice_row(row):
    """Một dòng danh sách hoá đơn MISA → dict gọn: refid, tax_code, vendor_name, inv_no, inv_date (date), amount (sau
    VAT), is_paid (bool), key (invoice_key). Thiếu trường nào thì giá trị rỗng / 0 tương ứng."""
    amount = float(row.get("total_turnover_amount") or 0.0) + float(row.get("total_vat_amount") or 0.0)
    return {
        "refid": row.get("refid") or "",
        "tax_code": normalize_tax_code(row.get("account_object_tax_code")),
        "vendor_name": (row.get("account_object_name") or "").strip(),
        "inv_no": (row.get("inv_no") or "").strip(),
        "inv_date": _misa_date(row.get("inv_date")),
        "amount": amount,
        "is_paid": bool(row.get("is_paid")),
        "key": invoice_key(row.get("account_object_tax_code"), row.get("inv_no")),
    }


def amounts_by_order(detail_rows):
    """Tiền (sau VAT) của hoá đơn theo số đơn mua trên từng dòng (pu_order_refno).

    Nhận: các dòng chi tiết MISA. Trả: dict {số đơn mua: tiền}; dòng không gắn đơn mua gom vào khoá "".
    """
    totals = {}
    for line in detail_rows or []:
        refno = (line.get("pu_order_refno") or "").strip()
        amount = float(line.get("turnover_amount_oc") or 0.0) + float(line.get("vat_amount_oc") or 0.0)
        totals[refno] = totals.get(refno, 0.0) + amount
    return totals


def debt_share(invoice_amount, open_amount):
    """Phần tiền hoá đơn trả vào một đơn được GHI thành công nợ: không quá số đơn còn nợ (đề nghị chi đã chi / đang
    chi và các phiếu trước đã trừ trong open_amount) — tiền đi qua đề nghị chi thì không đếm lần hai.

    Nhận: invoice_amount — tiền đơn này trên hoá đơn; open_amount — đơn còn nợ. Trả: số >= 0, làm tròn đồng.
    """
    return float(round(max(min(invoice_amount or 0.0, open_amount or 0.0), 0.0)))
