# -*- coding: utf-8 -*-
import base64
import io
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

    @http.route('/hlv_sale_delivery_planning/export_excel', type='http', auth='user', methods=['GET'])
    def export_excel(self, **kwargs):
        """
        Xuất Excel tình trạng đơn hàng theo bộ lọc hiện tại.
        Không phân trang, không chi tiết sản phẩm — chỉ trạng thái đơn.
        """
        try:
            import xlsxwriter
        except ImportError:
            from odoo.tools.misc import xlsxwriter

        STATUS_LABELS = {
            'stock_status': {
                'ready': 'Đủ hàng xuất',
                'partial_ready': 'Có hàng 1 phần',
                'out_of_stock': 'Không có hàng',
            },
            'packing_status': {
                'fully_packed': 'Đã đóng gói đủ',
                'unpacked': 'Có hàng chưa đóng gói',
                'waiting_stock': 'Không có hàng đóng',
            },
            'delivery_status': {
                'full': 'Hoàn thành',
                'partial': 'Giao 1 phần',
                'pending': 'Chưa giao',
            },
            'real_delivery_status': {
                'full': 'Hoàn thành',
                'partial': 'Giao 1 phần',
                'pending': 'Chưa giao',
            },
        }

        try:
            result = request.env['hlv.delivery.planner.service'].get_dashboard_data(
                search_query=kwargs.get('search_query', ''),
                filter_warehouse_id=kwargs.get('filter_warehouse_id', 'all'),
                filter_delivery_status=kwargs.get('filter_delivery_status', 'all'),
                filter_stock_status=kwargs.get('filter_stock_status', 'all'),
                filter_packing_status=kwargs.get('filter_packing_status', 'all'),
                filter_date_from=kwargs.get('filter_date_from', ''),
                filter_date_to=kwargs.get('filter_date_to', ''),
                filter_po_date_from=kwargs.get('filter_po_date_from', ''),
                filter_po_date_to=kwargs.get('filter_po_date_to', ''),
                filter_po_status=kwargs.get('filter_po_status', 'all'),
                filter_saler_code=kwargs.get('filter_saler_code', ''),
                filter_htgh=kwargs.get('filter_htgh', ''),
                filter_delivery_type=kwargs.get('filter_delivery_type', 'all'),
                filter_tag_ids=kwargs.get('filter_tag_ids', ''),
                show_completed=bool(kwargs.get('show_completed', '')),
                limit=100000,
                offset=0,
            )

            orders = result.get('orders', [])

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            sheet = workbook.add_worksheet('Tình trạng đơn hàng')

            # Formats
            header_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#4472C4', 'font_color': '#FFFFFF',
                'border': 1, 'align': 'center', 'valign': 'vcenter',
                'font_size': 11, 'text_wrap': True,
            })
            cell_fmt = workbook.add_format({
                'border': 1, 'valign': 'vcenter', 'font_size': 10,
            })
            money_fmt = workbook.add_format({
                'border': 1, 'valign': 'vcenter', 'font_size': 10,
                'num_format': '#,##0',
            })
            date_fmt = workbook.add_format({
                'border': 1, 'valign': 'vcenter', 'font_size': 10,
                'num_format': 'dd/mm/yyyy',
            })

            headers = [
                ('STT', 5),
                ('Đơn hàng', 15),
                ('Khách hàng', 25),
                ('Kho', 15),
                ('Mã NV MISA', 12),
                ('Ngày đặt hàng', 14),
                ('Ngày hẹn giao', 14),
                ('Tổng tiền', 15),
                ('Tình trạng kho', 18),
                ('Đóng gói', 18),
                ('Tiến độ giao', 18),
                ('TT giao thực tế', 18),
                ('HTGH', 15),
                ('Loại vận chuyển', 15),
                ('Địa chỉ giao', 30),
                ('Đề xuất chuyển kho', 30),
                ('Tags', 20),
            ]

            for col, (name, width) in enumerate(headers):
                sheet.write(0, col, name, header_fmt)
                sheet.set_column(col, col, width)
            sheet.freeze_panes(1, 0)

            for row_idx, order in enumerate(orders, start=1):
                col = 0
                sheet.write(row_idx, col, row_idx, cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('name', ''), cell_fmt); col += 1
                partner = order.get('partner_id')
                sheet.write(row_idx, col, partner[1] if partner else '', cell_fmt); col += 1
                wh = order.get('warehouse_id')
                sheet.write(row_idx, col, wh[1] if wh else '', cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_misa_saler_code', ''), cell_fmt); col += 1

                # Dates
                date_order = order.get('date_order', '')
                if date_order:
                    sheet.write(row_idx, col, date_order[:10], date_fmt)
                else:
                    sheet.write(row_idx, col, '', cell_fmt)
                col += 1

                commit_date = order.get('commitment_date', '')
                if commit_date:
                    sheet.write(row_idx, col, commit_date[:10], date_fmt)
                else:
                    sheet.write(row_idx, col, '', cell_fmt)
                col += 1

                sheet.write(row_idx, col, order.get('amount_total', 0), money_fmt); col += 1

                # Status columns – translate
                stock_st = order.get('stock_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['stock_status'].get(stock_st, stock_st), cell_fmt); col += 1
                pack_st = order.get('packing_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['packing_status'].get(pack_st, pack_st), cell_fmt); col += 1
                del_st = order.get('delivery_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['delivery_status'].get(del_st, del_st), cell_fmt); col += 1
                real_del = order.get('real_delivery_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['real_delivery_status'].get(real_del, real_del), cell_fmt); col += 1

                sheet.write(row_idx, col, order.get('x_studio_htgh', ''), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_delivery_type', ''), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('misa_shipping_address', ''), cell_fmt); col += 1

                # Transfer suggestions
                suggestions = order.get('transfer_suggestions', [])
                if suggestions:
                    parts = []
                    for s in suggestions:
                        src_names = ', '.join(
                            f"{src['from_warehouse_name']}({src['suggested_qty']})"
                            for src in s.get('sources', [])
                        )
                        parts.append(f"{s['product_name']} thiếu {s['shortage']}: {src_names}")
                    sheet.write(row_idx, col, '; '.join(parts), cell_fmt)
                else:
                    sheet.write(row_idx, col, '', cell_fmt)
                col += 1

                # Tags
                tags = order.get('tag_ids', [])
                tag_names = ', '.join(t[1] for t in tags) if tags else ''
                sheet.write(row_idx, col, tag_names, cell_fmt)

            workbook.close()
            output.seek(0)
            xlsx_data = output.read()

            filename = 'Tinh_trang_don_hang.xlsx'
            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', len(xlsx_data)),
                ],
            )
        except Exception as e:
            _logger.error("Error exporting Excel: %s", str(e), exc_info=True)
            return request.make_response(
                f'Lỗi khi xuất Excel: {str(e)}',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
            )