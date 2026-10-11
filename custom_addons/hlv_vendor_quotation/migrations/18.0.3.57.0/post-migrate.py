# -*- coding: utf-8 -*-
"""Nguồn tin giao hàng của đơn mua (hlv_vendor_event_source) cho dữ liệu có sẵn — đoán theo chữ của tin đã lưu:
"Trễ hẹn giao…" / "Kho đã nhận một phần…" → hệ thống; "Thu mua …" (duyệt / không duyệt yêu cầu) → bên mua;
tin khác hoặc chỉ có tiến độ → NCC. Không đoán được "Đã giao" do kho tự chuyển (không lưu tin) — để NCC."""


def migrate(cr, version):
    cr.execute("""
        UPDATE purchase_order SET hlv_vendor_event_source = CASE
            WHEN hlv_vendor_event LIKE 'Trễ hẹn giao%%' OR hlv_vendor_event LIKE 'Kho đã nhận một phần%%' THEN 'system'
            WHEN hlv_vendor_event LIKE 'Thu mua %%' THEN 'buyer'
            ELSE 'vendor'
        END
        WHERE hlv_vendor_event_source IS NULL AND hlv_vendor_status_date IS NOT NULL
    """)
