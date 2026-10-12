# -*- coding: utf-8 -*-
"""Ghi chú dòng YCMH chuyển từ hlv_note (3.66–3.70, chỉ có trên DB đã cài các bản đó) sang misa_note — trường ghi chú
có sẵn của misa_purchase_request_sync. Chỉ chép vào dòng misa_note đang trống. DB chưa từng có cột hlv_note (vd prd
nhảy thẳng từ 3.60) thì bỏ qua."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'purchase_request_line' AND column_name = 'hlv_note'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE purchase_request_line
           SET misa_note = hlv_note
         WHERE COALESCE(hlv_note, '') <> '' AND COALESCE(misa_note, '') = ''
    """)
