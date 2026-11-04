# -*- coding: utf-8 -*-
"""Đề xuất của thu mua có thêm SL / mã (po_proposal_change.py): đề xuất tạo trước bản này chưa có "SL trên đơn" (old_qty)
— lấy SL hiện tại của dòng đơn mua. Thiếu thì SL đích (_target_qty) ra 0 và duyệt sẽ đưa dòng về 0."""


def migrate(cr, version):
    cr.execute("""
        UPDATE hlv_po_price_proposal p
           SET old_qty = l.product_qty
          FROM purchase_order_line l
         WHERE l.id = p.order_line_id AND COALESCE(p.old_qty, 0) = 0
    """)
