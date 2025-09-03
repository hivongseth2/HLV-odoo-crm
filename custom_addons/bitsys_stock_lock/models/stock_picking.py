# -*- coding: utf-8 -*-
##############################################################################
#                                                                            #
#  🚀 Powered by Bit Systems, S.A. | https://bitsysgt.odoo.com               #
#  🏆 Innovation in Odoo, Excellence in Solutions                            #
#  🔒 This module is part of Bit Systems, S.A.                               #
#  📜 See LICENSE file for copyright and licensing details.                  #
#                                                                            #
#  🌎 Desarrollado por Bit Systems, S.A. | https://bitsysgt.odoo.com         #
#  💡 Innovación en Odoo, Excelencia en Soluciones                           #
#  🔐 Este módulo es parte de Bit Systems, S.A.                              #
#  📄 Consulte el archivo LICENSE para detalles sobre derechos de autor      #
#      y licencias.                                                          #
#                                                                            #
##############################################################################

from odoo.exceptions import ValidationError
from odoo import models, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        lines_to_check = self.move_ids_without_package.filtered(lambda line: not line.product_id.is_negative_allowed and self.picking_type_code != 'incoming')
        for line in lines_to_check:
            product_id, quantity = line.product_id, line.product_uom_qty
            if product_id.tracking == 'lot':
                move_lines = line.move_line_ids.filtered(lambda d: d.lot_id.product_qty > d.quantity)
                available_qty = sum(move_lines.mapped('lot_id.product_qty'))
                if quantity > available_qty:
                    raise ValidationError(_("Cannot complete delivery for '%s' due to insufficient stock. Negative stock is not allowed.") % product_id.display_name)
            else:
                if quantity > product_id.qty_available:
                    raise ValidationError(_("Cannot complete delivery for '%s' due to insufficient stock. Negative stock is not allowed.") % product_id.display_name)
        return super(StockPicking, self).button_validate()