from odoo import models

class IrActionsClient(models.Model):
    _inherit = 'ir.actions.client'

    def _stock_barcode_data(self, model, res_id):
        return self.env['ir.ui.menu']._stock_barcode_data(model, res_id)
