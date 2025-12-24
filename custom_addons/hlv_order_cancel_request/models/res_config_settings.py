from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Website password
    cancel_request_password = fields.Char(
        string='Mật khẩu trang web', 
        config_parameter='hlv_order_cancel_request.website_password', 
        help="Mật khẩu truy cập cho trang yêu cầu hủy đơn."
    )
    
    # Accountant Zalo UIDs - supports multiple (comma or newline separated)
    cancel_request_accountant_uid = fields.Text(
        string='Zalo ID Kế Toán', 
        config_parameter='hlv_order_cancel_request.accountant_zalo_uid', 
        help="""Zalo User ID của Kế toán để nhận thông báo.
Hỗ trợ nhiều UID: ngăn cách bằng dấu phẩy hoặc mỗi UID một dòng.
Ví dụ: 1234567890,9876543210
Hoặc:
1234567890
9876543210"""
    )
    
    # Warehouse Zalo UIDs - Mapping format: WAREHOUSE_CODE:UID1,UID2
    # Example: TSN:123456789,987654321
    #          KBC:111222333
    cancel_request_warehouse_mapping = fields.Text(
        string='Mapping Kho → Zalo ID Thủ Kho',
        config_parameter='hlv_order_cancel_request.warehouse_zalo_mapping',
        help="""Mapping mã kho với Zalo User ID của Thủ kho.
Mỗi dòng 1 kho, dạng: MÃ_KHO:ZALO_UID1,ZALO_UID2
Hỗ trợ nhiều UID mỗi kho (phân cách bằng dấu phẩy).
Ví dụ:
TSN:1234567890123456789,9999888877776666
KBC:9876543210987654321
TSNSR:1112223334445556667"""
    )
