# -*- coding: utf-8 -*-
"""Trang đọc hướng dẫn: /huong-dan (danh sách) và /huong-dan/<slug>/… (nội dung).

Chỉ người dùng nội bộ. Quyền xem từng hướng dẫn do record rule của hlv.sale.guide lo (nhóm
"Chỉ cho nhóm"), nên đọc bản ghi bằng env thường — không sudo.

Trang hướng dẫn phục vụ nguyên văn, cùng origin với Odoo (để ảnh đi kèm tải được bằng cookie
đăng nhập). Vì vậy chỉ nhóm Quản lý hướng dẫn được tải nội dung lên — xem security.xml.
"""

import mimetypes
from itertools import groupby

from odoo import http
from odoo.http import request

from ..models.guide_utils import INDEX, add_back_link
from ..models.sale_guide import GUIDE_ROUTE


class GuidePage(http.Controller):

    @http.route(GUIDE_ROUTE, type="http", auth="user", methods=["GET"])
    def guide_index(self, **kw):
        if request.env.user.share:
            return request.not_found()
        guides = request.env["hlv.sale.guide"].search([("published_on", "!=", False)])
        topics = [(topic or "Khác", list(items)) for topic, items in groupby(guides, key=lambda g: g.topic)]
        return request.render("hlv_sale_guide.guide_index", {"topics": topics})

    @http.route(
        [
            f"{GUIDE_ROUTE}/<string:slug>",
            f"{GUIDE_ROUTE}/<string:slug>/",
            f"{GUIDE_ROUTE}/<string:slug>/<path:path>",
        ],
        type="http", auth="user", methods=["GET"],
    )
    def guide_file(self, slug, path=None, **kw):
        guide = self._find_guide(slug)
        if not guide:
            return request.not_found()
        if path is None:
            # Ảnh trong trang dùng đường dẫn tương đối (img/a.png): thiếu "/" cuối thì trình
            # duyệt tìm ảnh ở /huong-dan/img/a.png. Odoo tắt strict_slashes nên tự chuyển hướng.
            if not request.httprequest.path.endswith("/"):
                return request.redirect(f"{GUIDE_ROUTE}/{slug}/")
            path = INDEX
        attachment = guide._guide_file(path)
        if not attachment:
            return request.not_found()
        if path == INDEX:
            page = add_back_link(attachment.raw.decode("utf-8", errors="replace"), GUIDE_ROUTE, "Tất cả hướng dẫn")
            return request.make_response(page, headers=[
                ("Content-Type", "text/html; charset=utf-8"),
                ("Cache-Control", "no-cache"),
            ])
        return request.make_response(attachment.raw, headers=[
            ("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream"),
            # Ảnh/CSS đổi khi tải gói mới; giữ ngắn để người đọc thấy bản mới trong ngày.
            ("Cache-Control", "private, max-age=3600"),
        ])

    def _find_guide(self, slug):
        if request.env.user.share:
            return None
        return request.env["hlv.sale.guide"].search([("slug", "=", slug), ("published_on", "!=", False)], limit=1)
