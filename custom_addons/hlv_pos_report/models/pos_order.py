# -*- coding: utf-8 -*-
from odoo import api, models, fields
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def get_available_reports_for_picking(self):
        """
        Lấy danh sách các báo cáo có sẵn cho stock.picking từ module hlv_a4_report.
        Trả về list of dict: [{id, name, report_name}, ...]
        """
        # Tìm tất cả reports của hlv_a4_report cho model stock.picking
        reports = self.env['ir.actions.report'].sudo().search([
            ('model', '=', 'stock.picking'),
            ('report_name', 'like', 'hlv_a4_report.%'),
        ])
        
        result = []
        for report in reports:
            result.append({
                'id': report.id,
                'name': report.name,
                'report_name': report.report_name,
            })
        
        _logger.info("POS Report: Found %d available reports for stock.picking", len(result))
        return result

    def get_picking_ids_for_pos_order(self):
        """
        Lấy danh sách stock.picking liên quan đến POS order này.
        """
        self.ensure_one()
        pickings = self.env['stock.picking'].sudo().search([
            ('pos_order_id', '=', self.id),
            ('state', '!=', 'cancel'),
        ])
        
        if not pickings:
            # Thử tìm qua session
            pickings = self.env['stock.picking'].sudo().search([
                ('origin', 'ilike', self.name),
                ('state', '!=', 'cancel'),
            ])
        
        _logger.info("POS Report: Found %d pickings for order %s", len(pickings), self.name)
        return pickings.ids

    @api.model
    def print_report_for_pos_order(self, order_id, report_id):
        """
        In báo cáo cho POS order.
        Trả về URL để mở PDF.
        """
        order = self.browse(order_id)
        if not order.exists():
            return {'error': 'Order not found'}
        
        picking_ids = order.get_picking_ids_for_pos_order()
        if not picking_ids:
            return {'error': 'No picking found for this order'}
        
        report = self.env['ir.actions.report'].browse(report_id)
        if not report.exists():
            return {'error': 'Report not found'}
        
        # Trả về URL để frontend mở PDF
        picking_id = picking_ids[0]  # Lấy picking đầu tiên
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        report_url = f"{base_url}/report/pdf/{report.report_name}/{picking_id}"
        
        _logger.info("POS Report: Generated report URL: %s", report_url)
        return {
            'success': True,
            'url': report_url,
            'picking_id': picking_id,
        }
