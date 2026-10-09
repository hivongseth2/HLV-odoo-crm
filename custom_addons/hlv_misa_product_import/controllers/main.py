import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.misa_fetch_po_button.utils.crm_product import exact_code_match

_logger = logging.getLogger(__name__)


class MisaProductImportController(http.Controller):
    """Trang import sản phẩm từ MISA CRM. Tìm và tạo sản phẩm dùng chung
    misa.api.utils.import_product_from_crm (misa_fetch_po_button) với trang hỏi giá NCC — hai nơi
    tạo sản phẩm giống hệt nhau (tên, ĐVT, giá, thuế bán + thuế mua)."""

    def _render(self, **values):
        return request.render("hlv_misa_product_import.page_product_import", values)

    @http.route('/misa/product/import', type='http', auth='user', website=True)
    def product_import_page(self, **kw):
        """Trang import sản phẩm từ MISA CRM"""
        return self._render(step="input")

    @http.route('/misa/product/search', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def product_search(self, **kw):
        """Tìm kiếm sản phẩm trên MISA CRM"""
        code = (kw.get("product_code") or "").strip()
        if not code:
            return self._render(step="input", error="Vui lòng nhập mã sản phẩm.")

        existing = request.env['product.template'].sudo().search([('default_code', '=', code)], limit=1)
        if existing:
            return self._render(step="input", error=f"Sản phẩm mã '{code}' đã tồn tại trong Odoo! (Tên: {existing.name})")

        try:
            results = request.env['misa.api.utils'].sudo()._crm_search(code=code, limit=10)
        except UserError as exc:
            return self._render(step="input", code=code, error=str(exc))
        if not results:
            return self._render(step="input", code=code, error=f"Không tìm thấy sản phẩm mã '{code}' trên MISA CRM.")

        # Ưu tiên khớp đúng mã; không có thì đưa kết quả gần nhất để người dùng xác nhận.
        return self._render(step="confirm", code=code, product=exact_code_match(results, code) or results[0])

    @http.route('/misa/product/create', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def product_create(self, **kw):
        """Tạo sản phẩm trong Odoo từ đúng mã đã xác nhận (đọc lại dữ liệu từ CRM)."""
        code = (kw.get("product_code") or "").strip()
        if not code:
            return request.redirect("/misa/product/import")
        try:
            product, created = request.env['misa.api.utils'].sudo().import_product_from_crm(code)
        except UserError as exc:
            return self._render(step="input", code=code, error=str(exc))
        if not created:
            return self._render(step="input", error=f"Sản phẩm mã '{code}' đã tồn tại!")
        return self._render(step="done", created_product={
            "name": product.name,
            "code": product.default_code,
            "id": product.product_tmpl_id.id,
        })
