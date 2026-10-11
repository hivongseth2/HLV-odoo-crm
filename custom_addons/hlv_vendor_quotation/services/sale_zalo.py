# -*- coding: utf-8 -*-
"""Báo sale qua Zalo OA khi NCC có thay đổi — đúng những việc chuông trang /hoi-gia-ncc đang báo: NCC gửi / cập nhật
báo giá, NCC nhắn tin, tiến độ đơn mua (đóng gói, gửi hàng, giao một phần, đổi ngày giao, yêu cầu thay đổi đơn,
trễ hẹn). Gọi từ chat_bus, ngay cạnh chỗ báo chuông.

Dùng lại cấu hình Zalo + mapping mã sale → Zalo user của module hlv_zalo_zns (hold_unreserve_saler_mapping_text, gửi
bằng send_hold_unreserve_notification) — không khai mapping thứ hai. Module đó không bắt buộc: chưa cài / không có
cấu hình đang chạy / tắt trong Cài đặt → không gửi gì.

Gửi ngay trong request nhưng không bao giờ làm hỏng thao tác chính (NCC gửi báo giá, kho nhận hàng…): savepoint +
bắt mọi lỗi, chỉ ghi log.
"""

import logging

from ..models.vendor_quote_access import SALE_PAGE_ROUTE

_logger = logging.getLogger(__name__)

# Cài đặt → Mua hàng → Hỏi giá NCC. Mặc định TẮT: bản staging chép cấu hình Zalo thật — bật nhầm là nhắn sale thật.
ZALO_PARAM = "hlv_vendor_quotation.zalo_notify_sale"
ZALO_MODEL = "hlv.zalo.stock.notification"
# Zalo OA giới hạn độ dài tin; tin NCC dài thì cắt, sale bấm link đọc đủ.
CHAT_PREVIEW_MAX = 300


def _send(record, sale_codes, text, vendor=None):
    """Gửi text (+ link trang /hoi-gia-ncc của từng mã sale, mở sẵn NCC) cho các sale trong sale_codes."""
    env = record.env
    codes = {code.strip().upper() for code in sale_codes if code and code.strip()}
    if not codes or ZALO_MODEL not in env or env["ir.config_parameter"].sudo().get_param(ZALO_PARAM) != "True":
        return
    config = env[ZALO_MODEL].sudo()._get_active_config()
    if not config:
        return
    base = record.get_base_url()
    for code in codes:
        link = f"{base}{SALE_PAGE_ROUTE}?t={env['stock.picking']._misa_invoice_saler_code_token(code)}"
        if vendor:
            link += f"&ncc={vendor.id}"
        try:
            with env.cr.savepoint():
                config.send_hold_unreserve_notification(code, f"{text}\nXem: {link}")
        except Exception:  # noqa: BLE001 — thông báo phụ, không chặn thao tác của NCC / kho / thu mua
            _logger.exception("Không gửi được Zalo cho sale %s về %s", code, record.display_name)


def zalo_quoted(quote, resubmitted):
    """NCC vừa gửi / cập nhật báo giá (quote đã sudo, có phiếu hỏi giá)."""
    vendor = quote.partner_id.commercial_partner_id
    _send(quote, [quote.inquiry_id.sale_code], "📩 {vendor} đã {verb} báo giá {name} (phiếu hỏi giá {inquiry}).".format(
        vendor=vendor.display_name, verb="cập nhật" if resubmitted else "gửi", name=quote.name,
        inquiry=quote.inquiry_id.name,
    ), vendor)


def zalo_order(order, inquiries, status, event, ship):
    """Tiến độ đơn mua đổi — status: nhãn tiến độ, event: giao một phần / đổi ngày / yêu cầu / trễ hẹn ("" nếu không)."""
    vendor = order.partner_id.commercial_partner_id
    details = " · ".join(part for part in (event or status, ship) if part)
    _send(order, inquiries.mapped("sale_code"), f"🚚 Đơn mua {order.name} — {vendor.display_name}: {details}", vendor)


def zalo_chat(record, inquiries, author, text):
    """NCC nhắn tin trên báo giá / đơn mua record. author: tên công ty NCC."""
    preview = text if len(text) <= CHAT_PREVIEW_MAX else text[:CHAT_PREVIEW_MAX].rstrip() + "…"
    _send(record, inquiries.mapped("sale_code"), f"💬 {author} nhắn về {record.name}:\n{preview}",
          record.partner_id.commercial_partner_id)
