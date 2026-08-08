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
MISA_INVOICE_CUTOFF_DEFAULT = '2026-05-01'
MISA_INVOICE_RECONCILE_GROUP = 'misa_invoice_status_report.group_misa_invoice_reconciliation'

# Sai số cho phép khi so tiền hóa đơn MISA với tiền thực xuất trên phiếu kho (làm tròn).
MISA_INVOICE_AMOUNT_TOLERANCE = 1.0

MISA_INVOICE_UNASSIGNED_SALER = 'Chưa gán mã sale'


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

    # 1 phiếu xuất kho có thể gộp nhiều đơn bán (MISA trả "order_code": "DH1, DH2"
    # cho cùng 1 refno), và 1 đơn bán có thể được xuất bởi nhiều phiếu (giao nhiều đợt)
    # => quan hệ nhiều-nhiều, không thể rút gọn về 1 đơn duy nhất.
    misa_invoice_sale_order_ids = fields.Many2many(
        'sale.order', string='Đơn bán liên quan',
        compute='_compute_misa_invoice_sale_order_ids', store=True,
    )
    # Lấy từ sale.order.x_studio_misa_saler_code (field Studio, đã có sẵn trên hệ thống).
    misa_invoice_saler_code = fields.Char(
        string='Mã sale MISA', compute='_compute_misa_invoice_saler_code', store=True, index=True,
    )
    # So tiền hóa đơn MISA với tiền thực xuất trên phiếu (field Studio x_studio_tng_tin_sau_thu).
    misa_invoice_amount_diff = fields.Float(
        string='Chênh lệch tiền (Odoo - MISA)', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )
    misa_invoice_amount_mismatch = fields.Boolean(
        string='Lệch tiền so với MISA', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )

    misa_invoice_exception = fields.Boolean(string='Ngoại lệ (chấp nhận chờ xuất HĐ)', copy=False)
    misa_invoice_exception_reason = fields.Text(string='Lý do ngoại lệ', copy=False)
    misa_invoice_exception_by_id = fields.Many2one('res.users', string='Người đánh dấu', copy=False)
    misa_invoice_exception_date = fields.Datetime(string='Ngày đánh dấu', copy=False)

    # Đơn Shopee dùng luồng hóa đơn meInvoice riêng (amis_callback) — loại khỏi đối soát MISA này.
    misa_invoice_is_shopee = fields.Boolean(
        string='Thuộc đơn Shopee', compute='_compute_misa_invoice_is_shopee', store=True,
    )

    @api.depends('move_ids_without_package.sale_line_id.order_id', 'origin')
    def _compute_misa_invoice_sale_order_ids(self):
        SaleOrder = self.env['sale.order']
        for picking in self:
            orders = picking.move_ids_without_package.mapped('sale_line_id.order_id')
            if not orders and picking.origin:
                names = [name.strip() for name in picking.origin.split(',') if name.strip()]
                if names:
                    orders = SaleOrder.search([('name', 'in', names)])
            picking.misa_invoice_sale_order_ids = orders

    @api.depends('misa_invoice_sale_order_ids.x_studio_misa_saler_code')
    def _compute_misa_invoice_saler_code(self):
        for picking in self:
            code = False
            for order in picking.misa_invoice_sale_order_ids:
                value = getattr(order, 'x_studio_misa_saler_code', False)
                if value:
                    code = value
                    break
            picking.misa_invoice_saler_code = code

    @api.depends('misa_invoice_sale_order_ids.shopee_order_ref')
    def _compute_misa_invoice_is_shopee(self):
        for picking in self:
            picking.misa_invoice_is_shopee = any(
                getattr(order, 'shopee_order_ref', False) for order in picking.misa_invoice_sale_order_ids
            )

    @api.depends('misa_invoice_state', 'misa_invoice_amount', 'x_studio_tng_tin_sau_thu')
    def _compute_misa_invoice_amount_mismatch(self):
        for picking in self:
            actual_amount = getattr(picking, 'x_studio_tng_tin_sau_thu', False) or 0.0
            if picking.misa_invoice_state == 'invoiced' and actual_amount:
                diff = actual_amount - (picking.misa_invoice_amount or 0.0)
                picking.misa_invoice_amount_diff = diff
                picking.misa_invoice_amount_mismatch = abs(diff) > MISA_INVOICE_AMOUNT_TOLERANCE
            else:
                picking.misa_invoice_amount_diff = 0.0
                picking.misa_invoice_amount_mismatch = False

    def action_check_misa_invoice_status(self):
        """Gọi MISA kiểm tra tình trạng xuất hóa đơn cho các phiếu đang chọn.
        Dùng chung cho nút thủ công (form/list), cron quét định kỳ, và vòng lặp
        hiện tiến trình trên dashboard. Trả về kết quả từng phiếu để hiển thị ngay
        (không bắt buộc caller nào phải dùng)."""
        misa_utils = self.env['misa.api.utils']
        results = []
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
                results.append({'id': picking.id, 'name': picking.name, 'error': str(e)})
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
            if picking.misa_invoice_amount_mismatch:
                picking.message_post(
                    body=Markup("<b>⚠️ Lệch tiền với MISA:</b> Odoo %.0f đ vs MISA %.0f đ (chênh %.0f đ)") % (
                        getattr(picking, 'x_studio_tng_tin_sau_thu', 0.0) or 0.0,
                        picking.misa_invoice_amount or 0.0,
                        picking.misa_invoice_amount_diff,
                    )
                )
            results.append({
                'id': picking.id,
                'name': picking.name,
                'state': picking.misa_invoice_state,
                'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            })
        return results

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

    def _misa_invoice_scan_domain(self, date_from=False, date_to=False):
        return self._misa_invoice_dashboard_base_domain(date_from, date_to) + [
            ('misa_invoice_state', '!=', 'invoiced'),
            ('misa_invoice_exception', '=', False),
        ]

    def _cron_scan_misa_invoice_status(self):
        pickings = self.search(
            self._misa_invoice_scan_domain(),
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

    @api.model
    def get_misa_invoice_scan_candidates(self, limit=MISA_INVOICE_SCAN_BATCH_SIZE, date_from=False, date_to=False):
        """Danh sách phiếu SẼ được quét (chưa gọi MISA) — dùng để dashboard chạy
        từng phiếu một và hiện tiến trình thực (thay vì 1 lệnh lớn chạy âm thầm).

        Khi có date_from/date_to (đang xem theo 1 khoảng ngày xuất kho cụ thể), JS sẽ
        lặp gọi hàm này nhiều lần (mỗi lần 1 batch) cho tới khi quét hết `total` — nhờ
        vậy vẫn chia nhỏ từng lệnh gọi MISA nhưng làm trọn được cả khoảng đang cần gấp,
        thay vì luôn chỉ dừng ở 1 batch như khi không chọn khoảng ngày nào."""
        domain = self._misa_invoice_scan_domain(date_from, date_to)
        Picking = self.sudo()
        pickings = Picking.search(domain, order='misa_invoice_last_checked asc nulls first', limit=limit)
        return {
            'candidates': [{'id': picking.id, 'name': picking.name} for picking in pickings],
            'total': Picking.search_count(domain),
        }

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

    def _misa_invoice_dashboard_base_domain(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Domain nền cho mọi truy vấn đối soát: phiếu xuất kho đã done, từ mốc
        đối soát trở đi. date_from/date_to lọc theo NGÀY XUẤT KHO (date_done, có thể
        là 1 ngày cụ thể nếu from=to, hoặc 1 khoảng) — chỉ dùng để THU HẸP thêm, không
        bao giờ vượt ra ngoài mốc đối soát. invoice_date_from/to lọc theo NGÀY XUẤT
        HÓA ĐƠN (misa_invoice_date) — độc lập với ngày xuất kho."""
        lower = self._get_misa_invoice_cutoff_date()
        if date_from:
            try:
                parsed_from = fields.Date.from_string(date_from)
            except Exception:
                parsed_from = False
            if parsed_from and parsed_from > lower:
                lower = parsed_from

        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', fields.Datetime.to_string(datetime.combine(lower, dt_time.min))),
            # Đơn Shopee dùng luồng meInvoice riêng; phiếu trả hàng không cần xuất HĐ mới.
            ('misa_invoice_is_shopee', '=', False),
            ('origin', 'not ilike', 'trả hàng'),
        ]
        if date_to:
            try:
                parsed_to = fields.Date.from_string(date_to)
            except Exception:
                parsed_to = False
            if parsed_to:
                domain.append(
                    ('date_done', '<=', fields.Datetime.to_string(datetime.combine(parsed_to, dt_time.max)))
                )
        if invoice_date_from:
            domain.append(('misa_invoice_date', '>=', invoice_date_from))
        if invoice_date_to:
            domain.append(('misa_invoice_date', '<=', invoice_date_to))
        return domain

    def _misa_invoice_state_breakdown(self, domain):
        Picking = self.sudo()
        return {
            'missing': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'missing'), ('misa_invoice_exception', '=', False)]
            ),
            'requested': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'requested'), ('misa_invoice_exception', '=', False)]
            ),
            'invoiced': Picking.search_count(domain + [('misa_invoice_state', '=', 'invoiced')]),
            'exception': Picking.search_count(domain + [('misa_invoice_exception', '=', True)]),
        }

    @api.model
    def get_misa_invoice_dashboard_data(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Số liệu tổng quan cho dashboard OWL (KPI tiles + bảng theo kho/sale/khách hàng)."""
        Picking = self.sudo()
        base_domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )

        counts = {}
        for state in MISA_INVOICE_STATE_LABELS:
            counts[state] = Picking.search_count(
                base_domain + [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
            )
        exception_count = Picking.search_count(base_domain + [('misa_invoice_exception', '=', True)])
        mismatch_count = Picking.search_count(base_domain + [('misa_invoice_amount_mismatch', '=', True)])
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
            row = self._misa_invoice_state_breakdown(wh_domain)
            row.update({'warehouse_id': wh.id, 'warehouse_name': wh.name, 'total': wh_total})
            by_warehouse.append(row)
        by_warehouse.sort(key=lambda row: row['missing'], reverse=True)

        by_saler = []
        saler_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_saler_code'])
        for grp in saler_groups:
            saler_domain = base_domain + [('misa_invoice_saler_code', '=', grp['misa_invoice_saler_code'])]
            saler_pickings = Picking.search(saler_domain)
            row = self._misa_invoice_state_breakdown(saler_domain)
            row.update({
                'saler_code': grp['misa_invoice_saler_code'] or MISA_INVOICE_UNASSIGNED_SALER,
                'total': grp['misa_invoice_saler_code_count'],
                'pending': row['missing'] + row['requested'],
                'actual_amount_total': sum(saler_pickings.mapped('x_studio_tng_tin_sau_thu')),
                'invoice_amount_total': sum(
                    saler_pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced').mapped(
                        'misa_invoice_amount'
                    )
                ),
            })
            by_saler.append(row)
        by_saler.sort(key=lambda row: row['pending'], reverse=True)

        by_customer = []
        customer_groups = Picking.read_group(base_domain, ['id'], ['partner_id'])
        for grp in customer_groups:
            partner = grp['partner_id']  # False, hoặc (id, display_name)
            partner_id = partner[0] if partner else False
            customer_domain = base_domain + [('partner_id', '=', partner_id)]
            customer_pickings = Picking.search(customer_domain)
            row = self._misa_invoice_state_breakdown(customer_domain)
            row.update({
                'partner_id': partner_id,
                'partner_name': partner[1] if partner else 'Chưa có khách hàng',
                'total': grp['partner_id_count'],
                'pending': row['missing'] + row['requested'],
                'actual_amount_total': sum(customer_pickings.mapped('x_studio_tng_tin_sau_thu')),
                'invoice_amount_total': sum(
                    customer_pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced').mapped(
                        'misa_invoice_amount'
                    )
                ),
            })
            by_customer.append(row)
        by_customer.sort(key=lambda row: row['pending'], reverse=True)

        cron = self.env.ref('misa_invoice_status_report.ir_cron_misa_invoice_status_scan', raise_if_not_found=False)
        last_scan_at = False
        if cron and cron.sudo().lastcall:
            last_scan_at = fields.Datetime.to_string(cron.sudo().lastcall)

        return {
            'counts': counts,
            'exception_count': exception_count,
            'mismatch_count': mismatch_count,
            'total': total,
            'invoiced_amount': invoiced_amount,
            'by_warehouse': by_warehouse,
            'by_saler': by_saler,
            'by_customer': by_customer,
            'last_scan_at': last_scan_at,
            'cutoff_date': fields.Date.to_string(self._get_misa_invoice_cutoff_date()),
            'can_configure': self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP),
        }

    def _misa_invoice_picking_to_row(self, picking, today):
        done_date = picking.date_done.date() if picking.date_done else False
        return {
            'id': picking.id,
            'name': picking.name,
            'partner_name': picking.partner_id.display_name or '',
            'sale_order_name': ', '.join(picking.misa_invoice_sale_order_ids.mapped('name')),
            'saler_code': picking.misa_invoice_saler_code or '',
            'date_done': fields.Date.to_string(done_date) if done_date else '',
            'days_pending': (today - done_date).days if done_date else 0,
            'state': picking.misa_invoice_state,
            'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            'actual_amount': picking.x_studio_tng_tin_sau_thu or 0.0,
            'invoice_amount': picking.misa_invoice_amount or 0.0,
            'outstanding_amount': 0.0 if picking.misa_invoice_state == 'invoiced' else (
                picking.x_studio_tng_tin_sau_thu or 0.0
            ),
        }

    @api.model
    def get_misa_invoice_urgent_list(
        self, limit=10, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Top phiếu cần hối gấp nhất: chưa xuất HĐ, không ngoại lệ, xuất kho lâu nhất."""
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        ) + [
            ('misa_invoice_state', 'in', ('missing', 'requested')),
            ('misa_invoice_exception', '=', False),
        ]
        pickings = self.sudo().search(domain, order='date_done asc', limit=limit)
        today = fields.Date.context_today(self)
        return [self._misa_invoice_picking_to_row(picking, today) for picking in pickings]

    @api.model
    def get_misa_invoice_picking_list(
        self, limit=20, offset=0, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách phiếu 'phẳng' (mọi trạng thái, không group) — tab 'Đơn hàng' trên
        dashboard. Có phân trang server-side vì có thể lên tới hàng nghìn dòng."""
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        total = Picking.search_count(domain)
        pickings = Picking.search(domain, order='date_done desc', limit=limit, offset=offset)
        today = fields.Date.context_today(self)
        return {
            'rows': [self._misa_invoice_picking_to_row(picking, today) for picking in pickings],
            'total': total,
        }

    @api.model
    def get_misa_invoice_picking_lines(self, picking_id):
        """Chi tiết sản phẩm/số lượng/giá trị xuất kho của 1 phiếu, dùng cho drawer chi tiết.

        Giá trị xuất kho = qty * đơn giá trên dòng đơn bán tương ứng (prorate theo
        qty đã giao trên dòng đó). Riêng combo/kit (BOM phantom): các dòng move con do
        Odoo tự nổ ra khi giao hàng đều trỏ về CÙNG 1 sale.order.line của sản phẩm combo,
        và giá chỉ nằm ở đó (giá sản phẩm con = 0) — nên gán toàn bộ price_subtotal của
        dòng combo cho 1 dòng đại diện, còn các sản phẩm con hiển thị giá trị = 0.
        """
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return []

        moves = picking.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        groups = {}
        order = []
        for move in moves:
            key = move.sale_line_id.id
            if key not in groups:
                groups[key] = self.env['stock.move']
                order.append(key)
            groups[key] |= move

        Bom = self.env['mrp.bom'].sudo()
        lines = []
        for key in order:
            group_moves = groups[key]
            sale_line = group_moves[0].sale_line_id
            is_kit = bool(sale_line and Bom.search_count([
                ('product_tmpl_id', '=', sale_line.product_id.product_tmpl_id.id),
                ('type', '=', 'phantom'),
                ('active', '=', True),
            ]))

            if sale_line and is_kit:
                lines.append({
                    'product_name': sale_line.product_id.display_name,
                    'qty': sale_line.product_uom_qty,
                    'uom_name': sale_line.product_uom.name,
                    'value': sale_line.price_subtotal,
                    'is_combo': True,
                })
                for move in group_moves:
                    lines.append({
                        'product_name': move.product_id.display_name,
                        'qty': move.quantity,
                        'uom_name': move.product_uom.name,
                        'value': 0.0,
                        'is_component': True,
                    })
                continue

            for move in group_moves:
                value = 0.0
                if sale_line and sale_line.product_uom_qty:
                    value = move.quantity * (sale_line.price_subtotal / sale_line.product_uom_qty)
                lines.append({
                    'product_name': move.product_id.display_name,
                    'qty': move.quantity,
                    'uom_name': move.product_uom.name,
                    'value': value,
                })
        return lines

    @api.model
    def get_misa_invoice_report_action(
        self, state=False, exception=None, saler_code=False, mismatch=False, partner_id=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Trả action list đã có sẵn (action_misa_invoice_status_report), lọc theo tile/dòng được bấm.
        exception=None: không ép domain, để search view tự quyết định (dùng cho "Xem tất cả").
        exception=True/False: ép domain đúng theo tile."""
        action = self.env['ir.actions.actions']._for_xml_id(
            'misa_invoice_status_report.action_misa_invoice_status_report'
        )
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if state:
            domain.append(('misa_invoice_state', '=', state))
            if exception is None:
                exception = False
        if exception is not None:
            domain.append(('misa_invoice_exception', '=', bool(exception)))
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        if mismatch:
            domain.append(('misa_invoice_amount_mismatch', '=', True))
        action['domain'] = domain
        return action
