# -*- coding: utf-8 -*-
"""Hàng của một cơ hội trên MISA CRM → dòng hàng cho hộp lập phiếu hỏi giá (/hoi-gia-ncc).

Ghép theo mã hàng (CRM ProductIDText = default_code Odoo). Hàng Odoo chưa có thì để product =
None — trang tạo sản phẩm từ CRM (import_products) rồi mới thêm. Đọc theo quyền người dùng.
"""

from odoo.addons.misa_fetch_po_button.utils.text_match import uom_key

from .sale_page_payload import product_payload


def opportunity_lines(env, rows):
    """rows: kết quả misa.api.utils.crm_opportunity_products. Trả từng dòng CRM kèm "product":
    dòng hàng Odoo (số lượng CRM, ĐVT trùng tên ĐVT CRM nếu có) hoặc None khi Odoo chưa có mã."""
    codes = [row["code"] for row in rows]
    products = env["product.product"].search([("default_code", "in", codes), ("purchase_ok", "=", True)]) \
        if codes else env["product.product"]
    by_code = {product.default_code: product for product in products}
    return [
        dict(row, product=_line(by_code[row["code"]], row) if row["code"] in by_code else None)
        for row in rows
    ]


def _line(product, row):
    line = dict(product_payload(product), qty=row["qty"] or 1)
    uom = _same_name_uom(product, row["unit"])
    if uom:
        line.update(uom_id=uom.id, uom=uom.name)
    return line


def _same_name_uom(product, unit_name):
    """ĐVT cùng nhóm với ĐVT của sản phẩm, trùng tên ĐVT trên CRM (không phân biệt hoa thường) — số
    lượng CRM tính theo ĐVT đó. Không có → None: giữ ĐVT mua của sản phẩm."""
    key = uom_key(unit_name)
    if not key:
        return None
    uoms = product.env["uom.uom"].search([("category_id", "=", product.uom_id.category_id.id)])
    return uoms.filtered(lambda uom: uom_key(uom.name) == key)[:1] or None
