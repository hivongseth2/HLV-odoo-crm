# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class JTPickingController(http.Controller):

    @http.route('/hlv_delivery_jt/print_label/<int:attachment_id>', type='http', auth='user')
    def print_jt_label(self, attachment_id, **kwargs):
        """
        Render a print preview page for J&T label.
        """
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not attachment or not attachment.exists():
            return request.not_found()
        
        # Security check: ensure user has access to the picking
        if attachment.res_model == 'stock.picking' and attachment.res_id:
            picking = request.env['stock.picking'].browse(attachment.res_id)
            if not picking.exists() or not picking.check_access_rights('read', raise_exception=False):
                return request.not_found()

        return request.render('hlv_delivery_jt.jt_print_label_template', {
            'attachment_id': attachment_id,
        })
