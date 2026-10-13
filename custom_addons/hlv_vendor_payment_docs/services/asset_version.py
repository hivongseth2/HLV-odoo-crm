# -*- coding: utf-8 -*-
"""Phiên bản gắn vào link CSS/JS của module (?v=): version manifest + mã băm nội dung thư mục static — sửa file là
link đổi, trình duyệt / Cloudflare không giữ bản cũ. Dùng lại static_digest của hlv_vendor_quotation (cùng lý do)."""

import functools
import os

from odoo.addons.hlv_vendor_quotation.services.asset_version import static_digest
from odoo.modules.module import get_manifest

MODULE = "hlv_vendor_payment_docs"
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


@functools.lru_cache(maxsize=1)
def asset_version():
    """"<version manifest>-<mã băm static>"; không đọc được version → chỉ mã băm."""
    version = (get_manifest(MODULE) or {}).get("version", "")
    digest = static_digest(STATIC_DIR)
    return f"{version}-{digest}" if version else digest
