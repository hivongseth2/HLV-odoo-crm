# -*- coding: utf-8 -*-
"""Người yêu cầu (x_misa_requested_by) của YCMH lập từ trang hỏi giá trước đây chỉ ghi mã sale (TRANTHIMYDUYEN);
YCMH đi từ MISA ghi dạng TÊN (MÃ). Đổi các YCMH cũ sang cùng dạng theo danh bạ sale (hlv.vendor.sale.contact) — mã
chưa có trong danh bạ thì giữ nguyên. Cùng quy tắc với vendor_quote_utils.requester_label."""


def migrate(cr, version):
    cr.execute("""
        UPDATE purchase_request pr
           SET x_misa_requested_by = TRIM(c.name) || ' (' || TRIM(pr.x_misa_requested_by) || ')'
          FROM hlv_vendor_sale_contact c
         WHERE pr.hlv_from_quote_page
           AND pr.x_misa_requested_by NOT LIKE '%%(%%'
           AND UPPER(TRIM(c.sale_code)) = UPPER(TRIM(pr.x_misa_requested_by))
           AND COALESCE(TRIM(c.name), '') <> ''
           AND UPPER(TRIM(c.name)) <> UPPER(TRIM(c.sale_code))
    """)
