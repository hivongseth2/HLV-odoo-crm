# -*- coding: utf-8 -*-
"""Gán nhóm quyền "Hỏi giá NCC" cho người đang dùng trang, lúc cài mới hoặc nâng cấp lên bản có
nhóm riêng — để không ai đang vào được /hoi-gia-ncc bị mất quyền.

Trước bản này trang mở cho sale / thu mua / YCMH, và mọi thu mua đều thấy "Tất cả mã sale".
Giờ "Tất cả" chỉ cho nhóm Quản lý — gán sẵn cho quản trị và quản lý mua hàng; ai khác cần thì
gán tay (Thiết lập → Người dùng → Hỏi giá NCC).
"""

USER_GROUP = "hlv_vendor_quotation.group_vendor_quote_user"
MANAGER_GROUP = "hlv_vendor_quotation.group_vendor_quote_manager"
# Nhóm trước đây được vào trang — người trong các nhóm này nhận nhóm Người dùng.
LEGACY_PAGE_GROUPS = (
    "sales_team.group_sale_salesman",
    "purchase.group_purchase_user",
    "purchase_request.group_purchase_request_user",
)
DEFAULT_MANAGER_GROUPS = ("purchase.group_purchase_manager",)


def _internal_users(env, group_xmlids):
    users = env["res.users"]
    for xmlid in group_xmlids:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            users |= group.users
    return users.filtered(lambda user: not user.share)


def grant_default_groups(env):
    """Thêm (không bớt) người dùng vào hai nhóm; chạy lại nhiều lần vẫn vậy."""
    user_group = env.ref(USER_GROUP)
    manager_group = env.ref(MANAGER_GROUP)
    user_group.write({"users": [(4, user.id) for user in _internal_users(env, LEGACY_PAGE_GROUPS)]})
    managers = _internal_users(env, DEFAULT_MANAGER_GROUPS)
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin:
        managers |= admin
    manager_group.write({"users": [(4, user.id) for user in managers]})
