import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_done(self):
        res = super().action_done()
        for picking in self:
            try:
                config = self.env['hlv.zalo.zns'].sudo().search([], limit=1)
                if not config or not config.template_id:
                    continue
                partner = picking.partner_id or (picking.move_lines and picking.move_lines[0].partner_id)
                msisdn = partner and (partner.mobile or partner.phone)
                if not msisdn:
                    continue
                params = {
                    "ORDER_NO": picking.name,
                    "PICKED_AT": fields.Datetime.to_string(fields.Datetime.now()),
                }
                config.sudo().send_zns(msisdn, params)
            except Exception as e:
                _logger.exception("Error sending ZNS on picking done: %s", e)
        return res
