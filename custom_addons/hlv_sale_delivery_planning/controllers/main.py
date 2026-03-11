# -*- coding: utf-8 -*-
import base64

from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class DeliveryPlannerController(http.Controller):

    @http.route('/hlv_sale_delivery_planning/print_picking_slips', type='json', auth='user', methods=['POST'])
    def print_picking_slips(self, sale_order_ids=None, **kwargs):
        """
        In phiếu lấy hàng cho các đơn hàng đã chọn.
        Loại bỏ các phiếu đã hoàn thành (state = 'done').
        
        :param sale_order_ids: List of sale.order IDs
        :return: Dict with URL to PDF report
        """
        try:
            # Hỗ trợ nhiều kiểu payload (json route / json-rpc params)
            if sale_order_ids is None:
                sale_order_ids = kwargs.get('sale_order_ids')
            if sale_order_ids is None and isinstance(request.jsonrequest, dict):
                sale_order_ids = (request.jsonrequest.get('params') or {}).get('sale_order_ids')

            # Chuẩn hóa dữ liệu ID về list int
            if isinstance(sale_order_ids, (set, tuple)):
                sale_order_ids = list(sale_order_ids)
            if not isinstance(sale_order_ids, list):
                sale_order_ids = [sale_order_ids] if sale_order_ids else []
            sale_order_ids = [int(x) for x in sale_order_ids if x]

            if not sale_order_ids:
                return {'error': {'message': 'Không có đơn hàng nào được chọn'}}

            # Get sale orders
            sale_orders = request.env['sale.order'].browse(sale_order_ids)
            if not sale_orders.exists():
                return {'error': {'message': 'Không tìm thấy đơn hàng'}}

            picking_obj = request.env['stock.picking']

            # Gom pickings theo nhiều kiểu liên kết để tránh bỏ sót dữ liệu thực tế.
            linked_pickings = sale_orders.mapped('picking_ids')
            linked_pickings |= picking_obj.search([
                ('sale_id', 'in', sale_orders.ids),
                ('picking_type_code', '=', 'outgoing'),
                ('state', 'not in', ['done', 'cancel']),
            ])
            linked_pickings |= picking_obj.search([
                ('origin', 'in', sale_orders.mapped('name')),
                ('picking_type_code', '=', 'outgoing'),
                ('state', 'not in', ['done', 'cancel']),
            ])
            linked_pickings |= picking_obj.search([
                ('move_ids.sale_line_id.order_id', 'in', sale_orders.ids),
                ('picking_type_code', '=', 'outgoing'),
                ('state', 'not in', ['done', 'cancel']),
            ])

            all_pickings = linked_pickings.filtered(
                lambda p: p.picking_type_code == 'outgoing' and p.state not in ['done', 'cancel']
            ).sorted(key=lambda p: (p.scheduled_date or p.create_date, p.id))

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
            pdf_content, _ = report._render_qweb_pdf(all_pickings.ids)

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
                'datas': base64.b64encode(pdf_content),
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
