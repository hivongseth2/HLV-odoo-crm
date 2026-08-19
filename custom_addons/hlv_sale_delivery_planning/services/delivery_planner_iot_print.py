"""Hàng chờ in phiếu lấy hàng theo kho (hlv.iot.print.queue) — dùng cho nút "In" trên trang
/sale_plan, để sale tự gửi yêu cầu in đơn của mình mà không cần chọn máy in tay.

Đã thử phương án gọi thẳng report._render_qweb_pdf() kèm ghi device_ids từ /sale_plan (public
page, ngoài web client) — xác nhận KHÔNG kích hoạt in vật lý qua IoT Box, chỉ tải PDF về (cơ chế
in-qua-IoT của Enterprise nằm ở tầng JS action-dispatch của web client, không phải side-effect
Python của _render_qweb_pdf). Vì vậy sale chỉ ĐƯA YÊU CẦU vào hàng chờ theo kho; người ở kho mở
"Điều phối Giao hàng > Hàng chờ in (IoT)" trong backend và bấm "In ngay" (models/iot_print_queue.py
action_print_now — trả về report action để web client dispatch đúng cơ chế đã xác nhận hoạt động)
để thực sự in ra máy. Hàng chờ là bản ghi bền (persistent), không bị mất khi không ai bấm ngay.
"""
import base64
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

REPORT_NAME_SEARCH = 'Hoạt động lấy hàng TSN'

PICKING_STATE_LABEL = {
    'draft': 'Nháp',
    'waiting': 'Chờ bước trước',
    'confirmed': 'Chờ hàng (chưa giữ được)',
    'assigned': 'Đã giữ hàng, sẵn sàng lấy',
    'done': 'Hoàn thành',
    'cancel': 'Đã hủy',
}


