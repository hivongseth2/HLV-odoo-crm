# -*- coding: utf-8 -*-
"""Hàng combo trên trang hỏi giá: mua combo = mua các THÀNH PHẦN của nó.

Combo ở Odoo là sản phẩm có BoM kiểu kit (phantom) — dựng bởi misa.api.utils.get_or_create_combo_product
(misa_fetch_po_button), sản phẩm cha để purchase_ok = False. NCC bán từng thành phần, nên thêm combo vào
phiếu hỏi giá là tách thành các mặt hàng con, số lượng nhân theo số combo (BoM lồng nhau tách tới cùng).

Combo chỉ có trên MISA CRM (Odoo chưa có): dựng xuống Odoo bằng chính hàm của misa_fetch_po_button
(get_combo_misa + _sync_combo_to_odoo) — không dựng BoM theo cách thứ hai.
"""

from odoo.exceptions import UserError

COMBO_UOM = "Bộ"


def kit_bom(product):
    """BoM kit (phantom) của sản phẩm, hoặc recordset rỗng / None (chưa cài mrp) khi không phải combo."""
    if not product or "mrp.bom" not in product.env:
        return None
    return product.env["mrp.bom"].sudo()._bom_find(product, bom_type="phantom")[product]


def kit_components(product, qty, uom=None):
    """Thành phần của combo cho ``qty`` combo (theo ĐVT ``uom``, mặc định ĐVT sản phẩm).

    Trả list ``(sản phẩm thành phần, số lượng, ĐVT dòng BoM)`` — BoM lồng nhau đã tách tới hàng lá;
    sản phẩm không phải combo → None.
    """
    bom = kit_bom(product)
    if not bom:
        return None
    factor = (uom or product.uom_id)._compute_quantity(qty, bom.product_uom_id) / (bom.product_qty or 1.0)
    _boms, lines = bom.explode(product, factor)
    return [(line.product_id, data["qty"], line.product_uom_id) for line, data in lines]


def import_crm_combo(env, code):
    """Sản phẩm combo trên Odoo dựng từ combo ``code`` trên MISA CRM (tạo cả thành phần chưa có).

    Lỗi (UserError): CRM không có mã / không phải combo / Odoo không dựng được BoM.
    Chạy với env của bên gọi — bên gọi tự sudo (sale không có quyền tạo sản phẩm).
    """
    misa = env["misa.api.utils"]
    try:
        combo = misa.get_combo_misa(code)
    except Exception as error:  # noqa: BLE001 — hàm CRM ném Exception thường, đổi sang lời cho sale đọc
        raise UserError(str(error)) from error
    result = misa._sync_combo_to_odoo(combo["code"], combo["name"], COMBO_UOM, [{
        "code": item["code"], "name": item["name"], "unit_name": item["unit"], "quantity": item["quantity"],
    } for item in combo["components"]])
    if not result["odoo_synced"]:
        raise UserError(result["odoo_note"])
    product = env["product.product"].search([("default_code", "=", combo["code"])], limit=1)
    if not product:
        raise UserError(f"Không dựng được combo {code} trên Odoo.")
    return product
