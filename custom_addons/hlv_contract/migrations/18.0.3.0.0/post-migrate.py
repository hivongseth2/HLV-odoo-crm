# -*- coding: utf-8 -*-
"""Bản 3.0: biến nhập chuyển từ cột cố định trên hợp đồng sang biến riêng từng mẫu.

1. Tạo bộ biến cho các mẫu đã có (quét trường trong file mẫu).
2. Chép giá trị các cột cũ (buyer_name, payment_terms...) vào variable_values theo tên biến
   chuẩn. Cột cũ để nguyên trong DB (không xoá) để còn đối chiếu nếu cần quay lại bản cũ.
"""

from odoo import SUPERUSER_ID, api

OLD_COLUMNS = {
    'buyer_name': 'Ten_Ben_Mua',
    'buyer_address': 'Dia_Chi_Ben_Mua',
    'buyer_vat': 'Ma_So_Thue_Ben_Mua',
    'buyer_phone': 'Dien_Thoai_Ben_Mua',
    'buyer_fax': 'Fax_Ben_Mua',
    'buyer_representative': 'Nguoi_Dai_Dien_Ben_Mua',
    'buyer_position': 'Chuc_Vu_Ben_Mua',
    'delivery_time': 'Thoi_Gian_Giao_Hang',
    'delivery_place': 'Dia_Diem_Giao_Hang',
    'payment_terms': 'Dieu_Kien_Thanh_Toan',
    'court': 'Toa_An_Giai_Quyet',
    'main_product': 'Mat_Hang_Chinh',
    'expiry_date': 'Ngay_Het_Han',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hlv.contract.template'].with_context(active_test=False).search([])._sync_variables()

    cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'hlv_contract'")
    present = [col for col in OLD_COLUMNS if col in {row[0] for row in cr.fetchall()}]
    if not present:
        return
    cr.execute('SELECT id, %s FROM hlv_contract' % ', '.join(present))
    Contract = env['hlv.contract']
    for row in cr.fetchall():
        old = {OLD_COLUMNS[col]: str(value) for col, value in zip(present, row[1:]) if value not in (None, '')}
        if old:
            contract = Contract.browse(row[0])
            contract.write({'variable_values': dict(contract.variable_values or {}, **old)})
