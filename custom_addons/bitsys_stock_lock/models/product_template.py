# -*- coding: utf-8 -*-
##############################################################################
#                                                                            #
#  🚀 Powered by Bit Systems, S.A. | https://bitsysgt.odoo.com               #
#                                                                            #
#  🏆 Innovation in Odoo, Excellence in Solutions                            #
#                                                                            #
#  🔒 This module is part of Bit Systems, S.A.                               #
#  📜 See LICENSE file for copyright and licensing details.                  #
#                                                                            #
#  🌎 Desarrollado por Bit Systems, S.A. | https://bitsysgt.odoo.com         #
#                                                                            #
#  💡 Innovación en Odoo, Excelencia en Soluciones                           #
#                                                                            #
#  🔐 Este módulo es parte de Bit Systems, S.A.                              #
#  📄 Consulte el archivo LICENSE para detalles sobre derechos de autor      #
#      y licencias.                                                          #
#                                                                            #
##############################################################################
from odoo import fields, models

class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_negative_allowed  = fields.Boolean(
        string="Allow Negative?",
        help="Enable this option to allow negative stock levels for this product. "
            "If not enabled, stock moves that would result in negative stock "
            "are blocked, unless allowed by the product category."
    )
