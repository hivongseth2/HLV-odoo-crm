"""In phiếu lấy hàng (PICK) theo TỪNG PHIẾU, quy trình 2 bước rõ ràng cho sale trên /sale_plan:
  1) preview_pick_slip(picking_id): chỉ render PDF xem trước (không tạo hàng chờ, không đánh dấu
     đã in) — sale xem "có gì giao nấy" trước khi quyết định gửi in.
  2) confirm_print_pick_slip(picking_id): sale đã xem preview và bấm "Xác nhận in" — lúc này mới
     thật sự tạo/refresh hàng chờ theo kho (hlv.iot.print.queue) và báo bus cho backend tự in.
Tuyệt đối không gộp 2 bước làm 1 (preview xong tự động gửi in luôn) — dễ khiến sale bấm nhầm gửi
in cho kho trong khi chỉ định xem thử.

Đã thử phương án gọi thẳng report._render_qweb_pdf() kèm ghi device_ids từ /sale_plan (public
page, ngoài web client) — xác nhận KHÔNG kích hoạt in vật lý qua IoT Box, chỉ tải PDF về (cơ chế
in-qua-IoT của Enterprise nằm ở tầng JS action-dispatch của web client, không phải side-effect
Python của _render_qweb_pdf). Vì vậy bước (2) chỉ ĐƯA YÊU CẦU vào hàng chờ theo kho; người ở kho mở
"Điều phối Giao hàng > Hàng chờ in (IoT)" trong backend (tự động xử lý, xem
delivery_planner_iot_print_mixin.js) — action_print_now/auto_claim_and_print trong
models/iot_print_queue.py trả về report action để web client dispatch đúng cơ chế đã xác nhận
hoạt động, mới thực sự in ra máy. Hàng chờ là bản ghi bền (persistent), không mất khi chưa ai xử lý.
"""
import base64
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

REPORT_NAME_SEARCH = 'Hoạt động lấy hàng TSN'


