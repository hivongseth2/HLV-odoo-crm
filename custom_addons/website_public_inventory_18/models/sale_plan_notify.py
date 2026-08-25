# -*- coding: utf-8 -*-
import logging
import time

_logger = logging.getLogger(__name__)


def push_sale_plan_notification(env, alias, body, so=None, author_name="Kho hàng"):
    """Tạo 1 thông báo trong hệ thống mention của trang /sale_plan (module
    hlv_sale_delivery_planning, model hlv.sale.plan.mention.notification) cho ĐÚNG 1 alias đã
    biết trước — KHÔNG dùng hàm gốc _push_public_mention_event (private, nằm trong file
    controller của module đó, chỉ nhận diện người cần báo bằng cách dò chuỗi "@alias" trong nội
    dung chat bằng regex). Ở đây mình đã biết chính xác alias cần báo (tra qua mapping mã sale),
    không cần suy luận từ text — nên viết lại độc lập phần tạo bản ghi + bắn bus, tránh phụ thuộc
    vào chi tiết cài đặt nội bộ (private) của module khác có thể đổi bất cứ lúc nào.

    Có bắn kèm sự kiện bus 'sale_plan_public_channel'/'sale_plan_mention' để nếu trang /sale_plan
    đang mở sẵn thì thấy ngay (chuông, toast) — KHÔNG làm thêm web-push (khi tắt hẳn trình duyệt),
    vì cơ chế đó cũng private/phức tạp hơn; kênh Zalo đã đảm nhiệm việc báo khi sale không mở
    trang nào cả. Bản ghi vẫn được lưu lại nên mở lại trang /sale_plan sau đó vẫn thấy."""
    if not alias:
        return
    preview = (body or "").strip()
    if len(preview) > 140:
        preview = preview[:140] + "..."
    so_id = so.id if so else False
    so_name = (so.name if so else "") or ""

    notif = env["hlv.sale.plan.mention.notification"].sudo().create({
        "alias": alias,
        "sale_order_id": so_id,
        "so_name": so_name,
        "author_name": author_name,
        "body": body or "",
        "preview": preview,
        "mentions": alias,
        "is_read": False,
    })
    payload = {
        "id": notif.id,
        "type": "sale_plan_mention",
        "notification_ids": [notif.id],
        "notification_id_by_alias": {alias: notif.id},
        "so_id": so_id,
        "so_name": so_name,
        "author_name": author_name,
        "body": body or "",
        "preview": preview,
        "mentions": [alias],
        "ts": int(time.time()),
    }
    try:
        env["bus.bus"].sudo()._sendone("sale_plan_public_channel", "sale_plan_mention", payload)
    except Exception:
        _logger.exception("Lỗi bắn bus sale_plan_mention cho alias=%s", alias)


def notify_sale_plan_by_code(env, saler_code, body, so=None, author_name="Kho hàng"):
    """Tra alias /sale_plan theo ĐÚNG mã sale (MISA saler_code) — KHÔNG được suy ra từ user đang
    đăng nhập/đứng đơn, vì 1 tài khoản có thể được gán quản lý NHIỀU mã sale
    (res.users.x_misa_saler_codes, vd trưởng nhóm) — chỉ đọc alias của tài khoản đó thôi sẽ
    không biết chính xác bản ghi này (yêu cầu giữ hàng / đơn hàng) là của ai trong số đó.

    Dùng mapping riêng hlv.zalo.stock.notification.sale_plan_alias_mapping_text (cùng model
    chứa mapping Zalo hold_unreserve, để admin cấu hình tập trung 1 chỗ) — KHÔNG liên quan gì
    đến field x_sale_plan_mention_names trên res.users (đó chỉ dùng để module
    hlv_sale_delivery_planning biết alias đó thuộc user nào khi họ tự mở trang xem)."""
    if not saler_code:
        return
    config = env["hlv.zalo.stock.notification"].sudo()._get_active_config()
    if not config:
        _logger.info(
            "Không có cấu hình Zalo Stock Notification đang active, bỏ qua báo /sale_plan cho "
            "mã sale=%s.", saler_code,
        )
        return
    aliases = config.get_sale_plan_aliases_from_mapping(saler_code)
    if not aliases:
        _logger.info(
            "Không tìm thấy alias /sale_plan cho saler_code=%s trong "
            "sale_plan_alias_mapping_text, bỏ qua.", saler_code,
        )
        return
    for alias in aliases:
        try:
            push_sale_plan_notification(env, alias, body, so=so, author_name=author_name)
        except Exception:
            _logger.exception(
                "Lỗi báo /sale_plan cho alias=%s (saler_code=%s).", alias, saler_code,
            )
