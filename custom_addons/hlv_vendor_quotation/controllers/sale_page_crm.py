# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc — hàng có trên MISA CRM mà Odoo chưa có: tìm trên CRM rồi tạo sản phẩm.

Tạo sản phẩm dùng chung misa.api.utils.import_product_from_crm (misa_fetch_po_button) với trang
/misa/product/import. Chạy sudo: sale không có quyền tạo sản phẩm, nhưng chỉ tạo được hàng có
ĐÚNG mã trên CRM (không gõ tay tên / giá), và hàm tạo ghi log người tạo.
"""

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.paste_utils import parse_paste_line, pick_best, score_product_match
from ..services import sale_page_payload as payload
from ..services.crm_opportunity import opportunity_lines
from .sale_page_common import API, SalePageMixin, to_int

# Mỗi dòng dán là 1–2 lần gọi CRM (~1 giây) — chặn trên để trang không treo lâu.
CRM_ROWS_MAX = 30
IMPORT_MAX = 30
SHOW_CANDIDATES = 5


class VendorQuoteSalePageCrm(SalePageMixin, http.Controller):

    @http.route(f"{API}/crm_products", type="json", auth="user", methods=["POST"])
    def api_crm_products(self, search="", **kw):
        """Hàng trên MISA CRM theo mã / tên (ô "Thêm sản phẩm" không thấy trong Odoo)."""
        self._check()
        products = self._misa().crm_product_candidates((search or "")[:100])
        return {"products": [payload.crm_product_payload(p) for p in products]}

    @http.route(f"{API}/crm_match_rows", type="json", auth="user", methods=["POST"])
    def api_crm_match_rows(self, lines=None, **kw):
        """Dòng dán không thấy trong Odoo → hàng gợi ý trên CRM, chấm điểm như khi dò trong Odoo
        (paste_utils.score_product_match). lines: các dòng đã dán (raw). Trả mỗi dòng
        {best: mã CRM chắc chắn hoặc "", candidates}."""
        self._check()
        misa = self._misa()
        rows = []
        for raw in (lines or [])[:CRM_ROWS_MAX]:
            row = parse_paste_line(raw)
            if not row:
                rows.append({"best": "", "candidates": []})
                continue
            key = max(row["codes"], key=len) if row["codes"] else row["term"]
            found = misa.crm_product_candidates(key, limit=10)
            scored = [(score_product_match(row["codes"], row["words"], p.get("code"), p.get("name")), p) for p in found]
            best, ranked = pick_best(scored)
            rows.append({
                "best": (best or {}).get("code") or "",
                "candidates": [payload.crm_product_payload(p) for p in ranked[:SHOW_CANDIDATES]],
            })
        return {"rows": rows}

    @http.route(f"{API}/import_products", type="json", auth="user", methods=["POST"])
    def api_import_products(self, codes=None, **kw):
        """Tạo (hoặc lấy sản phẩm sẵn có) theo mã CRM. Mỗi mã một savepoint: mã lỗi không kéo mã khác.
        Trả {results: [{code, product?, created?, error?}]} đúng thứ tự codes."""
        self._check()
        misa = self._misa()
        results = []
        for code in (codes or [])[:IMPORT_MAX]:
            try:
                with request.env.cr.savepoint():
                    product, created = misa.import_product_from_crm(code)
            except UserError as exc:
                results.append({"code": code, "error": exc.args[0]})
            else:
                results.append({
                    "code": code,
                    "created": created,
                    "product": payload.product_payload(product.with_env(request.env)),
                })
        return {"results": results}

    @http.route(f"{API}/crm_opportunities", type="json", auth="user", methods=["POST"])
    def api_crm_opportunities(self, search="", **kw):
        """Cơ hội trên MISA CRM theo số cơ hội / tên / khách hàng (ô "Lấy hàng từ cơ hội CRM")."""
        self._check()
        return {"opportunities": self._misa().crm_search_opportunities((search or "")[:100])}

    @http.route(f"{API}/crm_opportunity_lines", type="json", auth="user", methods=["POST"])
    def api_crm_opportunity_lines(self, opportunity_id=None, **kw):
        """Hàng của một cơ hội CRM, ghép sẵn sản phẩm Odoo (product = None: Odoo chưa có mã)."""
        self._check()
        if not to_int(opportunity_id):
            raise UserError("Chưa chọn cơ hội.")
        return {"lines": opportunity_lines(request.env, self._misa().crm_opportunity_products(to_int(opportunity_id)))}

    def _misa(self):
        return request.env["misa.api.utils"].sudo()
