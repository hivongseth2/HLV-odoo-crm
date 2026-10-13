# -*- coding: utf-8 -*-
"""Hàm thuần cho chứng từ chi NCC và trạng thái thanh toán — không đụng env."""

import os

# Trạng thái thanh toán của một đơn mua theo số đã chi.
PAYMENT_STATUS_LABELS = {
    "paid": "Đã thanh toán",
    "partial": "Thanh toán một phần",
    "unpaid": "Chưa thanh toán",
}
# Chênh dưới chừng này đồng coi như trả đủ (làm tròn giữa MISA và Odoo).
PAID_TOLERANCE = 1.0
# File kế toán được tải lên: ảnh chụp / PDF / Word (UNC, phiếu chi, sao kê).
ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".pdf", ".doc", ".docx")
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def payment_status(order_total, paid_amount):
    """Trạng thái thanh toán của đơn: "paid" (đã chi ≥ giá trị đơn, lệch ≤ PAID_TOLERANCE), "partial" (đã chi một
    phần), "unpaid" (chưa chi đồng nào). Đơn giá trị 0 mà có chi → "paid". Số None coi như 0."""
    total = order_total or 0.0
    paid = paid_amount or 0.0
    if paid <= PAID_TOLERANCE:
        return "unpaid"
    if paid >= total - PAID_TOLERANCE:
        return "paid"
    return "partial"


# Ảnh trình duyệt nào cũng hiện được (HEIC chỉ Safari hiện — coi như file thường, bấm là tải về).
PREVIEW_IMAGE_MIMETYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def preview_kind(mimetype, filename):
    """Cách xem nhanh một chứng từ: "image" (hiện ảnh thu nhỏ + xem to trong trang), "pdf" (xem trong trang), "file"
    (Word / ảnh HEIC — chỉ tải về). Không rõ mimetype thì đoán theo đuôi file; không đoán được → "file"."""
    mimetype = (mimetype or "").lower()
    extension = os.path.splitext(filename or "")[1].lower()
    if mimetype in PREVIEW_IMAGE_MIMETYPES or (not mimetype and extension in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if mimetype == "application/pdf" or extension == ".pdf":
        return "pdf"
    return "file"


def file_badge(filename):
    """Nhãn loại file trên ô chứng từ không có ảnh thu nhỏ: "PDF", "WORD", "ẢNH" (HEIC), đuôi lạ viết hoa; không đuôi → "FILE"."""
    extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return {"pdf": "PDF", "doc": "WORD", "docx": "WORD", "heic": "ẢNH"}.get(extension, extension.upper() or "FILE")


def document_error(filename, size):
    """Lý do không nhận file kế toán tải lên ("" = nhận). filename: tên file gốc; size: số byte."""
    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return f"{filename or 'File'}: chỉ nhận ảnh, PDF hoặc Word"
    if size <= 0:
        return f"{filename}: file rỗng"
    if size > MAX_DOCUMENT_BYTES:
        return f"{filename}: quá {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB"
    return ""
