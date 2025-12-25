from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # Warehouse Zalo UIDs - format: KHO1:UID1,UID2|KHO2:UID3
    cancel_request_warehouse_mapping = fields.Char(
        string='Mapping Kho → Zalo ID Thủ Kho',
        config_parameter='hlv_order_cancel_request.warehouse_zalo_mapping',
        help="Format: KHO1:UID1,UID2|KHO2:UID3. VD: TSN:123456|KBC:789012,111222|TSNSR:333444"
    )
    
    # Accountant Zalo UIDs - format: KHO1:UID1,UID2|KHO2:UID3 (same format as warehouse)
    cancel_request_accountant_mapping = fields.Char(
        string='Mapping Kho → Zalo ID Kế Toán',
        config_parameter='hlv_order_cancel_request.accountant_zalo_mapping',
        help="Format: KHO1:UID1,UID2|KHO2:UID3. VD: TSN:123456|KBC:789012,111222|TSNSR:333444"
    )
