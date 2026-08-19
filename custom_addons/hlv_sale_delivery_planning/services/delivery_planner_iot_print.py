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
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class DeliveryPlannerServiceIotPrint(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _get_pick_pickings_for_sale_order(self, sale_order):
        """Cùng logic lọc phiếu PICK như print_picking_slips (controllers/main.py) nhưng scope cho
        1 đơn — chưa hoàn thành/hủy, không phải phiếu trả hàng, đúng loại PICK."""
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
            lambda p: p.picking_type_code in ['outgoing', 'internal']
                      and p.state not in ['done', 'cancel']
                      and not p.return_id
                      and 'PICK' in (p.picking_type_id.sequence_code or '').upper()
        ).sorted(key=lambda p: (p.scheduled_date or p.create_date, p.id))

    def enqueue_iot_print_for_sale_order(self, sale_order_id):
        """RPC chính cho nút "In" trên /sale_plan (card + drawer). Gom phiếu PICK của đơn theo
        kho, tạo/refresh 1 bản ghi hàng chờ (pending) mỗi kho, báo bus realtime cho backend, KHÔNG
        tự render/in gì ở đây (xem docstring module)."""
        sale_order = self.env['sale.order'].sudo().browse(int(sale_order_id)).exists()
        if not sale_order:
            return {'success': False, 'message': 'Không tìm thấy đơn hàng'}

        pickings = self._get_pick_pickings_for_sale_order(sale_order)
        if not pickings:
            return {'success': False, 'message': 'Đơn này không có phiếu lấy hàng nào cần in'}

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
        }
