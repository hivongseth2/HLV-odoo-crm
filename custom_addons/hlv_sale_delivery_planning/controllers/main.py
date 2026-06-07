# -*- coding: utf-8 -*-
import base64
import io
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DeliveryPlannerController(http.Controller):

    @http.route('/hlv_sale_delivery_planning/print_picking_slips', type='json', auth='user', methods=['POST'])
    def print_picking_slips(self, sale_order_ids=None, report_id=None, packer_user_id=None, **kwargs):
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

            if report_id is None:
                report_id = kwargs.get('report_id')
            if report_id is None and isinstance(request.jsonrequest, dict):
                report_id = (request.jsonrequest.get('params') or {}).get('report_id')
            if isinstance(report_id, (list, tuple, set)):
                report_id = next(iter(report_id), None)
            if report_id:
                report_id = int(report_id)

            if packer_user_id is None:
                packer_user_id = kwargs.get('packer_user_id')
            if packer_user_id is None and isinstance(request.jsonrequest, dict):
                packer_user_id = (request.jsonrequest.get('params') or {}).get('packer_user_id')
            if isinstance(packer_user_id, (list, tuple, set)):
                packer_user_id = next(iter(packer_user_id), None)
            packer_user_id = int(packer_user_id) if packer_user_id else False

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
                lambda p: p.picking_type_code in ['outgoing', 'internal']
                          and p.state not in ['done', 'cancel']
                          and not p.return_id   # Loại bỏ phiếu trả hàng
                          and 'PICK' in (p.picking_type_id.sequence_code or '').upper()  # Chỉ in phiếu lấy hàng (pick)
            ).sorted(key=lambda p: (p.scheduled_date or p.create_date, p.id))

            if not all_pickings:
                return {'success': False, 'message': 'Không có phiếu lấy hàng nào cần in (tất cả đã hoàn thành hoặc đã hủy)'}

            if not packer_user_id:
                return {'success': False, 'message': 'Vui lòng chọn người đóng trước khi in phiếu lấy hàng'}
            packer = request.env['res.users'].sudo().browse(packer_user_id).exists()
            if not packer:
                return {'success': False, 'message': 'Không tìm thấy người đóng đã chọn'}

            if report_id:
                report = request.env['ir.actions.report'].sudo().browse(report_id).exists()
                if not report:
                    return {'success': False, 'message': 'Không tìm thấy report template đã chọn'}
                if report.report_type != 'qweb-pdf':
                    return {
                        'success': False,
                        'message': 'Mẫu in đã chọn không hỗ trợ in hàng loạt bằng PDF',
                    }
            else:
                # Fetch report by name "Hoạt động lấy hàng"
                report = request.env['ir.actions.report'].sudo().search([
                    ('name', 'ilike', 'Hoạt động lấy hàng TSN'),
                ], limit=1)

                if not report:
                    return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

            picking_ids = list(all_pickings.ids)
            try:
                all_pickings.mark_picking_print_started(packer_user_id=packer_user_id)
                # Render từng phiếu riêng lẻ → mỗi phiếu là 1 PDF độc lập
                # rồi merge lại bằng Odoo built-in → đảm bảo page break cứng giữa từng phiếu
                from odoo.tools.pdf import merge_pdf
                pdf_parts = []
                for pid in picking_ids:
                    pdf_bytes, _ = report._render_qweb_pdf(report.report_name, res_ids=[pid])
                    pdf_parts.append(pdf_bytes)
                pdf_content = merge_pdf(pdf_parts)
                all_pickings.mark_picking_print_finished()
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

            # Đánh dấu các đơn hàng đã in phiếu lấy hàng
            sale_orders.filtered(lambda s: not s.x_picking_slip_printed).write({
                'x_picking_slip_printed': True,
            })
            # Đánh dấu từng phiếu đã được in (để phát hiện phiếu mới chưa in sau này)
            all_pickings.filtered(lambda p: not p.x_printed).mark_picking_print_finished()

            return {
                'success': True,
                'url': f'/web/content/{attachment.id}?download=true',
                'picking_count': len(all_pickings),
                'packer_user_id': packer.id,
                'packer_name': getattr(packer, 'x_packer_name', None) or packer.name,
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

            # Chỉ gọi action_assign khi picking CÒN HÀNG THỰC TẾ để reserve thêm.
            #
            # Vấn đề: Nếu quant.reserved_quantity không đồng bộ với move_line.quantity
            # (inconsistent data), action_assign sẽ thấy "free quant" ảo và tăng
            # ml.quantity mỗi lần gọi mà không bao giờ update quant.reserved → vòng lặp vô hạn.
            #
            # Fix: So sánh tổng move_line.quantity với tổng quant.quantity tại location nguồn.
            # Nếu move_lines đã claim đủ hàng vật lý có trong kho → không cần assign thêm.
            Quant = request.env['stock.quant']

            def _needs_reservation(p):
                if p.picking_type_code not in ('outgoing', 'internal'):
                    return False
                if p.state in ('done', 'cancel'):
                    return False
                if p.return_id:
                    return False
                for mv in p.move_ids:
                    if mv.state in ('done', 'cancel'):
                        continue
                    if mv.product_uom_qty <= mv.quantity:
                        continue  # move này đã đủ reservation
                    # Tổng qty move_lines đang claim cho move này
                    existing_ml_qty = sum(
                        ml.quantity for ml in mv.move_line_ids
                        if ml.state not in ('cancel', 'done')
                    )
                    # Tổng hàng vật lý tại location nguồn (bất kể reserved hay không)
                    total_quant_qty = sum(
                        q.quantity for q in Quant.search([
                            ('product_id', '=', mv.product_id.id),
                            ('location_id', 'child_of', mv.location_id.id),
                        ])
                    )
                    # Chỉ cần assign nếu còn hàng vật lý chưa bị ml nào claim
                    if existing_ml_qty < total_quant_qty:
                        return True
                return False

            pickings_to_reserve = linked_pickings.filtered(_needs_reservation)

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
                'waiting_stock': 'Không có hàng đóng',
                'unpacked': 'Có hàng chưa đóng gói',
                'partial_packed': 'Đã đóng 1 phần',
                'has_unprinted': 'Có phiếu chưa in',
                'printed_waiting': 'Đã in, chờ đóng gói',
                'fully_packed': 'Đã đóng gói đủ',
                'packed_waiting_ship': 'Đã gói, chờ nhận giao',
                'shipping': 'Đang giao',
                'delivered': 'Đã giao đủ',
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
            
            # Lọc theo selected_ids nếu có (Export các card được check)
            selected_ids_str = kwargs.get('selected_ids', '')
            if selected_ids_str:
                selected_ids = [int(x.strip()) for x in selected_ids_str.split(',') if x.strip().isdigit()]
                if selected_ids:
                    orders = [o for o in orders if o.get('id') in selected_ids]

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
                ('Ngày MISA', 14),
                ('Tổng tiền', 15),
                ('Tình trạng kho', 18),
                ('Đóng gói', 18),
                ('Đã in phiếu', 12),
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
                
                misa_date = order.get('misa_order_date', '')
                if misa_date:
                    sheet.write(row_idx, col, misa_date[:10], date_fmt)
                else:
                    sheet.write(row_idx, col, '', cell_fmt)
                col += 1

                sheet.write(row_idx, col, order.get('amount_total', 0), money_fmt); col += 1

                # Status columns – translate
                stock_st = order.get('stock_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['stock_status'].get(stock_st, stock_st), cell_fmt); col += 1
                pack_st = order.get('packing_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['packing_status'].get(pack_st, pack_st), cell_fmt); col += 1
                
                # Cột Đã in phiếu
                is_printed = 'Đã in' if order.get('picking_slip_printed') else 'Chưa in'
                sheet.write(row_idx, col, is_printed, cell_fmt); col += 1
                
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

    @http.route('/hlv_sale_delivery_planning/export_transfer_excel', type='http', auth='user', methods=['POST', 'GET'])
    def export_transfer_excel(self, **kwargs):
        """
        Xuất Excel báo cáo chuyển kho từ dữ liệu modal luân chuyển.
        Nhận JSON param: sale_order_ids (comma-separated or JSON array).
        """
        try:
            import xlsxwriter
        except ImportError:
            from odoo.tools.misc import xlsxwriter

        try:
            import json as _json
            raw_ids = kwargs.get('sale_order_ids', '')
            if isinstance(raw_ids, str):
                try:
                    ids_list = _json.loads(raw_ids)
                except Exception:
                    ids_list = [int(x.strip()) for x in raw_ids.split(',') if x.strip().isdigit()]
            else:
                ids_list = list(raw_ids)

            data = request.env['hlv.delivery.planner.service'].prepare_transfer_modal_data(ids_list)
            warehouses = data.get('warehouses', [])

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})

            hdr_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#2F75B6', 'font_color': '#FFFFFF',
                'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 11,
            })
            wh_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#D6E4F7', 'border': 1,
                'align': 'left', 'valign': 'vcenter', 'font_size': 11,
            })
            cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10})
            num_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': '#,##0.##'})
            red_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'font_color': '#C00000', 'bold': True, 'num_format': '#,##0.##'})
            grn_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'font_color': '#375623', 'bold': True, 'num_format': '#,##0.##'})
            ord_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 9, 'font_color': '#595959', 'text_wrap': True})

            sheet = workbook.add_worksheet('Báo cáo chuyển kho')
            sheet.set_row(0, 22)

            headers = [
                ('Kho nguồn', 16),
                ('Mã hàng', 18),
                ('Tên sản phẩm', 36),
                ('Từ các đơn', 28),
                ('Tổng yêu cầu', 14),
                ('Tồn kho tại kho', 16),
                ('SL đề xuất', 14),
                ('Liên hệ', 28),
                ('Vị trí đích', 34),
                ('Loại hoạt động', 24),
            ]

            for col, (h, w) in enumerate(headers):
                sheet.write(0, col, h, hdr_fmt)
                sheet.set_column(col, col, w)
            sheet.freeze_panes(1, 0)

            row = 1
            for wh in warehouses:
                wh_label = f"{wh.get('warehouse_code', '')} — {wh.get('warehouse_name', '')}"
                sheet.merge_range(row, 0, row, len(headers) - 1, wh_label, wh_fmt)
                row += 1

                for prod in wh.get('products', []):
                    avail = prod.get('available_at_source', 0)
                    total = prod.get('total_qty', 0)
                    order_names = ', '.join(prod.get('order_names', []))

                    sheet.write(row, 0, wh.get('warehouse_name', ''), cell_fmt)
                    sheet.write(row, 1, prod.get('product_code', ''), cell_fmt)
                    sheet.write(row, 2, prod.get('product_name', ''), cell_fmt)
                    sheet.write(row, 3, order_names, ord_fmt)
                    sheet.write(row, 4, total, red_fmt)
                    sheet.write(row, 5, avail, grn_fmt if avail >= total else num_fmt)
                    sheet.write(row, 6, total, num_fmt)
                    sheet.write(row, 7, wh.get('partner_name', ''), cell_fmt)
                    sheet.write(row, 8, wh.get('transit_location_name', ''), cell_fmt)
                    sheet.write(row, 9, wh.get('picking_type_name', ''), cell_fmt)
                    row += 1

            workbook.close()
            output.seek(0)
            xlsx_data = output.read()

            filename = 'Bao_cao_chuyen_kho.xlsx'
            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', str(len(xlsx_data))),
                ],
            )
        except Exception as e:
            _logger.error("Error exporting transfer Excel: %s", str(e), exc_info=True)
            return request.make_response(
                f'Lỗi: {str(e)}',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
            )