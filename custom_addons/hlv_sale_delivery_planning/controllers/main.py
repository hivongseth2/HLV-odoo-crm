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

            # Fetch report by name "Hoạt động lấy hàng"
            report = request.env['ir.actions.report'].sudo().search([
                ('name', 'ilike', 'Hoạt động lấy hàng'),
            ], limit=1)
            
            if not report:
                return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

            try:
                # Render PDF with proper signature for Odoo 18
                picking_ids = list(all_pickings.ids)
                # In Odoo 18, _render_qweb_pdf needs report_ref as first arg
                pdf_content, _ = report._render_qweb_pdf(report.report_name, res_ids=picking_ids)
            except Exception as render_error:
                _logger.error("Error rendering PDF: %s", str(render_error), exc_info=True)
                return {'success': False, 'message': f'Lỗi khi tạo PDF: {str(render_error)}'}
            if not pdf_content:
                return {'success': False, 'message': 'Không thể tạo PDF'}

            picking_names = ', '.join(all_pickings.mapped('name')[:5])
            if len(all_pickings) > 5:
                picking_names += f' (+{len(all_pickings) - 5} phiếu khác)'

            filename = f'Phieu_Lay_Hang_{picking_names}.pdf'
            attachment = request.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content).decode('utf-8'),
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

    @http.route('/hlv_sale_delivery_planning/reserve_stock', type='json', auth='user', methods=['POST'])
    def reserve_stock(self, sale_order_ids=None, **kwargs):
        """
        Giữ hàng (action_assign) cho các picking liên quan đến đơn hàng đã chọn.
        Gọi action_assign cho tất cả picking chưa done/cancel — kể cả picking đã
        'assigned' nhưng chưa reserve đủ số lượng (partial).
        """
        try:
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

            # Giữ hàng cho tất cả picking chưa done/cancel
            # Không loại trừ 'assigned' vì picking có thể ở state assigned
            # nhưng vẫn chưa reserve đủ số lượng yêu cầu
            pickings_to_reserve = linked_pickings.filtered(
                lambda p: p.picking_type_code in ['outgoing', 'internal']
                          and p.state not in ['done', 'cancel']
            )

            if not pickings_to_reserve:
                return {'success': True, 'reserved_count': 0, 'message': 'Tất cả phiếu đã hoàn thành hoặc đã hủy'}

            reserved_count = 0
            for picking in pickings_to_reserve:
                try:
                    picking.with_context(skip_unreserve_wizard=True).action_assign()
                    reserved_count += 1
                except Exception as e_pick:
                    _logger.warning("Could not reserve picking %s: %s", picking.name, e_pick)

            return {
                'success': True,
                'reserved_count': reserved_count,
                'message': f'Đã giữ hàng cho {reserved_count} phiếu',
            }
        except Exception as e:
            _logger.error("Error reserving stock: %s", str(e), exc_info=True)
            return {'success': False, 'message': f'Lỗi khi giữ hàng: {str(e)}'}