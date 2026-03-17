import logging
import hmac
import re
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

PW_PARAM_KEY = "website_public_inventory_18.search_password"
SESSION_KEY_OK = "inv_pw_ok"


def _get_pw():
    return request.env["ir.config_parameter"].sudo().get_param(PW_PARAM_KEY, default="") or ""


def _check_pw():
    conf = _get_pw()
    if not conf:
        return True
    return bool(request.session.get(SESSION_KEY_OK))


def _parse_tax_rate(tax_text):
    if not tax_text:
        return None
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(tax_text))
    return float(m.group(1)) if m else None


class MisaProductImportController(http.Controller):

    @http.route('/misa/product/import', type='http', auth='public', website=True)
    def product_import_page(self, **kw):
        """Trang import sản phẩm từ MISA CRM"""
        conf_pw = _get_pw()

        # --- AUTH ---
        if conf_pw and not _check_pw():
            if request.httprequest.method == "POST":
                inp = (kw.get("inv_password") or "").strip()
                if hmac.compare_digest(inp, conf_pw):
                    request.session[SESSION_KEY_OK] = True
                    return request.redirect("/misa/product/import")
                else:
                    return request.render("hlv_misa_product_import.page_product_import", {
                        "pw_ok": False, "pw_err": True,
                    })
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": False, "pw_err": False,
            })

        # --- LOGGED IN ---
        return request.render("hlv_misa_product_import.page_product_import", {
            "pw_ok": True,
            "step": "input",
        })

    @http.route('/misa/product/search', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def product_search(self, **kw):
        """Tìm kiếm sản phẩm trên MISA CRM"""
        if not _check_pw():
            return request.redirect("/misa/product/import")

        code = (kw.get("product_code") or "").strip()
        if not code:
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input",
                "error": "Vui lòng nhập mã sản phẩm.",
            })

        # Kiểm tra đã tồn tại trong Odoo
        existing = request.env['product.template'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if existing:
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input",
                "error": f"Sản phẩm mã '{code}' đã tồn tại trong Odoo! (Tên: {existing.name})",
            })

        # Tìm trên MISA CRM
        try:
            results = request.env['misa.api.utils'].sudo().search_product_by_name(
                name=None, code=code, limit=10
            )
        except Exception as e:
            _logger.exception("MISA search error")
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input", "code": code,
                "error": f"Lỗi khi tìm trên MISA CRM: {e}",
            })

        if not results:
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input", "code": code,
                "error": f"Không tìm thấy sản phẩm mã '{code}' trên MISA CRM.",
            })

        # Ưu tiên khớp chính xác
        matched = next(
            (p for p in results if p.get('code') and p['code'].strip().upper() == code.upper()),
            results[0]
        )

        return request.render("hlv_misa_product_import.page_product_import", {
            "pw_ok": True,
            "step": "confirm",
            "code": code,
            "product": matched,
        })

    @http.route('/misa/product/create', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def product_create(self, **kw):
        """Tạo sản phẩm trong Odoo"""
        if not _check_pw():
            return request.redirect("/misa/product/import")

        code = (kw.get("product_code") or "").strip()
        name = (kw.get("product_name") or code).strip()
        price = float(kw.get("product_price") or 0)
        unit_name = (kw.get("product_unit") or "").strip()
        tax_text = (kw.get("product_tax") or "").strip()

        if not code:
            return request.redirect("/misa/product/import")

        # Double-check
        existing = request.env['product.template'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if existing:
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input",
                "error": f"Sản phẩm mã '{code}' đã tồn tại!",
            })

        # Build vals
        vals = {
            'name': name,
            'default_code': code,
            'list_price': price,
            'type': 'consu',
            'is_storable': True,
        }

        if unit_name:
            uom = request.env['uom.uom'].sudo().search([('name', '=', unit_name)], limit=1)
            if uom:
                vals['uom_id'] = uom.id
                vals['uom_po_id'] = uom.id

        if tax_text:
            tax_rate = _parse_tax_rate(tax_text)
            if tax_rate is not None:
                try:
                    tax = request.env['odoo.utils'].sudo()._get_or_create_vn_vat(tax_rate, use='sale')
                    if tax:
                        vals['taxes_id'] = [(6, 0, [tax.id])]
                except Exception:
                    pass

        try:
            product = request.env['product.template'].sudo().create(vals)
            _logger.info("Đã tạo SP từ MISA CRM: %s [%s] (ID: %s)", name, code, product.id)
        except Exception as e:
            _logger.exception("Create product error")
            return request.render("hlv_misa_product_import.page_product_import", {
                "pw_ok": True, "step": "input", "code": code,
                "error": f"Lỗi khi tạo sản phẩm: {e}",
            })

        return request.render("hlv_misa_product_import.page_product_import", {
            "pw_ok": True,
            "step": "done",
            "created_product": {
                "name": product.name,
                "code": product.default_code,
                "id": product.id,
            },
        })
