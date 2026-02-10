# -*- coding: utf-8 -*-
"""
Auto transition return.sale.request when linked pickings are done.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()

        done_pickings = self.filtered(lambda p: p.state == "done")
        if done_pickings:
            done_pickings._sync_return_sale_requests_after_done()
        return res

    def _sync_return_sale_requests_after_done(self):
        ReturnSaleRequest = self.env["return.sale.request"].sudo()

        incoming_requests = ReturnSaleRequest.search([
            ("picking_in_id", "in", self.ids),
            ("state", "in", ["draft", "return_sale", "return_purchase"]),
        ])
        if incoming_requests:
            _logger.info(
                "Auto process incoming-done for %s return sale request(s) from pickings %s",
                len(incoming_requests),
                self.ids,
            )
            incoming_requests._process_after_incoming_done(check_done=False)

        outgoing_requests = ReturnSaleRequest.search([
            ("picking_out_id", "in", self.ids),
            ("state", "!=", "done"),
        ])
        if outgoing_requests:
            _logger.info(
                "Auto process outgoing-done for %s return sale request(s) from pickings %s",
                len(outgoing_requests),
                self.ids,
            )
            outgoing_requests._process_after_outgoing_done(check_done=False)
