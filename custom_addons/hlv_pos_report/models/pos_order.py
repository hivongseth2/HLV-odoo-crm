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
        Tìm cả picking ở mọi state (trừ cancel).
        """
        self.ensure_one()
        pickings = self.env['stock.picking'].browse()
        
        # Cách 1: Tìm trực tiếp qua field pos_order_id (nếu có)
        try:
            pickings = self.env['stock.picking'].sudo().search([
                ('pos_order_id', '=', self.id),
                ('state', '!=', 'cancel'),
            ])
        except Exception as e:
            _logger.warning("POS Report: pos_order_id field not found: %s", str(e))
        
        # Cách 2: Tìm qua picking_ids của order (nếu có relation)
        if not pickings and hasattr(self, 'picking_ids'):
            pickings = self.picking_ids.filtered(lambda p: p.state != 'cancel')
        
        # Cách 3: Tìm qua origin chứa tên order
        if not pickings:
            pickings = self.env['stock.picking'].sudo().search([
                ('origin', 'ilike', self.name),
                ('state', '!=', 'cancel'),
            ])
        
        # Cách 4: Tìm qua session (POS thường tạo picking qua session)
        if not pickings and self.session_id:
            pickings = self.env['stock.picking'].sudo().search([
                ('pos_session_id', '=', self.session_id.id),
                ('origin', 'ilike', self.name),
                ('state', '!=', 'cancel'),
            ], limit=5)
        
        # Cách 5: Tìm qua sale_id nếu có
        if not pickings and hasattr(self, 'sale_order_id') and self.sale_order_id:
            pickings = self.sale_order_id.picking_ids.filtered(lambda p: p.state != 'cancel')
        
        _logger.info("POS Report: Found %d pickings for order %s (ID: %s)", 
                     len(pickings), self.name, self.id)
        
        if pickings:
            for p in pickings:
                _logger.info("  - Picking %s, state: %s", p.name, p.state)
        
        return pickings.ids

    @api.model
    def print_report_for_pos_order(self, order_id, report_id):
        """
        In báo cáo cho POS order.
        Trả về URL để mở PDF.
        """
        order = self.browse(order_id)
        if not order.exists():
            return {'error': 'Không tìm thấy đơn hàng'}
        
        picking_ids = order.get_picking_ids_for_pos_order()
        if not picking_ids:
            return {'error': 'Chưa có phiếu xuất kho cho đơn hàng này. Vui lòng đợi hệ thống tạo phiếu.'}
        
        report = self.env['ir.actions.report'].browse(report_id)
        if not report.exists():
            return {'error': 'Không tìm thấy mẫu biên bản'}
        
        # Trả về URL để frontend mở PDF
        picking_id = picking_ids[0]  # Lấy picking đầu tiên
        picking = self.env['stock.picking'].browse(picking_id)
        
        _logger.info("POS Report: Printing report for picking %s (state: %s)", 
                     picking.name, picking.state)
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        report_url = f"{base_url}/report/pdf/{report.report_name}/{picking_id}"
        
        _logger.info("POS Report: Generated report URL: %s", report_url)
        return {
            'success': True,
            'url': report_url,
            'picking_id': picking_id,
            'picking_name': picking.name,
            'picking_state': picking.state,
        }
