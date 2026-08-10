# -*- coding: utf-8 -*-
"""
Migration 1.1 - _compute_misa_invoice_sale_order_ids giờ chỉ gắn quan hệ với đơn bán ở
PHIẾU XUẤT KHO CUỐI (outgoing), loại các bước trung gian pick/pack của giao hàng nhiều bước
ra khỏi field misa_invoice_sale_order_ids (và theo đó là sale.order.misa_invoice_picking_ids).

Sửa code không tự làm lại dữ liệu STORED đã tính từ trước — cần recompute thủ công 1 lần.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Cài mới, chưa có dữ liệu cũ cần dọn lại.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    pickings = env['stock.picking'].search([
        ('picking_type_id.code', '!=', 'outgoing'),
        ('misa_invoice_sale_order_ids', '!=', False),
    ])
    _logger.info(
        "MISA invoice status report migration 1.1: xóa quan hệ đơn bán sai (pick/pack) "
        "trên %d phiếu không phải phiếu xuất kho cuối.",
        len(pickings),
    )
    if pickings:
        pickings.write({'misa_invoice_sale_order_ids': [(5, 0, 0)]})