class DeliveryPlannerServiceIotPrint(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _get_all_linked_pickings_for_sale_order(self, sale_order):
        """Toàn bộ phiếu kho (outgoing/internal, chưa done/cancel) liên quan đến đơn — kể cả
        không phải loại PICK. Dùng để chẩn đoán khi _get_pick_pickings_for_sale_order() trả về
        rỗng (xem enqueue_iot_print_for_sale_order), giúp sale biết ĐANG có phiếu gì, trạng thái
        nào, thay vì chỉ báo chung chung "không có gì để in"."""
        picking_obj = self.env['stock.picking']
        linked = sale_order.picking_ids
        linked |= picking_obj.search([
            ('sale_id', '=', sale_order.id),
            ('picking_type_code', 'in', ['outgoing', 'internal']),
            ('state', 'not in', ['done', 'cancel']),
        ])
        linked |= picking_obj.search([
            ('origin', '=', sale_order.name),
            ('picking_type_code', 'in', ['outgoing', 'internal']),
            ('state', 'not in', ['done', 'cancel']),
        ])
        linked |= picking_obj.search([
            ('move_ids.sale_line_id.order_id', '=', sale_order.id),
            ('picking_type_code', 'in', ['outgoing', 'internal']),
            ('state', 'not in', ['done', 'cancel']),
        ])
        return linked.filtered(
            lambda p: p.picking_type_code in ['outgoing', 'internal'] and p.state not in ['done', 'cancel']
        )

    def _get_pick_pickings_for_sale_order(self, sale_order):
        """Cùng logic lọc phiếu PICK như print_picking_slips (controllers/main.py) nhưng scope cho
        1 đơn — chưa hoàn thành/hủy, không phải phiếu trả hàng, đúng loại PICK."""
        linked = self._get_all_linked_pickings_for_sale_order(sale_order)
        return linked.filtered(
            lambda p: not p.return_id and 'PICK' in (p.picking_type_id.sequence_code or '').upper()
        ).sorted(key=lambda p: (p.scheduled_date or p.create_date, p.id))

    def _no_pick_picking_message(self, sale_order):
        """Xây thông báo lỗi CHI TIẾT khi không tìm được phiếu PICK nào để in — liệt kê đúng
        những phiếu ĐANG có (nếu có) kèm loại + trạng thái, thay vì báo chung chung."""
        all_linked = self._get_all_linked_pickings_for_sale_order(sale_order)
        if not all_linked:
            return 'Đơn này chưa có phiếu kho nào (chưa xác nhận hoặc chưa tạo phiếu xuất kho).'
        details = []
        for p in all_linked:
            if p.return_id:
                details.append('%s (phiếu trả hàng — bỏ qua)' % p.name)
            else:
                details.append('%s — loại "%s", trạng thái "%s"' % (
                    p.name,
                    p.picking_type_id.name or p.picking_type_id.code or '?',
                    PICKING_STATE_LABEL.get(p.state, p.state),
                ))
        return (
            'Đơn này không có phiếu LẤY HÀNG (PICK) nào để in — có thể kho của đơn không dùng '
            'bước lấy hàng riêng (giao thẳng 1 bước), hoặc phiếu chưa ở đúng trạng thái. '
            'Phiếu hiện có: ' + '; '.join(details)
        )

    def _render_preview_pdf(self, report, pickings):
        """Render PDF xem trước (không đánh dấu đã in — xem models/ir_actions_report.py) cho sale
        xem "có gì giao nấy" trước khi phiếu được kho in thật. Render riêng từng phiếu rồi merge
        (đảm bảo ngắt trang cứng giữa các phiếu), cùng cách main.py:print_picking_slips đang làm."""
        from odoo.tools.pdf import merge_pdf
        pdf_parts = []
        for picking in pickings:
            pdf_bytes, _ = report.with_context(hlv_skip_print_status_marking=True)._render_qweb_pdf(
                report.report_name, res_ids=[picking.id]
            )
            pdf_parts.append(pdf_bytes)
        return merge_pdf(pdf_parts)

    def enqueue_iot_print_for_sale_order(self, sale_order_id):
        """RPC chính cho nút "In" trên /sale_plan (card + drawer). Kiểm tra tồn kho trước: nếu
        TOÀN BỘ phiếu đều chưa giữ được chút hàng nào (state chưa lên 'assigned') thì CHẶN, không
        tạo hàng chờ. Nếu có ít nhất 1 phần hàng (kể cả partial — "có gì giao nấy"): render 1 PDF
        xem trước cho sale (không đánh dấu đã in), rồi mới gom phiếu PICK theo kho, tạo/refresh
        hàng chờ (pending) mỗi kho, báo bus realtime cho backend tự in — xem docstring module."""
        sale_order = self.env['sale.order'].sudo().browse(int(sale_order_id)).exists()
        if not sale_order:
            return {'success': False, 'message': 'Không tìm thấy đơn hàng'}

        pickings = self._get_pick_pickings_for_sale_order(sale_order)
        if not pickings:
            return {'success': False, 'message': self._no_pick_picking_message(sale_order)}

        if not any(p.state == 'assigned' for p in pickings):
            return {
                'success': False,
                'no_stock': True,
                'message': 'Đơn này chưa giữ được hàng cho bất kỳ sản phẩm nào (chưa có hàng), '
                            'chưa thể in phiếu lấy hàng.',
            }

        report = self.env['ir.actions.report'].sudo().search([
            ('name', 'ilike', REPORT_NAME_SEARCH),
        ], limit=1)
        if not report:
            return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

        preview_url = False
        try:
            pdf_content = self._render_preview_pdf(report, pickings)
            attachment = self.env['ir.attachment'].sudo().create({
                'name': 'Xem_truoc_Phieu_Lay_Hang_%s.pdf' % sale_order.name,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content).decode('utf-8'),
                'res_model': 'sale.order',
                'res_id': sale_order.id,
                'mimetype': 'application/pdf',
            })
            preview_url = '/web/content/%d?download=false' % attachment.id
        except Exception:
            # Preview chỉ là tiện ích thêm — lỗi render preview không được chặn việc gửi hàng chờ.
            _logger.exception('Failed to render preview PDF for sale order %s', sale_order_id)

        by_warehouse = {}
        for picking in pickings:
            wh = picking.picking_type_id.warehouse_id
            by_warehouse.setdefault(wh, self.env['stock.picking'])
            by_warehouse[wh] |= picking

        Queue = self.env['hlv.iot.print.queue'].sudo()
        warehouse_names = []
        missing_device_warehouses = []
        touched_warehouse_ids = []
        for wh, wh_pickings in by_warehouse.items():
            if not wh:
                missing_device_warehouses.append('Không rõ kho')
                continue
            if not wh.x_iot_printer_device_id:
                missing_device_warehouses.append(wh.name)
            existing = Queue.search([
                ('sale_order_id', '=', sale_order.id),
                ('warehouse_id', '=', wh.id),
                ('state', '=', 'pending'),
            ], limit=1)
            if existing:
                existing.write({
                    'picking_ids': [(6, 0, wh_pickings.ids)],
                    'requested_by_id': self.env.uid,
                    'requested_at': fields.Datetime.now(),
                })
            else:
                Queue.create({
                    'sale_order_id': sale_order.id,
                    'warehouse_id': wh.id,
                    'picking_ids': [(6, 0, wh_pickings.ids)],
                })
            warehouse_names.append(wh.name)
            touched_warehouse_ids.append(wh.id)

        if not warehouse_names:
            return {'success': False, 'message': 'Không xác định được kho của phiếu lấy hàng'}

        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel', 'iot_print_queue_changed',
                {'warehouse_ids': touched_warehouse_ids, 'sale_order_id': sale_order.id},
            )
        except Exception:
            _logger.debug('Failed to send iot_print_queue_changed notification', exc_info=True)

        message = 'Đã gửi yêu cầu in cho kho %s. Kho sẽ in phiếu trong ít phút.' % ', '.join(warehouse_names)
        if missing_device_warehouses:
            message += ' CẢNH BÁO: kho %s chưa gán máy in IoT (vào Kho hàng > cấu hình).' % ', '.join(missing_device_warehouses)

        return {
            'success': True,
            'message': message,
            'picking_count': len(pickings),
            'iot_ready': not missing_device_warehouses,
            'preview_url': preview_url,
            'partial_stock': any(p.state != 'assigned' for p in pickings),
        }
