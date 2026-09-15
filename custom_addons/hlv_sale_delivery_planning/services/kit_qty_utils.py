# -*- coding: utf-8 -*-
"""Quy số lượng thành phần về số bộ kit (phantom BOM).

Kit nổ ra thành các move thành phần, nên mọi chỗ muốn biết "đã giao / đã đóng
mấy BỘ" đều phải chia ngược theo định mức BOM. Gom về một hàm để bảng tiền của
phiếu xuất kho và bảng sản phẩm của đơn không ra hai con số khác nhau.
"""


def kit_qty_from_components(bom, get_component_qty):
    """Số bộ kit hoàn chỉnh ráp được từ số lượng thành phần đang có.

    Bộ hoàn chỉnh bị chặn bởi thành phần thiếu nhất, nên lấy min của
    (số lượng thành phần / định mức mỗi bộ) trên tất cả dòng BOM.

    :param bom: record mrp.bom kiểu phantom (1 bản), hoặc giá trị falsy.
    :param get_component_qty: hàm nhận record product.product của một dòng BOM,
        trả về số lượng thành phần đó đang có (float).
    :return: float số bộ — 0.0 nếu không có bom, hoặc BOM không có dòng nào
        dùng được (product_qty <= 0 / thiếu sản phẩm).
    """
    if not bom:
        return 0.0
    bom_qty = bom.product_qty or 1.0
    ratio = None
    for bom_line in bom.bom_line_ids:
        qty_per_kit = (bom_line.product_qty or 0.0) / bom_qty
        if qty_per_kit <= 0 or not bom_line.product_id:
            continue
        candidate = (get_component_qty(bom_line.product_id) or 0.0) / qty_per_kit
        ratio = candidate if ratio is None else min(ratio, candidate)
    return ratio or 0.0
