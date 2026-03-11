# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class DeliveryPlannerController(http.Controller):

    @http.route('/hlv_sale_delivery_planning/print_picking_slips', type='json', auth='user', methods=['POST'])
    def print_picking_slips(self, sale_order_ids):
        """
        In phiếu lấy hàng cho các đơn hàng đã chọn.
        Loại bỏ các phiếu đã hoàn thành (state = 'done').
        
        :param sale_order_ids: List of sale.order IDs
        :return: Dict with URL to PDF report
        """
        try:
            if not sale_order_ids:
                return {'error': {'message': 'Không có đơn hàng nào được chọn'}}

            # Get sale orders
            sale_orders = request.env['sale.order'].browse(sale_order_ids)
            if not sale_orders.exists():
                return {'error': {'message': 'Không tìm thấy đơn hàng'}}

            # Get all pickings from selected sale orders
            # Filter: only outgoing, not done, not cancelled
            all_pickings = sale_orders.mapped('picking_ids').filtered(
                lambda p: p.picking_type_code == 'outgoing' 
                and p.state not in ['done', 'cancel']
            )

            if not all_pickings:
                return {'error': {'message': 'Không có phiếu lấy hàng nào cần in (tất cả đã hoàn thành hoặc đã hủy)'}}

            # Use standard Odoo stock picking report
            # The report XML ID is usually 'stock.action_report_delivery'
            report = request.env.ref('stock.action_report_delivery', raise_if_not_found=False)
            
            if not report:
                # Fallback to generic stock picking report
                report = request.env.ref('stock.action_report_picking', raise_if_not_found=False)
            
            if not report:
                return {'error': {'message': 'Không tìm thấy report template cho phiếu lấy hàng'}}

            # Generate PDF
            pdf_content, _ = report._render_qweb_pdf(report.id, all_pickings.ids)

            if not pdf_content:
                return {'error': {'message': 'Không thể tạo PDF'}}

            # Create attachment
            picking_names = ', '.join(all_pickings.mapped('name')[:5])
            if len(all_pickings) > 5:
                picking_names += f' (+{len(all_pickings) - 5} phiếu khác)'
            
            filename = f'Phieu_Lay_Hang_{picking_names}.pdf'
            attachment = request.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': pdf_content,
                'res_model': 'stock.picking',
                'res_id': False,  # Not linked to specific picking
                'mimetype': 'application/pdf',
            })

            # Return download URL
            download_url = f'/web/content/{attachment.id}?download=true'
            
            return {
                'success': True,
                'url': download_url,
                'picking_count': len(all_pickings),
                'message': f'Đã tạo PDF cho {len(all_pickings)} phiếu lấy hàng'
            }

        except Exception as e:
            _logger.error("Error printing picking slips: %s", str(e), exc_info=True)
            return {'error': {'message': f'Lỗi khi in phiếu lấy hàng: {str(e)}'}}
