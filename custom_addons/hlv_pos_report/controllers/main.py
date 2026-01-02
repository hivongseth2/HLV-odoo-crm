# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)


class PosReportController(http.Controller):

    @http.route('/pos/report/available', type='json', auth='user', methods=['POST'])
    def get_available_reports(self):
        """
        API để lấy danh sách các báo cáo có sẵn cho POS.
        """
        try:
            reports = request.env['pos.order'].get_available_reports_for_picking()
            return {'success': True, 'reports': reports}
        except Exception as e:
            _logger.error("Error getting available reports: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/pos/report/print', type='json', auth='user', methods=['POST'])
    def print_report(self, order_id, report_id):
        """
        API để in báo cáo cho POS order.
        """
        try:
            result = request.env['pos.order'].print_report_for_pos_order(order_id, report_id)
            return result
        except Exception as e:
            _logger.error("Error printing report: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/pos/report/pickings/<int:order_id>', type='json', auth='user', methods=['POST'])
    def get_pickings(self, order_id):
        """
        API để lấy danh sách pickings của POS order.
        """
        try:
            order = request.env['pos.order'].browse(order_id)
            if not order.exists():
                return {'success': False, 'error': 'Order not found'}
            
            picking_ids = order.get_picking_ids_for_pos_order()
            return {'success': True, 'picking_ids': picking_ids}
        except Exception as e:
            _logger.error("Error getting pickings: %s", str(e))
            return {'success': False, 'error': str(e)}
