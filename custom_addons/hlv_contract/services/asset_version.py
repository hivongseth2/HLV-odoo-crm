# -*- coding: utf-8 -*-
"""Phiên bản gắn vào link CSS/JS của trang /hop-dong.

Trang nạp file tĩnh bằng <link>/<script> thường (không qua asset bundle, xem
contract_page_templates.xml) nên không có mã băm tự đổi; thiếu ?v= thì trình duyệt giữ
bản cũ sau khi nâng module. Cùng cách hlv_vendor_quotation làm, viết lại ở đây để không
phải phụ thuộc cả module đó chỉ vì hai dòng.
"""

from odoo.modules.module import get_manifest

MODULE = 'hlv_contract'


def asset_version():
    """Version trong __manifest__ (get_manifest đã tự cache). Không đọc được -> ''."""
    return (get_manifest(MODULE) or {}).get('version', '')
