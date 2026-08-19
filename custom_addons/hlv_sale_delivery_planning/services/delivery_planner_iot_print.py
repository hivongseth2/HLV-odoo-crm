"""In phiếu lấy hàng cho MỘT đơn bán, tự động route ra đúng máy in IoT của kho
(stock.warehouse.x_iot_printer_device_id) — dùng cho nút "In" trên trang /sale_plan, để sale tự in
phiếu đơn của mình mà không cần chọn máy in tay mỗi lần.

CHÚ Ý QUAN TRỌNG: cơ chế in vật lý qua IoT Box (route theo field device_ids trên ir.actions.report,
xem Settings > Technical > Actions > Reports > tab "Thiết bị IoT") là tính năng của module
Enterprise `iot` — codebase này không có source của module đó nên KHÔNG xác nhận được việc in vật
lý được kích hoạt ở layer JS (web client action service) hay như 1 side-effect Python bên trong
_render_qweb_pdf(). Hàm dưới đây set đúng device_ids theo kho TRƯỚC khi gọi _render_qweb_pdf():
nếu Odoo IoT tự in như side-effect Python thì sẽ in thẳng ra máy ngay; nếu cơ chế thực sự nằm ở
JS thì endpoint vẫn trả PDF bình thường (không regression so với trước), cần bấm thử trên máy thật
để xác nhận có in ra giấy hay không.
"""
import base64
import logging

from odoo import models

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

    def _set_report_iot_device(self, report, device):
        """Ghi device_ids của report action đúng bằng 1 máy in (hoặc rỗng nếu kho chưa gán máy).
        Chỉ ghi khi khác giá trị hiện tại để tránh write thừa (report action dùng CHUNG cho mọi
        kho, nên phải set lại đúng trước MỖI lần render nếu kho khác nhau)."""
        target_ids = {device.id} if device else set()
        if set(report.device_ids.ids) != target_ids:
            report.sudo().write({'device_ids': [(6, 0, list(target_ids))]})

    def print_pick_slip_for_sale_order(self, sale_order_id):
        """RPC chính cho nút "In" trên /sale_plan. Trả về:
        {success, message, url, picking_count, iot_ready} — 'iot_ready' = True nếu MỌI phiếu đều
        tìm được máy in IoT cấu hình cho kho (không đảm bảo Box đã thực sự in được, chỉ đảm bảo đã
        set đúng device_ids trước khi render — xem docstring module)."""
        sale_order = self.env['sale.order'].sudo().browse(int(sale_order_id)).exists()
        if not sale_order:
            return {'success': False, 'message': 'Không tìm thấy đơn hàng'}

        pickings = self._get_pick_pickings_for_sale_order(sale_order)
        if not pickings:
            return {'success': False, 'message': 'Đơn này không có phiếu lấy hàng nào cần in'}

        report = self.env['ir.actions.report'].sudo().search([
            ('name', 'ilike', 'Hoạt động lấy hàng TSN'),
        ], limit=1)
        if not report:
            return {'success': False, 'message': 'Không tìm thấy report template cho phiếu lấy hàng'}

        from odoo.tools.pdf import merge_pdf
        pdf_parts = []
        missing_device_warehouses = set()
        try:
            for picking in pickings:
                warehouse = picking.picking_type_id.warehouse_id
                device = warehouse.x_iot_printer_device_id if warehouse else False
                if not device:
                    missing_device_warehouses.add(warehouse.name if warehouse else 'Không rõ kho')
                self._set_report_iot_device(report, device)
                pdf_bytes, _ = report._render_qweb_pdf(report.report_name, res_ids=[picking.id])
                pdf_parts.append(pdf_bytes)
            pdf_content = merge_pdf(pdf_parts)
        except Exception as e:
            _logger.error("Error printing pick slip for sale order %s: %s", sale_order_id, e, exc_info=True)
            return {'success': False, 'message': f'Lỗi khi tạo PDF: {e}'}

        if not sale_order.x_picking_slip_printed:
            sale_order.write({'x_picking_slip_printed': True})

        attachment = self.env['ir.attachment'].sudo().create({
            'name': f'Phieu_Lay_Hang_{sale_order.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content).decode('utf-8'),
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'mimetype': 'application/pdf',
        })

        message = f'Đã gửi in {len(pickings)} phiếu cho đơn {sale_order.name}'
        if missing_device_warehouses:
            message += (
                ' — CẢNH BÁO: kho %s chưa gán máy in IoT (vào Kho hàng > cấu hình), '
                'phiếu này chỉ ra PDF, chưa chắc in thẳng ra máy.'
                % ', '.join(sorted(missing_device_warehouses))
            )

        return {
            'success': True,
            'message': message,
            'url': f'/web/content/{attachment.id}?download=true',
            'picking_count': len(pickings),
            'iot_ready': not missing_device_warehouses,
        }
