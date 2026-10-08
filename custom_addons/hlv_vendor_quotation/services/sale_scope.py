# -*- coding: utf-8 -*-
"""Phạm vi mã sale của trang /hoi-gia-ncc — mượn nguyên cơ chế /misa_sale_status.

Mỗi tài khoản khai các mã sale MISA của mình ở res.users.x_misa_saler_codes; link riêng của
một sale là /hoi-gia-ncc?t=<token> (token băm từ mã, chỉ để không lộ mã trên URL). Quyền
THẬT nằm ở server: mọi API nhận mã sale và kiểm lại mã đó có thuộc tài khoản đang đăng nhập
không (misa_invoice_status_report._misa_invoice_validate_public_saler_code). Không chép lại
luật ở đây — gọi thẳng hàm bên đó.

"Tất cả mã sale" chỉ cho nhóm Quản lý của module (security/security.xml) — khác
/misa_sale_status (nhóm Đối soát XHD). Nhóm Người dùng chỉ thấy mã của tài khoản mình.
"""

from odoo.addons.misa_invoice_status_report.models.misa_invoice_public_api import (
    MISA_INVOICE_PUBLIC_ALL_SALERS as ALL_SALES,
)
from odoo.exceptions import UserError

from .access_setup import MANAGER_GROUP


def can_see_all(env):
    """Tài khoản được chọn "Tất cả mã sale" không — chỉ nhóm Quản lý Hỏi giá NCC."""
    return env.user.has_group(MANAGER_GROUP)


def sale_code_options(env):
    """[{code, token}] các mã tài khoản đang đăng nhập được xem — đúng danh sách của /misa_sale_status."""
    return env["stock.picking"].get_misa_invoice_saler_code_registry_with_tokens()


def validate_sale_code(env, code):
    """Mã sale đã kiểm quyền. "Tất cả" (ALL_SALES) → False = không lọc theo sale.

    Mã rỗng / không thuộc tài khoản → UserError (do hàm của misa_invoice_status_report ném).
    """
    code = (code or "").strip()
    if code == ALL_SALES:
        if not can_see_all(env):
            raise UserError("Chỉ nhóm Quản lý Hỏi giá NCC được xem phiếu hỏi giá của mọi sale.")
        return False
    return env["stock.picking"]._misa_invoice_validate_public_saler_code(code)


def scope_domain(code, field="sale_code"):
    """Domain lọc theo mã đã kiểm (False = mọi mã). So không phân biệt hoa thường như MISA."""
    return [(field, "=ilike", code)] if code else []
