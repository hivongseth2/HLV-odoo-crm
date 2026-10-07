# -*- coding: utf-8 -*-
"""Phiên bản gắn vào link CSS/JS của hai trang tự dựng (/bao-gia, /hoi-gia-ncc).

Hai trang nạp file tĩnh bằng <link>/<script> thường, không qua asset bundle của Odoo (xem
sale_page_templates.xml) — nên không có mã băm tự đổi. Thiếu ?v= thì trình duyệt giữ bản cũ
sau khi upgrade module (VD tiêu đề vẫn ra font cũ). Lấy theo version trong manifest: mỗi lần
nâng version là trình duyệt tải lại.
"""

from odoo.modules.module import get_manifest

MODULE = "hlv_vendor_quotation"


def asset_version():
    """Version module trong __manifest__ (get_manifest đã tự cache). Không đọc được → ""."""
    return (get_manifest(MODULE) or {}).get("version", "")
