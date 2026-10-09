# -*- coding: utf-8 -*-
"""Tạo sản phẩm Odoo từ hàng có trên MISA CRM — một chỗ cho mọi nơi cần (trang
/misa/product/import, trang hỏi giá NCC /hoi-gia-ncc khi CRM có hàng mà Odoo chưa có).
"""
import logging

from odoo import Command, models
from odoo.exceptions import UserError

from .crm_product import exact_code_match, parse_tax_rate

_logger = logging.getLogger(__name__)
CANDIDATE_LIMIT = 20


class MisaProductImport(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def crm_product_candidates(self, search, limit=CANDIDATE_LIMIT):
        """Hàng trên CRM theo mã (chứa), không thấy thì theo tên. Mỗi dict kết quả CRM thêm
        ``odoo_exists`` = Odoo đã có sản phẩm cùng mã. ``search`` rỗng → []."""
        search = (search or '').strip()
        if not search:
            return []
        results = self._crm_search(code=search, limit=limit) or self._crm_search(name=search, limit=limit)
        codes = [(p.get('code') or '').strip() for p in results if p.get('code')]
        existing = set(self.env['product.product'].with_context(active_test=False).search(
            [('default_code', 'in', codes)]).mapped('default_code')) if codes else set()
        return [dict(p, odoo_exists=(p.get('code') or '').strip() in existing) for p in results]

    def import_product_from_crm(self, code):
        """Sản phẩm Odoo cho đúng mã ``code`` trên CRM; chưa có thì tạo từ dữ liệu CRM.

        Trả (product.product, True nếu vừa tạo). Odoo đã có mã → trả sản phẩm đó, không sửa gì.
        Tạo: tên, ĐVT (odoo.utils._get_or_create_uom), giá bán, giá vốn, thuế bán + thuế mua theo
        % VAT trên CRM; mua được và bán được.
        UserError: mã trống; mã đang lưu trữ trong Odoo; CRM không có ĐÚNG mã đó; hàng combo
        (combo cần dựng thành phần — tạo theo luồng đơn bán, không tạo thành hàng đơn).
        """
        code = (code or '').strip()
        if not code:
            raise UserError("Thiếu mã hàng.")
        Product = self.env['product.product'].with_context(active_test=False)
        existing = Product.search([('default_code', '=', code)], limit=1)
        if existing and not existing.active:
            raise UserError(f"Mã '{code}' đã có trong Odoo nhưng đang lưu trữ — nhờ quản trị mở lại.")
        if existing:
            return existing, False
        match = exact_code_match(self._crm_search(code=code, limit=10), code)
        if not match:
            raise UserError(f"Không thấy hàng mã '{code}' trên MISA CRM.")
        if match.get('is_combo'):
            raise UserError(f"'{code}' là hàng combo trên MISA CRM — tạo qua đơn bán, không tạo ở đây.")
        crm_code = match['code'].strip()
        product = self.env['odoo.utils']._get_or_create_product(
            crm_code, match.get('name') or crm_code, match.get('unit') or 'Cái',
            cost=float(match.get('cost') or 0), sale_ok=True,
        )
        vals = {'list_price': float(match.get('price') or 0)}
        rate = parse_tax_rate(match.get('tax'))
        if rate is not None:
            # Hàm tạo thuế VAT VN đang ở các model đồng bộ MISA (cùng một luật) — dùng lại bản của
            # misa.po.fetch thay vì chép thêm một bản nữa.
            vat = self.env['misa.po.fetch']._get_or_create_vn_vat
            vals['taxes_id'] = [Command.set(vat(rate, use='sale').ids)]
            vals['supplier_taxes_id'] = [Command.set(vat(rate, use='purchase').ids)]
        product.product_tmpl_id.write(vals)
        _logger.info("Tạo sản phẩm %s từ MISA CRM (user %s)", crm_code, self.env.user.login)
        return product, True

    def _crm_search(self, name=None, code=None, limit=CANDIDATE_LIMIT):
        """search_product_by_name, lỗi gọi CRM đổi thành UserError đọc được."""
        try:
            return self.search_product_by_name(name=name, code=code, limit=limit) or []
        except Exception as exc:  # noqa: BLE001 — lỗi mạng / token / CRM trả lỗi đều báo cho người dùng
            _logger.warning("Gọi MISA CRM lỗi: %s", exc)
            raise UserError(f"Không gọi được MISA CRM: {exc}") from exc
