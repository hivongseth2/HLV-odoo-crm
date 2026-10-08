# -*- coding: utf-8 -*-
"""Trang đọc hướng dẫn: /huong-dan (cây thư mục + khung xem) và /huong-dan/<slug>/… (nội dung).

Chỉ người dùng nội bộ. Quyền xem từng hướng dẫn do record rule của hlv.sale.guide lo (nhóm
"Chỉ cho nhóm"), nên đọc bản ghi bằng env thường — không sudo.

Trang hướng dẫn phục vụ nguyên văn, cùng origin với Odoo (để ảnh đi kèm tải được bằng cookie
đăng nhập). Vì vậy chỉ nhóm Quản lý hướng dẫn được tải nội dung lên — xem security.xml.
"""

import mimetypes

from odoo import http
from odoo.http import request
from odoo.modules.module import get_manifest

from ..models.guide_utils import INDEX, PDF_FILE, add_back_link, build_tree, pdf_viewer_page
from ..models.sale_guide import GUIDE_ROUTE

MANAGER_GROUP = "hlv_sale_guide.group_guide_manager"
# Link mở thẳng form backend (Odoo 18 hiểu /odoo/action-<xmlid>[/new]).
BACKEND_GUIDES = "/odoo/action-hlv_sale_guide.action_sale_guide"
BACKEND_FOLDERS = "/odoo/action-hlv_sale_guide.action_sale_guide_folder"


class GuidePage(http.Controller):

    @http.route(GUIDE_ROUTE, type="http", auth="user", methods=["GET"])
    def guide_index(self, **kw):
        if request.env.user.share:
            return request.not_found()
        guides = request.env["hlv.sale.guide"].search([("published_on", "!=", False)])
        folders = request.env["hlv.sale.guide.folder"].search([])
        tree = build_tree(
            [{"id": f.id, "parent_id": f.parent_id.id or None, "name": f.name} for f in folders],
            [self._guide_item(guide) for guide in guides],
        )
        return request.render("hlv_sale_guide.guide_index", {
            "tree": tree,
            "is_manager": request.env.user.has_group(MANAGER_GROUP),
            "backend_guides": BACKEND_GUIDES,
            "backend_folders": BACKEND_FOLDERS,
            "asset_version": (get_manifest("hlv_sale_guide") or {}).get("version", ""),
        })

    @http.route(
        [
            f"{GUIDE_ROUTE}/<string:slug>",
            f"{GUIDE_ROUTE}/<string:slug>/",
            f"{GUIDE_ROUTE}/<string:slug>/<path:path>",
        ],
        type="http", auth="user", methods=["GET"],
    )
    def guide_file(self, slug, path=None, embed=None, **kw):
        guide = self._find_guide(slug)
        if not guide:
            return request.not_found()
        # embed=1: trang nằm trong khung xem của /huong-dan — không chèn nút quay lại.
        back_href = None if embed else f"{GUIDE_ROUTE}?g={slug}"
        if path is None:
            # Ảnh trong trang dùng đường dẫn tương đối (img/a.png): thiếu "/" cuối thì trình
            # duyệt tìm ảnh ở /huong-dan/img/a.png. Odoo tắt strict_slashes nên tự chuyển hướng.
            if not request.httprequest.path.endswith("/"):
                return request.redirect(f"{GUIDE_ROUTE}/{slug}/" + (f"?embed={embed}" if embed else ""))
            if guide.content_kind == "pdf":
                return self._html(pdf_viewer_page(guide.name, PDF_FILE, back_href))
            path = INDEX
        attachment = guide._guide_file(path)
        if not attachment:
            return request.not_found()
        if path == INDEX:
            page = attachment.raw.decode("utf-8", errors="replace")
            return self._html(add_back_link(page, back_href, "Tất cả hướng dẫn") if back_href else page)
        headers = [
            ("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream"),
            # Ảnh/CSS/PDF đổi khi tải bản mới; giữ ngắn để người đọc thấy bản mới trong ngày.
            ("Cache-Control", "private, max-age=3600"),
        ]
        if path == PDF_FILE:
            headers.append(("Content-Disposition", f'inline; filename="{slug}.pdf"'))
        return request.make_response(attachment.raw, headers=headers)

    @staticmethod
    def _html(page):
        return request.make_response(page, headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-cache"),
        ])

    @staticmethod
    def _guide_item(guide):
        return {
            "folder_id": guide.folder_id.id or None,
            "name": guide.name,
            "slug": guide.slug,
            "url": guide.url,
            "summary": guide.summary or "",
            "kind": guide.content_kind or "html",
        }

    def _find_guide(self, slug):
        if request.env.user.share:
            return None
        return request.env["hlv.sale.guide"].search([("slug", "=", slug), ("published_on", "!=", False)], limit=1)
