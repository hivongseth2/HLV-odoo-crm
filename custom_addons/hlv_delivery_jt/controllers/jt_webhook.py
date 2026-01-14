# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class JTWebhook(http.Controller):

    @http.route('/jt/webhook/status', type='json', auth='public', methods=['POST'], csrf=False)
    def jt_status_update(self, **post):
        """
        Handle J&T status updates
        Documentation usually specifies a POST with JSON body
        """
        data = request.jsonrequest
        _logger.info("J&T Webhook Received: %s", json.dumps(data))
        
        # J&T Webhook format varies, but usually contains billCode and status
        bill_code = data.get('billCode')
        status = data.get('statusName') or data.get('status')
        
        if bill_code:
            picking = request.env['stock.picking'].sudo().search([('jt_bill_code', '=', bill_code)], limit=1)
            if picking:
                picking.write({'jt_order_status': status})
                _logger.info("J&T Webhook: Updated picking %s with status %s", picking.name, status)
                return {'code': '1', 'msg': 'success'}
        
        return {'code': '0', 'msg': 'Picking not found or billCode missing'}
