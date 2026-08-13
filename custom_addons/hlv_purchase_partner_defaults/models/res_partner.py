from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    hlv_po_payment_term = fields.Char(string='Điều kiện thanh toán (mua hàng)')
    hlv_po_delivery_term = fields.Char(string='Điều khoản giao hàng (mua hàng)')
    hlv_po_delivery_address = fields.Char(string='Địa điểm giao hàng (mua hàng)')
