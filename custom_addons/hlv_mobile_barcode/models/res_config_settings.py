from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    hlv_barcode_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        relation='res_company_stock_picking_type_barcode_rel',
        column1='company_id',
        column2='picking_type_id',
        string='Barcode Picking Types'
    )
    hlv_barcode_print_after_pack = fields.Boolean(
        string='Print Label after Put in Pack',
        default=False
    )

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hlv_barcode_picking_type_ids = fields.Many2many(
        related='company_id.hlv_barcode_picking_type_ids',
        readonly=False,
    )
    hlv_barcode_print_after_pack = fields.Boolean(
        related='company_id.hlv_barcode_print_after_pack',
        readonly=False,
    )
