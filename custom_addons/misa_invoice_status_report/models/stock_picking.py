import logging
from datetime import datetime, time as dt_time

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

MISA_INVOICE_STATE_LABELS = {
    'not_checked': 'Chưa kiểm tra',
    'missing': 'Chưa có đề nghị xuất HĐ',
    'requested': 'Đã đề nghị, chờ HĐ',
    'invoiced': 'Đã xuất hóa đơn',
}

# Giới hạn số phiếu xử lý mỗi lần chạy cron, tránh gọi MISA API quá nhiều cùng lúc.
MISA_INVOICE_SCAN_BATCH_SIZE = 50

# Mốc ngày mặc định bắt đầu đối soát nếu chưa cấu hình (có thể đổi trên dashboard).
MISA_INVOICE_CUTOFF_PARAM = 'misa_invoice_status_report.cutoff_date'
MISA_INVOICE_CUTOFF_DEFAULT = '2026-01-01'
MISA_INVOICE_RECONCILE_GROUP = 'misa_invoice_status_report.group_misa_invoice_reconciliation'


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
        pickings = self.search(
            self._misa_invoice_dashboard_base_domain() + [
                ('misa_invoice_state', '!=', 'invoiced'),
                ('misa_invoice_exception', '=', False),
            ],
            order='misa_invoice_last_checked asc nulls first',
            limit=MISA_INVOICE_SCAN_BATCH_SIZE,
        )

        for picking in pickings:
            try:
                picking.action_check_misa_invoice_status()
            except Exception:
                _logger.exception(
                    "❌ [MISA INVOICE STATUS CRON] Lỗi xử lý phiếu %s", picking.name
                )

    # ==================== Mốc ngày đối soát (cấu hình được) ====================

    def _get_misa_invoice_cutoff_date(self):
        raw = (self.env['ir.config_parameter'].sudo().get_param(MISA_INVOICE_CUTOFF_PARAM) or '').strip()
        for value in (raw, MISA_INVOICE_CUTOFF_DEFAULT):
            if not value:
                continue
            try:
                return fields.Date.from_string(value)
            except Exception:
                continue
        return fields.Date.from_string(MISA_INVOICE_CUTOFF_DEFAULT)

    @api.model
    def set_misa_invoice_cutoff_date(self, date_str):
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Bạn không có quyền thay đổi mốc đối soát MISA."))
        try:
            parsed = fields.Date.from_string(date_str)
        except Exception:
            parsed = False
        if not parsed:
            raise UserError(_("Ngày không hợp lệ: %s") % date_str)
        self.env['ir.config_parameter'].sudo().set_param(
            MISA_INVOICE_CUTOFF_PARAM, fields.Date.to_string(parsed)
        )
        return self.get_misa_invoice_dashboard_data()

    # ==================== Dữ liệu cho Dashboard OWL ====================

    def _misa_invoice_dashboard_base_domain(self):
        cutoff = self._get_misa_invoice_cutoff_date()
        cutoff_dt = fields.Datetime.to_string(datetime.combine(cutoff, dt_time.min))
        return [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', cutoff_dt),
        ]

    @api.model
    def get_misa_invoice_dashboard_data(self):
        """Số liệu tổng quan cho dashboard OWL (KPI tiles + bảng theo kho)."""
        Picking = self.sudo()
        base_domain = self._misa_invoice_dashboard_base_domain()

        counts = {}
        for state in MISA_INVOICE_STATE_LABELS:
            counts[state] = Picking.search_count(
                base_domain + [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
            )
        exception_count = Picking.search_count(base_domain + [('misa_invoice_exception', '=', True)])
        total = sum(counts.values()) + exception_count

        invoiced_pickings = Picking.search(base_domain + [('misa_invoice_state', '=', 'invoiced')])
        invoiced_amount = sum(invoiced_pickings.mapped('misa_invoice_amount'))

        by_warehouse = []
        warehouses = self.env['stock.warehouse'].sudo().search([])
        for wh in warehouses:
            wh_domain = base_domain + [('picking_type_id.warehouse_id', '=', wh.id)]
            wh_total = Picking.search_count(wh_domain)
            if not wh_total:
                continue
            by_warehouse.append({
                'warehouse_id': wh.id,
                'warehouse_name': wh.name,
                'missing': Picking.search_count(
                    wh_domain + [('misa_invoice_state', '=', 'missing'), ('misa_invoice_exception', '=', False)]
                ),
                'requested': Picking.search_count(
                    wh_domain + [('misa_invoice_state', '=', 'requested'), ('misa_invoice_exception', '=', False)]
                ),
                'invoiced': Picking.search_count(wh_domain + [('misa_invoice_state', '=', 'invoiced')]),
                'exception': Picking.search_count(wh_domain + [('misa_invoice_exception', '=', True)]),
                'total': wh_total,
            })
        by_warehouse.sort(key=lambda row: row['missing'], reverse=True)

        cron = self.env.ref('misa_invoice_status_report.ir_cron_misa_invoice_status_scan', raise_if_not_found=False)
        last_scan_at = False
        if cron and cron.sudo().lastcall:
            last_scan_at = fields.Datetime.to_string(cron.sudo().lastcall)

        return {
            'counts': counts,
            'exception_count': exception_count,
            'total': total,
            'invoiced_amount': invoiced_amount,
            'by_warehouse': by_warehouse,
            'last_scan_at': last_scan_at,
            'cutoff_date': fields.Date.to_string(self._get_misa_invoice_cutoff_date()),
            'can_configure': self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP),
        }

    @api.model
    def get_misa_invoice_urgent_list(self, limit=10):
        """Top phiếu cần hối gấp nhất: chưa xuất HĐ, không ngoại lệ, xuất kho lâu nhất."""
        domain = self._misa_invoice_dashboard_base_domain() + [
            ('misa_invoice_state', 'in', ('missing', 'requested')),
            ('misa_invoice_exception', '=', False),
        ]
        pickings = self.sudo().search(domain, order='date_done asc', limit=limit)
        today = fields.Date.context_today(self)
        rows = []
        for picking in pickings:
            done_date = picking.date_done.date() if picking.date_done else False
            rows.append({
                'id': picking.id,
                'name': picking.name,
                'partner_name': picking.partner_id.display_name or '',
                'sale_order_name': picking.misa_invoice_sale_order_id.name or '',
                'date_done': fields.Date.to_string(done_date) if done_date else '',
                'days_pending': (today - done_date).days if done_date else 0,
                'state': picking.misa_invoice_state,
                'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            })
        return rows

    @api.model
    def get_misa_invoice_report_action(self, state=False, exception=None):
        """Trả action list đã có sẵn (action_misa_invoice_status_report), lọc theo tile được bấm.
        exception=None: không ép domain, để search view tự quyết định (dùng cho "Xem tất cả").
        exception=True/False: ép domain đúng theo tile."""
        action = self.env['ir.actions.actions']._for_xml_id(
            'misa_invoice_status_report.action_misa_invoice_status_report'
        )
        domain = self._misa_invoice_dashboard_base_domain()
        if state:
            domain.append(('misa_invoice_state', '=', state))
            if exception is None:
                exception = False
        if exception is not None:
            domain.append(('misa_invoice_exception', '=', bool(exception)))
        action['domain'] = domain
        return action

    @api.model
    def action_misa_invoice_dashboard_scan_now(self):
        """Bấm nút 'Kiểm tra MISA ngay' trên dashboard: chạy đúng batch của cron rồi trả số liệu mới."""
        self._cron_scan_misa_invoice_status()
        return self.get_misa_invoice_dashboard_data()
