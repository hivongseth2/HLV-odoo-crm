# -*- coding: utf-8 -*-
"""Hàm thuần cho giao hàng từng đợt của đơn mua (NCC thiếu hàng / hẹn giao) — không đụng env."""

from datetime import datetime, time

import pytz

from .vendor_quote_utils import DATE_FMT, LOCAL_TZ, format_vn_number

# Sai số so SL (ĐVT có số lẻ): chênh dưới mức này coi như đã nhận đủ.
QTY_EPSILON = 1e-6
# Giờ đặt cho ngày giao mới khi dòng chưa có giờ cũ để giữ.
DEFAULT_DUE_HOUR = 8


def remaining_qty(ordered_qty, received_qty):
    """SL còn chờ giao = đặt − đã nhận, không âm. None coi như 0; chênh nhỏ hơn QTY_EPSILON → 0.0."""
    rest = (ordered_qty or 0.0) - (received_qty or 0.0)
    return rest if rest > QTY_EPSILON else 0.0


def is_late(due_day, today, remaining):
    """Quá hẹn: còn hàng chờ giao (remaining > 0) và ngày hẹn (date) trước hôm nay. Không có ngày → False."""
    return bool(remaining > 0 and due_day and due_day < today)


def due_day_error(new_day, today):
    """Kiểm ngày giao NCC nhập: trống / trước hôm nay → câu lỗi; hợp lệ → ""."""
    if not new_day:
        return "chọn ngày giao"
    if new_day < today:
        return "ngày giao không được trước hôm nay"
    return ""


def due_datetime(new_day, old_utc, tz_name=LOCAL_TZ):
    """Datetime UTC (naive, kiểu Odoo lưu) cho ngày giao mới new_day, GIỮ giờ địa phương của giờ cũ old_utc
    (naive UTC) — chỉ dời ngày, không làm lệch giờ hẹn. old_utc trống → DEFAULT_DUE_HOUR giờ địa phương."""
    tz = pytz.timezone(tz_name)
    clock = pytz.utc.localize(old_utc).astimezone(tz).time() if old_utc else time(DEFAULT_DUE_HOUR)
    return tz.localize(datetime.combine(new_day, clock)).astimezone(pytz.utc).replace(tzinfo=None)


def local_day(value_utc, tz_name=LOCAL_TZ):
    """Ngày (date) theo giờ địa phương của một datetime naive UTC; trống → None."""
    if not value_utc:
        return None
    return pytz.utc.localize(value_utc).astimezone(pytz.timezone(tz_name)).date()


def local_day_start_utc(day, tz_name=LOCAL_TZ):
    """Datetime naive UTC của 00:00 giờ địa phương ngày day (date) — mốc so với datetime Odoo lưu (UTC).
    day trống → None."""
    if not day:
        return None
    tz = pytz.timezone(tz_name)
    return tz.localize(datetime.combine(day, time())).astimezone(pytz.utc).replace(tzinfo=None)


def pending_text(parts):
    """Một dòng liệt kê hàng còn chờ giao: parts = [(tên, SL còn, ĐVT, ngày hẹn date | None)].

    → "Phốt dầu 4 Cái hẹn 20/10/2026; Bóng đèn 2 Cái". parts rỗng → "".
    """
    items = []
    for name, qty, uom, day in parts:
        text = f"{name} {format_vn_number(qty)} {uom}".strip()
        items.append(f"{text} hẹn {day.strftime(DATE_FMT)}" if day else text)
    return "; ".join(items)

# Ai gây ra tiến độ / tin giao hàng mới nhất của đơn mua (purchase.order.hlv_vendor_event_source) — để chuông, popup,
# Zalo của sale ghi đúng người báo: tin "Trễ hẹn giao" do hệ thống tự sinh chứ không phải NCC báo.
EVENT_SOURCES = [("vendor", "NCC"), ("buyer", "Bên mua"), ("system", "Hệ thống")]
SYSTEM_ACTOR = "Hệ thống"


def event_actor(source, vendor_name, company_name):
    """Tên người báo hiện ở chuông / popup / Zalo của sale cho một sự kiện đơn mua.

    source: "vendor" | "buyer" | "system" | rỗng. Trả vendor_name (NCC báo; rỗng — dữ liệu trước khi có nguồn — cũng
    coi là NCC), company_name (bên mua: thu mua duyệt / không duyệt yêu cầu của NCC; rỗng → "Bên mua") hoặc
    "Hệ thống" (kho nhận hàng, trễ hẹn).
    """
    if source == "system":
        return SYSTEM_ACTOR
    if source == "buyer":
        return company_name or "Bên mua"
    return vendor_name or ""
