# -*- coding: utf-8 -*-
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DeliveryPlannerController(http.Controller):

    @http.route('/hlv_sale_delivery_planning/print_picking_slips', type='json', auth='user', methods=['POST'])
    def print_picking_slips(self, sale_order_ids=None, **kwargs):
        """
        In phiếu lấy hàng cho các đơn hàng đã chọn.
        Loại bỏ các phiếu đã hoàn thành (state = 'done').
        """
        try:
            if sale_order_ids is None:
                sale_order_ids = kwargs.get('sale_order_ids')
            if sale_order_ids is None and isinstance(request.jsonrequest, dict):
                sale_order_ids = (request.jsonrequest.get('params') or {}).get('sale_order_ids')

            if isinstance(sale_order_ids, (set, tuple)):
                sale_order_ids = list(sale_order_ids)
            if not isinstance(sale_order_ids, list):
                sale_order_ids = [sale_order_ids] if sale_order_ids else []
            sale_order_ids = [int(x) for x in sale_order_ids if x]

            if not sale_order_ids:
                return {'success': False, 'message': 'Không có đơn hàng nào được chọn'}

            sale_orders = request.env['sale.order'].browse(sale_order_ids).exists()
            if not sale_orders:
                return {'success': False, 'message': 'Không tìm thấy đơn hàng'}

            picking_obj = request.env['stock.picking']

            linked_pickings = sale_orders.mapped('picking_ids')
            linked_pickings |= picking_obj.search([
                ('sale_id', 'in', sale_orders.ids),
                ('picking_type_code', 'in', ['outgoing', 'internal']),
                ('state', 'not in', ['done', 'cancel']),
            ])
            linked_pickings |= picking_obj.search([
                ('origin', 'in', sale_orders.mapped('name')),
                ('picking_type_code', 'in', ['outgoing', 'internal']),
                ('state', 'not in', ['done', 'cancel']),
            ])
            linked_pickings |= picking_obj.search([
                ('move_ids.sale_line_id.order_id', 'in', sale_orders.ids),
                ('picking_type_code', 'in', ['outgoing', 'internal']),
                ('state', 'not in', ['done', 'cancel']),
            ])

            all_pickings = linked_pickings.filtered(
                lambda p: p.picking_type_code in ['outgoing', 'internal'] and p.state not in ['done', 'cancel']
            ).sorted(key=lambda p: (p.scheduled_date or p.create_date, p.id))

            if not all_pickings:
                return {'success': False, 'message': 'Không có phiếu lấy hàng nào cần in (tất cả đã hoàn thành hoặc đã hủy)'}

            has_internal = any(p.picking_type_code == 'internal' for p in all_pickings)
            report = request.env.ref(
                'stock.action_report_picking' if has_internal else 'stock.action_report_delivery',
                raise_if_not_found=False,
            )
            if not report:
                report = request.env.ref('stock.action_report_delivery', raise_if_not_found=False)
            if not report:
                return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

            pdf_content, _ = report._render_qweb_pdf(all_pickings.ids)
            if not pdf_content:
                return {'success': False, 'message': 'Không thể tạo PDF'}

            picking_names = ', '.join(all_pickings.mapped('name')[:5])
            if len(all_pickings) > 5:
                picking_names += f' (+{len(all_pickings) - 5} phiếu khác)'

            filename = f'Phieu_Lay_Hang_{picking_names}.pdf'
            attachment = request.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'stock.picking',
                'res_id': False,
                'mimetype': 'application/pdf',
            })

            return {
                'success': True,
                'url': f'/web/content/{attachment.id}?download=true',
                'picking_count': len(all_pickings),
                'message': f'Đã tạo PDF cho {len(all_pickings)} phiếu lấy hàng',
            }
        except Exception as e:
            _logger.error("Error printing picking slips: %s", str(e), exc_info=True)
            return {'success': False, 'message': f'Lỗi khi in phiếu lấy hàng: {str(e)}'}