import base64
import io

import xlsxwriter

from odoo import tools, _
from odoo import api, fields, models
from odoo.exceptions import UserError

MONTHLY_MEASURES = [
    'qty_delivered:sum', 'qty_returned:sum', 'qty_net:sum',
    'amount_gross:sum', 'amount_returned:sum', 'amount_net:sum',
]


class HlvCustomerRevenueReport(models.Model):
    _name = 'hlv.customer.revenue.report'
    _description = 'Báo cáo doanh thu theo khách hàng'
    _auto = False
    _rec_name = 'sale_order_id'
    _order = 'date_done desc'

    # ==================== Relations ====================
    move_id = fields.Many2one('stock.move', string='Dịch chuyển kho', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', readonly=True)
    picking_type_id = fields.Many2one('stock.picking.type', string='Loại thao tác', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Dòng đơn hàng', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn hàng', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty nội bộ', readonly=True,
        help='Công ty vận hành Odoo xuất phiếu (đa công ty). Khác với "Khách hàng" - '
             'là đối tác/khách hàng trên đơn bán.',
    )
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho', readonly=True)
    user_id = fields.Many2one('res.users', string='Nhân viên bán hàng', readonly=True)
    order_partner_id = fields.Many2one('res.partner', string='Người đặt hàng', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    product_categ_id = fields.Many2one('product.category', string='Nhóm sản phẩm', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Đơn vị tính', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', readonly=True)

    # ==================== Dates ====================
    order_date = fields.Datetime(string='Ngày đặt hàng', readonly=True)
    date_done = fields.Datetime(string='Ngày xuất kho', readonly=True)

    # ==================== Quantities ====================
    qty_delivered = fields.Float(string='SL xuất kho', readonly=True)
    qty_returned = fields.Float(string='SL trả hàng', readonly=True)
    qty_net = fields.Float(string='SL thực xuất (ròng)', readonly=True)

    # ==================== Unit prices ====================
    price_unit_after_tax = fields.Float(string='Đơn giá (sau thuế)', readonly=True)
    price_unit_before_tax = fields.Float(string='Đơn giá (trước thuế)', readonly=True)

    # ==================== Amounts ====================
    amount_gross = fields.Monetary(
        string='Doanh thu xuất kho (gộp, sau thuế)', currency_field='currency_id', readonly=True,
        help='Tiền hàng đã xuất kho theo đơn giá sau thuế của dòng đơn bán (chưa trừ trả hàng).',
    )
    amount_returned = fields.Monetary(
        string='Tiền hàng trả lại (sau thuế)', currency_field='currency_id', readonly=True,
        help='Giá trị (theo đơn giá sau thuế) phần hàng đã bị khách trả lại, xác định qua '
             'stock.move.origin_returned_move_id của các phiếu nhập trả hàng.',
    )
    amount_net = fields.Monetary(
        string='Doanh thu xuất ròng (sau thuế)', currency_field='currency_id', readonly=True,
        help='= Doanh thu xuất kho (gộp) - Tiền hàng trả lại.',
    )
    amount_gross_untaxed = fields.Monetary(
        string='Doanh thu xuất kho (gộp, trước thuế)', currency_field='currency_id', readonly=True,
    )
    amount_net_untaxed = fields.Monetary(
        string='Doanh thu xuất ròng (trước thuế)', currency_field='currency_id', readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW hlv_customer_revenue_report AS (
                WITH move_return AS (
                    SELECT
                        origin_returned_move_id AS move_id,
                        SUM(quantity) AS returned_qty
                    FROM stock_move
                    WHERE state = 'done' AND origin_returned_move_id IS NOT NULL
                    GROUP BY origin_returned_move_id
                )
                SELECT
                    sm.id AS id,
                    sm.id AS move_id,
                    sm.picking_id AS picking_id,
                    sp.picking_type_id AS picking_type_id,
                    sm.sale_line_id AS sale_line_id,
                    sol.order_id AS sale_order_id,
                    so.company_id AS company_id,
                    spt.warehouse_id AS warehouse_id,
                    so.user_id AS user_id,
                    so.partner_id AS order_partner_id,
                    COALESCE(rp.commercial_partner_id, so.partner_id) AS partner_id,
                    sm.product_id AS product_id,
                    pt.categ_id AS product_categ_id,
                    sm.product_uom AS product_uom_id,
                    sol.currency_id AS currency_id,

                    so.date_order AS order_date,
                    sp.date_done AS date_done,

                    sm.quantity AS qty_delivered,
                    COALESCE(mr.returned_qty, 0.0) AS qty_returned,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) AS qty_net,

                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END AS price_unit_after_tax,
                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END AS price_unit_before_tax,

                    sm.quantity * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_gross,
                    COALESCE(mr.returned_qty, 0.0) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_returned,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_net,

                    sm.quantity * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_gross_untaxed,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_net_untaxed

                FROM stock_move sm
                JOIN sale_order_line sol ON sol.id = sm.sale_line_id
                JOIN sale_order so ON so.id = sol.order_id
                JOIN stock_picking sp ON sp.id = sm.picking_id
                JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                LEFT JOIN product_product pp ON pp.id = sm.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN move_return mr ON mr.move_id = sm.id
                WHERE sm.state = 'done'
                  AND spt.code = 'outgoing'
                  AND sm.sale_line_id IS NOT NULL
            )
        """)

    # ==================== Dashboard: khách hàng ====================
    @api.model
    def search_report_customers(self, term=False, limit=20):
        """Gợi ý khách hàng (chỉ những khách đã có phát sinh xuất kho trong báo cáo)."""
        domain = [('partner_id.name', 'ilike', term)] if term else []
        groups = self.read_group(domain, [], ['partner_id'], limit=limit, orderby='partner_id')
        return [
            {'id': g['partner_id'][0], 'name': g['partner_id'][1]}
            for g in groups if g.get('partner_id')
        ]

    # ==================== Dashboard: tổng hợp theo tháng ====================
    def _monthly_domain(self, partner_id, date_from=False, date_to=False):
        if not partner_id:
            raise UserError(_('Vui lòng chọn khách hàng.'))
        domain = [('partner_id', '=', partner_id)]
        if date_from:
            domain.append(('date_done', '>=', '%s 00:00:00' % date_from))
        if date_to:
            domain.append(('date_done', '<=', '%s 23:59:59' % date_to))
        return domain

    @api.model
    def get_customer_monthly_summary(self, partner_id, date_from=False, date_to=False):
        """Doanh thu theo tháng của 1 khách hàng: tiền đặt hàng (gộp), trả hàng, xuất ròng."""
        domain = self._monthly_domain(partner_id, date_from, date_to)
        groups = self.read_group(
            domain, MONTHLY_MEASURES, ['date_done:month'], orderby='date_done asc', lazy=False,
        )
        rows = []
        for g in groups:
            date_range = (g.get('__range') or {}).get('date_done:month') or {}
            rows.append({
                'month_label': g.get('date_done:month') or _('Không xác định'),
                'date_from': date_range.get('from'),
                'date_to': date_range.get('to'),
                'order_count': g.get('__count', 0),
                'qty_delivered': g.get('qty_delivered') or 0.0,
                'qty_returned': g.get('qty_returned') or 0.0,
                'qty_net': g.get('qty_net') or 0.0,
                'amount_gross': g.get('amount_gross') or 0.0,
                'amount_returned': g.get('amount_returned') or 0.0,
                'amount_net': g.get('amount_net') or 0.0,
            })
        return rows

    @api.model
    def get_customer_month_detail(self, partner_id, date_from, date_to):
        """Chi tiết theo đơn hàng trong khoảng [date_from, date_to) - dùng cho drawer."""
        if not date_from or not date_to:
            return []
        domain = self._monthly_domain(partner_id, False, False) + [
            ('date_done', '>=', date_from), ('date_done', '<', date_to),
        ]
        groups = self.read_group(
            domain, MONTHLY_MEASURES, ['sale_order_id'], orderby='sale_order_id asc', lazy=False,
        )
        rows = []
        for g in groups:
            order = g.get('sale_order_id')
            rows.append({
                'sale_order_id': order[0] if order else False,
                'sale_order_name': order[1] if order else _('(Không rõ đơn hàng)'),
                'qty_delivered': g.get('qty_delivered') or 0.0,
                'qty_returned': g.get('qty_returned') or 0.0,
                'qty_net': g.get('qty_net') or 0.0,
                'amount_gross': g.get('amount_gross') or 0.0,
                'amount_returned': g.get('amount_returned') or 0.0,
                'amount_net': g.get('amount_net') or 0.0,
            })
        return rows

    # ==================== Xuất Excel ====================
    def _create_export_attachment(self, filename, content):
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': 0,
        })
        return attachment.id

    @api.model
    def export_customer_revenue_excel(self, partner_id, date_from=False, date_to=False):
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise UserError(_('Khách hàng không tồn tại.'))

        monthly_rows = self.get_customer_monthly_summary(partner_id, date_from, date_to)

        monthly_headers = [
            'Tháng', 'Số đơn hàng', 'SL xuất kho', 'SL trả hàng', 'SL thực xuất (ròng)',
            'Tiền đặt hàng (gộp)', 'Tiền hàng trả lại', 'Doanh thu xuất ròng',
        ]
        monthly_data = [
            [
                r['month_label'], r['order_count'], r['qty_delivered'], r['qty_returned'], r['qty_net'],
                r['amount_gross'], r['amount_returned'], r['amount_net'],
            ]
            for r in monthly_rows
        ]

        detail_headers = [
            'Tháng', 'Đơn hàng', 'SL xuất kho', 'SL trả hàng', 'SL thực xuất (ròng)',
            'Tiền đặt hàng (gộp)', 'Tiền hàng trả lại', 'Doanh thu xuất ròng',
        ]
        detail_data = []
        for month_row in monthly_rows:
            for line in self.get_customer_month_detail(partner_id, month_row['date_from'], month_row['date_to']):
                detail_data.append([
                    month_row['month_label'], line['sale_order_name'],
                    line['qty_delivered'], line['qty_returned'], line['qty_net'],
                    line['amount_gross'], line['amount_returned'], line['amount_net'],
                ])

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#2a78d6', 'font_color': '#ffffff',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_money = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0', 'align': 'right'})

        def _write_sheet(name, headers, rows, money_cols):
            worksheet = workbook.add_worksheet(name[:31])
            worksheet.set_row(0, 22)
            for col, header in enumerate(headers):
                worksheet.write(0, col, header, fmt_header)
                worksheet.set_column(col, col, max(14, len(header) + 4))
            for row_idx, row in enumerate(rows, start=1):
                for col, value in enumerate(row):
                    worksheet.write(row_idx, col, value, fmt_money if col in money_cols else fmt_cell)

        _write_sheet('Theo thang', monthly_headers, monthly_data, money_cols={5, 6, 7})
        _write_sheet('Chi tiet don hang', detail_headers, detail_data, money_cols={5, 6, 7})

        workbook.close()
        output.seek(0)
        content = output.read()

        filename = 'doanh_thu_%s.xlsx' % (partner.name or partner_id)
        return self._create_export_attachment(filename, content)
