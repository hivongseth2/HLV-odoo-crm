# -*- coding: utf-8 -*-
"""Phiên bản gắn vào link CSS/JS của hai trang tự dựng (/bao-gia, /hoi-gia-ncc).

Hai trang nạp file tĩnh bằng <link>/<script> thường, không qua asset bundle của Odoo (xem
sale_page_templates.xml) — nên không có mã băm tự đổi. Thiếu ?v= thì trình duyệt giữ bản cũ.

Trước đây chỉ lấy version manifest: sửa JS mà không nâng version (để khỏi phải nâng cấp module) là
trình duyệt của sale vẫn chạy JS cũ — VD ô tìm NCC chưa nhận MST 12 số dù máy chủ đã có code mới.
Nay ghép thêm mã băm NỘI DUNG thư mục static: file đổi là link đổi, không phụ thuộc version.
Tính một lần mỗi tiến trình — deploy code mới là Odoo khởi động lại tiến trình.
"""

import functools
import hashlib
import os

from odoo.modules.module import get_manifest

MODULE = "hlv_vendor_quotation"
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
HASH_LENGTH = 8


def static_digest(root):
    """Mã băm (8 ký tự hex) nội dung mọi file dưới thư mục root, theo đường dẫn tương đối + nội dung.

    Nhận: đường dẫn thư mục. Trả: chuỗi hex; thư mục không có / rỗng → mã băm của "không có gì" (cố định).
    Thứ tự duyệt được sắp lại nên cùng nội dung luôn ra cùng mã.
    """
    digest = hashlib.sha1()
    for folder, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(folder, name)
            digest.update(os.path.relpath(path, root).replace(os.sep, "/").encode())
            with open(path, "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()[:HASH_LENGTH]


@functools.lru_cache(maxsize=1)
def asset_version():
    """"<version manifest>-<mã băm static>", VD "18.0.3.60.0-1a2b3c4d". Không đọc được version → chỉ mã băm."""
    version = (get_manifest(MODULE) or {}).get("version", "")
    digest = static_digest(STATIC_DIR)
    return f"{version}-{digest}" if version else digest
