from odoo import api, fields, models
from odoo.exceptions import UserError


class MisaInvoiceAiReport(models.Model):
    """Báo cáo đối soát hằng ngày do Claude viết trên máy worker (skill doi-soat-misa, chạy 19h).

    Vì sao lưu thành bản ghi: cả trăm đơn lệch mỗi ngày, người không soát tay nổi. Máy soát lý do
    từng đơn (misa.invoice.gap.review), Claude gom thành việc cho từng người và tự soát lại theo
    đơn những đơn tự sửa được; bản ghi giữ lại báo cáo từng ngày để so hôm trước / hôm nay, và giữ
    các đề xuất gắn mã đề nghị chờ người xác nhận — AI không tự gắn."""
    _name = 'misa.invoice.ai.report'
    _description = 'Báo cáo đối soát MISA (AI)'
    _inherit = ['mail.thread']
    _order = 'report_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    report_date = fields.Date(string='Ngày báo cáo', required=True, index=True, default=fields.Date.context_today)
    body = fields.Html(string='Báo cáo', readonly=True, sanitize=True)
    order_count = fields.Integer(string='Số đơn lệch', readonly=True)
    total_gap = fields.Float(string='Tổng lệch (đ)', readonly=True)
    refreshed_log = fields.Text(
        string='Đã soát lại theo đơn', readonly=True,
        help='Các đơn AI đã bấm soát lại theo đơn trước khi viết báo cáo, lệch trước → sau.',
    )
    worker = fields.Char(string='Máy viết', readonly=True)
    suggestion_ids = fields.One2many('misa.invoice.ai.suggestion', 'report_id', string='Đề xuất gắn mã đề nghị')
    suggestion_pending_count = fields.Integer(string='Đề xuất chờ duyệt', compute='_compute_suggestion_pending_count')

    @api.depends('report_date')
    def _compute_name(self):
        for report in self:
            report.name = 'Báo cáo đối soát %s' % (report.report_date.strftime('%d/%m/%Y') if report.report_date else '')

    @api.depends('suggestion_ids.state')
    def _compute_suggestion_pending_count(self):
        for report in self:
            report.suggestion_pending_count = len(report.suggestion_ids.filtered(lambda s: s.state == 'proposed'))

    @api.model
    def submit_from_ai(self, values):
        """Tạo báo cáo từ worker. values = {report_date, body (HTML), order_count, total_gap,
        refreshed_log, worker, suggestions: [{picking, refno, reason, amount}]}. Phiếu đề xuất tra
        theo tên — tên không có trong Odoo thì báo lỗi luôn, để AI sửa lại chứ không lưu đề xuất
        treo. Trả id báo cáo."""
        Picking = self.env['stock.picking'].sudo()
        suggestion_vals = []
        for suggestion in values.get('suggestions') or []:
            picking = Picking.search([('name', '=', (suggestion.get('picking') or '').strip())], limit=1)
            refno = (suggestion.get('refno') or '').strip()
            if not picking or not refno:
                raise UserError("Đề xuất không hợp lệ (phiếu '%s', đề nghị '%s')." % (suggestion.get('picking'), refno))
            suggestion_vals.append((0, 0, {
                'picking_id': picking.id, 'refno': refno,
                'reason': suggestion.get('reason') or '', 'amount': suggestion.get('amount') or 0.0,
            }))
        report = self.create({
            'report_date': values.get('report_date') or fields.Date.context_today(self),
            'body': values.get('body') or '',
            'order_count': values.get('order_count') or 0,
            'total_gap': values.get('total_gap') or 0.0,
            'refreshed_log': values.get('refreshed_log') or '',
            'worker': values.get('worker') or '',
            'suggestion_ids': suggestion_vals,
        })
        return report.id


class MisaInvoiceAiSuggestion(models.Model):
    """Một đề xuất gắn mã đề nghị MISA cho phiếu xuất kho, AI viết, NGƯỜI xác nhận mới gắn —
    gắn sai là tiền HĐ của đơn khác chạy sang phiếu này."""
    _name = 'misa.invoice.ai.suggestion'
    _description = 'Đề xuất gắn mã đề nghị (AI)'
    _order = 'report_id desc, id'

    report_id = fields.Many2one('misa.invoice.ai.report', required=True, ondelete='cascade', index=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True, ondelete='cascade')
    order_names = fields.Char(string='Đơn hàng', compute='_compute_order_names', store=True)
    refno = fields.Char(string='Mã đề nghị MISA', required=True)
    amount = fields.Float(string='Tiền liên quan (đ)')
    reason = fields.Text(string='Vì sao')
    state = fields.Selection(
        [('proposed', 'Chờ duyệt'), ('applied', 'Đã gắn'), ('rejected', 'Bỏ qua')],
        string='Trạng thái', default='proposed', required=True,
    )
    decided_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    decided_at = fields.Datetime(string='Duyệt lúc', readonly=True)
    result = fields.Char(string='Kết quả', readonly=True)

    @api.depends('picking_id.misa_invoice_sale_order_ids')
    def _compute_order_names(self):
        for suggestion in self:
            suggestion.order_names = ', '.join(suggestion.picking_id.misa_invoice_sale_order_ids.mapped('name'))

    def action_apply(self):
        """Gắn mã đề nghị như nút "Gắn mã đề nghị" (kiểm tra lại MISA ngay), rồi soát lại theo đơn
        để tiền HĐ và dòng ghi nhầm mã đơn chuyển theo."""
        for suggestion in self.filtered(lambda s: s.state == 'proposed'):
            picking = suggestion.picking_id
            check = picking.action_apply_manual_invoice_link(
                suggestion.refno, source_note='đề xuất của %s' % suggestion.report_id.name,
            )
            picking.misa_invoice_sale_order_ids._misa_invoice_refresh_order_truth()
            suggestion.write({
                'state': 'applied', 'decided_by_id': self.env.user.id, 'decided_at': fields.Datetime.now(),
                'result': (check or {}).get('state_label') or picking.misa_invoice_state,
            })
        return True

    def action_reject(self):
        self.filtered(lambda s: s.state == 'proposed').write({
            'state': 'rejected', 'decided_by_id': self.env.user.id, 'decided_at': fields.Datetime.now(),
        })
        return True
