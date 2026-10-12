# -*- coding: utf-8 -*-
"""Thông tin bên bán và mặc định của hợp đồng, lưu trên công ty.

Mẫu Word cũ ghi cứng thông tin bên bán; module này đưa vào công ty để mẫu mới dùng
biến Ten_Ben_Ban, Tai_Khoan_Ben_Ban... và đổi công ty không phải sửa file mẫu.
"""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    contract_seller_name = fields.Char(string='Tên bên bán (hợp đồng)')
    contract_seller_address = fields.Char(string='Địa chỉ bên bán')
    contract_seller_phone = fields.Char(string='Điện thoại bên bán')
    contract_seller_vat = fields.Char(string='MST bên bán')
    contract_seller_representative = fields.Char(string='Người đại diện bên bán')
    contract_seller_position = fields.Char(string='Chức vụ người đại diện')
    contract_seller_bank_account = fields.Char(string='Số tài khoản bên bán')
    contract_seller_bank_name = fields.Char(string='Ngân hàng bên bán')
    contract_court = fields.Char(string='Toà án giải quyết tranh chấp mặc định')
    contract_vat_rate = fields.Float(string='Thuế suất VAT mặc định (%)', default=8.0)

    def _contract_seller_vars(self):
        """Biến bên bán cho hợp đồng, lấy từ công ty. Trường trống -> chuỗi rỗng."""
        self.ensure_one()
        return {
            'Ten_Ben_Ban': self.contract_seller_name or self.name or '',
            'Dia_Chi_Ben_Ban': self.contract_seller_address or '',
            'Dien_Thoai_Ben_Ban': self.contract_seller_phone or '',
            'Ma_So_Thue_Ben_Ban': self.contract_seller_vat or '',
            'Nguoi_Dai_Dien_Ben_Ban': self.contract_seller_representative or '',
            'Chuc_Vu_Ben_Ban': self.contract_seller_position or '',
            'Tai_Khoan_Ben_Ban': self.contract_seller_bank_account or '',
            'Ngan_Hang_Ben_Ban': self.contract_seller_bank_name or '',
        }
