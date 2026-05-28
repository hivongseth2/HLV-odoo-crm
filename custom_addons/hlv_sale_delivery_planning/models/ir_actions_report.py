import logging
from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """
        Override để tự động đánh dấu x_printed khi in report "Hoạt động lấy hàng"
        từ BẤT KỲ giao diện nào (không chỉ từ delivery planner).
        """
        result = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

        if not res_ids:
            return result

        try:
            # Xác định report đang in
            report = self._get_report(report_ref)
            if not report:
                return result

            # Check bằng tên dịch UI (vi_VN) hoặc fallback tên kỹ thuật
            translated_name = (report.with_context(lang='vi_VN').name or '').lower()
            report_technical = (report.report_name or '')
            is_picking_report = (
                'hoạt động lấy hàng' in translated_name
                or (
                    report_technical.startswith('stock.report_picking')
                    and 'packages' not in report_technical
                )
            )

            # === "Biên bản" detection ===
            # Bất kỳ report có dấu hiệu "biên bản giao nhận / bàn giao / phiếu xuất / phiếu bàn giao"
            # hoặc các viết tắt phổ biến (BBGN, BBBG, PXBH) trong tên (vi/en hoặc technical name)
            # và in cho stock.picking → đánh dấu x_bien_ban_printed.
            tech_lower = report_technical.lower()
            bien_ban_keywords = (
                'biên bản', 'bien ban',
                'bbgn', 'bbbg', 'pxbh',
                'phiếu xuất', 'phieu xuat',
                'phiếu bàn', 'phieu ban',
                'phiếu giao nhận', 'phieu giao nhan',
                'bàn giao', 'ban giao',
            )
            is_bien_ban_report = any(
                kw in translated_name or kw in tech_lower
                for kw in bien_ban_keywords
            )
            if is_bien_ban_report and report.model == 'stock.picking':
                pickings_bb = self.env['stock.picking'].browse(res_ids).exists()
                pickings_bb = pickings_bb.filtered(lambda p: not p.x_bien_ban_printed)
                if pickings_bb:
                    pickings_bb.write({'x_bien_ban_printed': True})
                    _logger.info(
                        'Auto-marked %d pickings as bien_ban_printed (report: %s): %s',
                        len(pickings_bb), translated_name or report_technical,
                        ', '.join(pickings_bb.mapped('name')),
                    )

            if not is_picking_report:
                return result

            # Report này in cho stock.picking → đánh dấu x_printed
            if report.model == 'stock.picking':
                pickings = self.env['stock.picking'].browse(res_ids).exists()
                pick_pickings = pickings.filtered(
                    lambda p: 'PICK' in (p.picking_type_id.sequence_code or '').upper()
                              and not p.return_id
                              and not p.x_printed
                )
                if pick_pickings:
                    if any(not p.x_pick_print_start_at for p in pick_pickings):
                        pick_pickings.filtered(lambda p: not p.x_pick_print_start_at).write({
                            'x_pick_print_start_at': fields.Datetime.now(),
                            'x_pick_printed_by_id': self.env.uid,
                        })
                    pick_pickings.mark_picking_print_finished()
                    _logger.info(
                        'Auto-marked %d pick pickings as printed: %s',
                        len(pick_pickings),
                        ', '.join(pick_pickings.mapped('name')),
                    )

                    # Đánh dấu SO tương ứng
                    sale_orders = self.env['sale.order']
                    for pk in pick_pickings:
                        # Tìm SO qua move_ids.sale_line_id hoặc sale_id
                        so = pk.sale_id or pk.move_ids.sale_line_id.order_id
                        if so:
                            sale_orders |= so
                    if not sale_orders:
                        # Fallback: tìm qua origin
                        origins = [p.origin for p in pick_pickings if p.origin]
                        if origins:
                            sale_orders = self.env['sale.order'].search([
                                ('name', 'in', origins),
                            ])
                    sale_orders.filtered(lambda s: not s.x_picking_slip_printed).write({
                        'x_picking_slip_printed': True,
                    })
        except Exception:
            _logger.warning('Error auto-marking printed pickings', exc_info=True)

        return result
