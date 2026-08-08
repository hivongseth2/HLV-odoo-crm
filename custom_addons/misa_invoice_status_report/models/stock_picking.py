import logging

from markupsafe import Markup

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MISA_INVOICE_STATE_LABELS = {
    'not_checked': 'Chưa kiểm tra',
    'missing': 'Chưa có đề nghị xuất HĐ',
    'requested': 'Đã đề nghị, chờ HĐ',
    'invoiced': 'Đã xuất hóa đơn',
}

# Giới hạn số phiếu xử lý mỗi lần chạy cron, tránh gọi MISA API quá nhiều cùng lúc.
MISA_INVOICE_SCAN_BATCH_SIZE = 50


class StockPickingMisaInvoiceStatus(models.Model):
    _inherit = 'stock.picking'

    misa_invoice_state = fields.Selection(
        [
            ('not_checked', 'Chưa kiểm tra'),
            ('missing', 'Chưa có đề nghị xuất HĐ'),
            ('requested', 'Đã đề nghị, chờ HĐ'),
            ('invoiced', 'Đã xuất hóa đơn'),
        ],
        string='Tình trạng xuất HĐ MISA',
        default='not_checked',
        copy=False,
        index=True,
    )
    misa_invoice_last_checked = fields.Datetime(string='MISA kiểm tra lúc', copy=False)
    misa_invoice_request_refid = fields.Char(string='MISA Request RefID', copy=False)
    misa_invoice_no = fields.Char(string='Số hóa đơn MISA', copy=False)
    misa_invoice_date = fields.Date(string='Ngày hóa đơn MISA', copy=False)
    misa_invoice_amount = fields.Float(string='Tiền hóa đơn MISA', copy=False)
    misa_invoice_sale_order_id = fields.Many2one(
        'sale.order', string='Đơn bán liên quan',
        compute='_compute_misa_invoice_sale_order_id', store=True,
    )
    misa_invoice_exception = fields.Boolean(string='Ngoại lệ (chấp nhận chờ xuất HĐ)', copy=False)
    misa_invoice_exception_reason = fields.Text(string='Lý do ngoại lệ', copy=False)
    misa_invoice_exception_by_id = fields.Many2one('res.users', string='Người đánh dấu', copy=False)
    misa_invoice_exception_date = fields.Datetime(string='Ngày đánh dấu', copy=False)

    @api.depends('move_ids_without_package.sale_line_id.order_id', 'origin')
    def _compute_misa_invoice_sale_order_id(self):
        SaleOrder = self.env['sale.order']
        for picking in self:
            order = picking.move_ids_without_package.mapped('sale_line_id.order_id')[:1]
            if not order and picking.origin:
                order = SaleOrder.search([('name', '=', picking.origin)], limit=1)
            picking.misa_invoice_sale_order_id = order.id if order else False

    def action_check_misa_invoice_status(self):
        """Gọi MISA kiểm tra tình trạng xuất hóa đơn cho các phiếu đang chọn.
        Dùng chung cho nút thủ công (form/list) và cron quét định kỳ."""
        misa_utils = self.env['misa.api.utils']
        for picking in self:
            if picking.picking_type_code != 'outgoing':
                continue
            try:
                status = misa_utils.get_invoice_status_for_refno(picking.name)
            except Exception as e:
                _logger.exception(
                    "❌ [MISA INVOICE STATUS] Lỗi kiểm tra phiếu %s: %s", picking.name, e
                )
                picking.message_post(
                    body=Markup("<b>Kiểm tra hóa đơn MISA thất bại:</b><br/>%s") % str(e)
                )
                continue

            vals = {
                'misa_invoice_state': status['state'],
                'misa_invoice_last_checked': fields.Datetime.now(),
                'misa_invoice_request_refid': status.get('request_refid') or False,
                'misa_invoice_no': status.get('invoice_no') or False,
                'misa_invoice_amount': status.get('invoice_amount') or 0.0,
            }
            invoice_date = status.get('invoice_date')
            if invoice_date:
                try:
                    vals['misa_invoice_date'] = fields.Date.to_date(invoice_date)
                except Exception:
                    _logger.warning("Không parse được ngày hóa đơn MISA: %s", invoice_date)

            old_state = picking.misa_invoice_state
            picking.write(vals)

            if old_state != status['state']:
                picking.message_post(
                    body=Markup("<b>Tình trạng xuất hóa đơn MISA:</b> %s → %s") % (
                        MISA_INVOICE_STATE_LABELS.get(old_state, old_state),
                        MISA_INVOICE_STATE_LABELS.get(status['state'], status['state']),
                    )
                )
        return True

    def action_mark_misa_invoice_exception(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.exception.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }

    def action_unmark_misa_invoice_exception(self):
        self.write({
            'misa_invoice_exception': False,
            'misa_invoice_exception_reason': False,
            'misa_invoice_exception_by_id': False,
            'misa_invoice_exception_date': False,
        })
        self.message_post(body=Markup("Đã bỏ đánh dấu ngoại lệ xuất hóa đơn MISA."))
        return True

    def _cron_scan_misa_invoice_status(self):
        pickings = self.search([
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('misa_invoice_state', '!=', 'invoiced'),
            ('misa_invoice_exception', '=', False),
        ], order='misa_invoice_last_checked asc nulls first', limit=MISA_INVOICE_SCAN_BATCH_SIZE)

        for picking in pickings:
            try:
                picking.action_check_misa_invoice_status()
            except Exception:
                _logger.exception(
                    "❌ [MISA INVOICE STATUS CRON] Lỗi xử lý phiếu %s", picking.name
                )
