from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cancel_request_password = fields.Char(string='Mật khẩu trang web', config_parameter='hlv_order_cancel_request.website_password', help="Mật khẩu truy cập cho trang yêu cầu hủy đơn.")
    cancel_request_accountant_uid = fields.Char(string='Zalo ID Thủ Kho', config_parameter='hlv_order_cancel_request.accountant_zalo_uid', help="Zalo User ID của Thủ Kho để nhận thông báo.")
    cancel_request_warehouse_uid = fields.Char(string='Zalo ID Kế Toán', config_parameter='hlv_order_cancel_request.warehouse_zalo_uid', help="Zalo User ID của Kế toán để nhận thông báo.")