class DeliveryPlannerServiceIotPrint(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _get_sale_order_for_picking(self, picking):
        return picking.sale_id or picking.move_ids.sale_line_id.order_id[:1]

    def _is_pick_slip_locked(self):
        """Cờ tạm khóa tính năng in phiếu lấy hàng qua sale plan trước khi chính thức vận
        hành (VD: đã lên code nhưng chờ 2-3 ngày mới cho sale dùng thật) — bật/tắt ở
        Settings > HLV Delivery Planner, không cần đụng tới hàng chờ/queue."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.lock_pick_slip_requests'
        ) in ('1', 'True', 'true')

    def _get_pick_report(self, warehouse=None):
        """Admin có thể cấu hình report riêng theo từng kho (stock.warehouse.x_iot_report_id) —
        ưu tiên report đó nếu có, không thì dùng mẫu mặc định (tìm theo tên)."""
        if warehouse and warehouse.x_iot_report_id:
            return warehouse.x_iot_report_id
        return self.env['ir.actions.report'].sudo().search([
            ('name', 'ilike', REPORT_NAME_SEARCH),
        ], limit=1)

    def _render_preview_pdf(self, report, picking):
        """Render PDF xem trước (không đánh dấu đã in — xem models/ir_actions_report.py) cho sale
        xem "có gì giao nấy" trước khi phiếu được kho in thật."""
        pdf_bytes, _ = report.with_context(hlv_skip_print_status_marking=True)._render_qweb_pdf(
            report.report_name, res_ids=[picking.id]
        )
        return pdf_bytes

    def preview_pick_slip(self, picking_id):
        """Bước 1: chỉ xem trước, KHÔNG tạo hàng chờ / KHÔNG đánh dấu đã in."""
        picking = self.env['stock.picking'].sudo().browse(int(picking_id)).exists()
        if not picking:
            return {'success': False, 'message': 'Không tìm thấy phiếu lấy hàng'}
        if self._is_pick_slip_locked():
            return {
                'success': False,
                'locked': True,
                'message': 'Tính năng xem/in phiếu lấy hàng đang tạm khóa, chưa vận hành. Vui lòng thử lại sau.',
            }
        sale_order = self._get_sale_order_for_picking(picking)
        if sale_order and not self._user_can_print_sale_order(sale_order):
            return {
                'success': False,
                'forbidden': True,
                'message': 'Tài khoản của bạn không khớp mã sale của đơn này, không được phép xem/in phiếu này.',
            }
        if 'PICK' not in (picking.picking_type_id.sequence_code or '').upper():
            return {'success': False, 'message': 'Phiếu này không phải phiếu lấy hàng (PICK)'}
        if picking.state != 'assigned':
            return {
                'success': False,
                'no_stock': True,
                'message': 'Phiếu này chưa giữ được hàng (chưa có hàng để lấy), chưa thể xem trước / in.',
            }

        report = self._get_pick_report(picking.picking_type_id.warehouse_id)
        if not report:
            return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

        try:
            pdf_content = self._render_preview_pdf(report, picking)
            attachment = self.env['ir.attachment'].sudo().create({
                'name': 'Xem_truoc_%s.pdf' % picking.name.replace('/', '_'),
                'type': 'binary',
                'datas': base64.b64encode(pdf_content).decode('utf-8'),
                'res_model': 'stock.picking',
                'res_id': picking.id,
                'mimetype': 'application/pdf',
            })
        except Exception as e:
            _logger.exception('Failed to render preview PDF for picking %s', picking_id)
            return {'success': False, 'message': 'Lỗi khi tạo bản xem trước: %s' % e}

        return {
            'success': True,
            'preview_url': '/web/content/%d?download=false' % attachment.id,
            'message': 'Xem trước phiếu %s' % picking.name,
        }

    def confirm_print_pick_slip(self, picking_id):
        """Bước 2: sale đã xem preview, bấm "Xác nhận in" — tạo/refresh hàng chờ theo kho, báo
        bus realtime cho backend tự in (xem docstring module)."""
        picking = self.env['stock.picking'].sudo().browse(int(picking_id)).exists()
        if not picking:
            return {'success': False, 'message': 'Không tìm thấy phiếu lấy hàng'}
        if self._is_pick_slip_locked():
            return {
                'success': False,
                'locked': True,
                'message': 'Tính năng xem/in phiếu lấy hàng đang tạm khóa, chưa vận hành. Vui lòng thử lại sau.',
            }

        sale_order = self._get_sale_order_for_picking(picking)
        if not sale_order:
            return {'success': False, 'message': 'Không xác định được đơn hàng của phiếu này'}
        if not self._user_can_print_sale_order(sale_order):
            return {
                'success': False,
                'forbidden': True,
                'message': 'Tài khoản của bạn không khớp mã sale của đơn này, không được phép gửi in phiếu này.',
            }

        if picking.state != 'assigned':
            return {
                'success': False,
                'no_stock': True,
                'message': 'Phiếu này chưa giữ được hàng (chưa có hàng để lấy), chưa thể gửi in.',
            }

        wh = picking.picking_type_id.warehouse_id
        if not wh:
            return {'success': False, 'message': 'Không xác định được kho của phiếu này'}

        Queue = self.env['hlv.iot.print.queue'].sudo()
        existing = Queue.search([
            ('sale_order_id', '=', sale_order.id),
            ('warehouse_id', '=', wh.id),
            ('state', '=', 'pending'),
        ], limit=1)
        if existing:
            # Đơn này ĐÃ có chỗ trong hàng chờ của kho rồi (chỉ thêm phiếu vào request cũ) —
            # không tính là "thêm 1 đơn mới", nên không cần kiểm tra giới hạn hàng chờ.
            existing_pickings = existing.picking_ids | picking
            existing.write({
                'picking_ids': [(6, 0, existing_pickings.ids)],
                'requested_by_id': self.env.uid,
                'requested_at': fields.Datetime.now(),
            })
        else:
            # Kho có thể cấu hình số đơn TỐI ĐA đang xử lý cùng lúc (x_iot_queue_limit, 0 =
            # không giới hạn) — chỉ áp dụng khi tạo MỘT ĐƠN MỚI trong hàng chờ, để tránh kho bị
            # quá tải nếu nhiều sale gửi in cùng lúc.
            limit = wh.x_iot_queue_limit or 0
            if limit > 0:
                active_count = Queue.count_active_for_warehouse(wh.id)
                if active_count >= limit:
                    return {
                        'success': False,
                        'queue_full': True,
                        'message': 'Kho "%s" đang xử lý %d/%d đơn (đã đạt giới hạn) — vui lòng '
                                    'thử gửi in lại sau khi kho xử lý xong 1 vài đơn.' % (
                                        wh.name, active_count, limit,
                                    ),
                    }
            Queue.create({
                'sale_order_id': sale_order.id,
                'warehouse_id': wh.id,
                'picking_ids': [(6, 0, [picking.id])],
            })

        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel', 'iot_print_queue_changed',
                {'warehouse_ids': [wh.id], 'sale_order_id': sale_order.id},
            )
        except Exception:
            _logger.debug('Failed to send iot_print_queue_changed notification', exc_info=True)

        message = 'Đã gửi yêu cầu in phiếu %s cho kho %s. Kho sẽ in trong ít phút.' % (picking.name, wh.name)
        iot_ready = bool(wh.x_iot_printer_device_id)
        if not iot_ready:
            message += ' CẢNH BÁO: kho "%s" chưa gán máy in IoT (vào Kho hàng > cấu hình).' % wh.name

        return {'success': True, 'message': message, 'iot_ready': iot_ready}

    def get_print_log_for_picking(self, picking_id):
        """Nhật ký in gắn thẳng vào 1 phiếu (tab "Nhật ký" trên dialog chi tiết phiếu /sale_plan)
        — có kiểm quyền giống preview/confirm, không cho xem nhật ký đơn không phải của mình."""
        picking = self.env['stock.picking'].sudo().browse(int(picking_id)).exists()
        if not picking:
            return {'success': False, 'message': 'Không tìm thấy phiếu lấy hàng'}
        sale_order = self._get_sale_order_for_picking(picking)
        if sale_order and not self._user_can_print_sale_order(sale_order):
            return {
                'success': False,
                'forbidden': True,
                'message': 'Tài khoản của bạn không khớp mã sale của đơn này, không được xem nhật ký.',
            }
        logs = self.env['hlv.iot.print.queue'].sudo().get_log_for_picking(picking_id)
        return {'success': True, 'logs': logs}
