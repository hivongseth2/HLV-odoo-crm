from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Website password
    cancel_request_password = fields.Char(
        string='Mật khẩu trang web', 
        config_parameter='hlv_order_cancel_request.website_password', 
        help="Mật khẩu truy cập cho trang yêu cầu hủy đơn."
    )
    
    # Accountant Zalo UIDs - comma separated
    cancel_request_accountant_uid = fields.Char(
        string='Zalo ID Kế Toán', 
        config_parameter='hlv_order_cancel_request.accountant_zalo_uid', 
        help="Zalo User ID của Kế toán. Nhiều UID ngăn cách bằng dấu phẩy. VD: 123456,789012"
    )
    
    # Warehouse Zalo UIDs - format: KHO1:UID1,UID2|KHO2:UID3
    cancel_request_warehouse_mapping = fields.Char(
        string='Mapping Kho → Zalo ID Thủ Kho',
        config_parameter='hlv_order_cancel_request.warehouse_zalo_mapping',
        help="Format: KHO1:UID1,UID2|KHO2:UID3|KHO3:UID4. VD: TSN:123456|KBC:789012,111222|TSNSR:333444"
    )
