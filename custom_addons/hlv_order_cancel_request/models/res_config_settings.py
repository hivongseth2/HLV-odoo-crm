from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cancel_request_password = fields.Char(string='Cancellation Request Website Password', config_parameter='hlv_order_cancel_request.website_password', help="Password for salespeople to access the cancellation request form.")
    cancel_request_accountant_uid = fields.Char(string='Accountant Zalo ID', config_parameter='hlv_order_cancel_request.accountant_zalo_uid', help="Zalo User ID of the Accountant to verify requests.")
    cancel_request_warehouse_uid = fields.Char(string='Warehouse Manager Zalo ID', config_parameter='hlv_order_cancel_request.warehouse_zalo_uid', help="Zalo User ID of the Warehouse Manager to verify requests.")
