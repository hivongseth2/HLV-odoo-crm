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

# Whitelist cột được phép ORDER BY trên danh sách khách hàng/shop - order_by đến từ client
# nên KHÔNG được nội suy trực tiếp vào SQL, chỉ tra qua dict này.
CUSTOMERS_SUMMARY_ORDER_COLUMNS = {
    'group_label': 'group_label',
    'order_count': 'order_count',
    'qty_delivered': 'qty_delivered',
    'qty_returned': 'qty_returned',
    'qty_net': 'qty_net',
    'amount_gross': 'amount_gross',
    'amount_returned': 'amount_returned',
    'amount_net': 'amount_net',
}

CUSTOMERS_SUMMARY_GROUP_SQL = """
    SELECT
        CASE WHEN is_shopee AND shopee_shop_id IS NOT NULL THEN 'shop' ELSE 'partner' END AS group_type,
        CASE WHEN is_shopee AND shopee_shop_id IS NOT NULL THEN shopee_shop_id ELSE partner_id END AS group_id,
        bool_or(is_shopee AND shopee_shop_id IS NOT NULL) AS is_shopee_group,
        COUNT(DISTINCT sale_order_id) AS order_count,
        COALESCE(SUM(qty_delivered), 0) AS qty_delivered,
        COALESCE(SUM(qty_returned), 0) AS qty_returned,
        COALESCE(SUM(qty_net), 0) AS qty_net,
        COALESCE(SUM(amount_gross), 0) AS amount_gross,
        COALESCE(SUM(amount_returned), 0) AS amount_returned,
        COALESCE(SUM(amount_net), 0) AS amount_net
    FROM hlv_customer_revenue_report
    WHERE {where_sql}
    GROUP BY 1, 2
"""


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
    shopee_shop_id = fields.Many2one('shopee.shop', string='Shop Shopee', readonly=True)
    is_shopee = fields.Boolean(
        string='Đơn Shopee', readonly=True,
        help='Đơn có shopee_shop_id / shopee_order_ref hoặc tên khách hàng chứa "shopee" '
             '(cùng cách nhận diện đang dùng ở export_outgoing_picking_excel).',
    )
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
                    so.shopee_shop_id AS shopee_shop_id,
                    (so.shopee_shop_id IS NOT NULL OR so.shopee_order_ref IS NOT NULL
                        OR rp.name ILIKE '%shopee%') AS is_shopee,
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

    # ==================== Dashboard: danh sách khách hàng / shop Shopee ====================
    # Đơn Shopee dùng chung 1 contact đại diện (VD "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE"),
    # nên với đơn Shopee ta gộp theo shopee_shop_id thay vì partner_id. group_type phân biệt
    # dòng nào là 1 khách hàng thật ('partner') và dòng nào là 1 shop Shopee ('shop').
    @staticmethod
    def _new_agg_entry(**extra):
        entry = {key.split(':')[0]: 0.0 for key in MONTHLY_MEASURES}
        entry['order_ids'] = set()
        entry.update(extra)
        return entry

    def _accumulate(self, entry, group):
        if group.get('sale_order_id'):
            entry['order_ids'].add(group['sale_order_id'][0])
        for key in ('qty_delivered', 'qty_returned', 'qty_net', 'amount_gross', 'amount_returned', 'amount_net'):
            entry[key] += group.get(key) or 0.0

    def _base_date_domain(self, date_from=False, date_to=False):
        domain = []
        if date_from:
            domain.append(('date_done', '>=', '%s 00:00:00' % date_from))
        if date_to:
            domain.append(('date_done', '<=', '%s 23:59:59' % date_to))
        return domain

    def _customers_summary_where(self, date_from, date_to, search, shopee_filter):
        """WHERE áp lên bảng gốc (chưa GROUP BY) - trả về (sql, params), luôn tham số hoá."""
        clauses = ['1 = 1']
        params = []
        if date_from:
            clauses.append('date_done >= %s')
            params.append('%s 00:00:00' % date_from)
        if date_to:
            clauses.append('date_done <= %s')
            params.append('%s 23:59:59' % date_to)
        if shopee_filter == 'shopee':
            clauses.append('is_shopee = true')
        elif shopee_filter == 'non_shopee':
            clauses.append('is_shopee = false')
        if search:
            clauses.append("""(
                partner_id IN (SELECT id FROM res_partner WHERE name ILIKE %s)
                OR shopee_shop_id IN (SELECT id FROM shopee_shop WHERE name ILIKE %s)
            )""")
            like = '%%%s%%' % search
            params += [like, like]
        return ' AND '.join(clauses), params

    def _fetch_customers_summary(self, where_sql, params, order_by='amount_net', order_dir='desc',
                                  limit=None, offset=0):
        """Query đã GROUP BY + JOIN tên hiển thị, tính toàn bộ phân trang/sắp xếp ở tầng DB
        (thay vì kéo hết dữ liệu ra rồi group bằng Python - rất chậm khi có hàng chục nghìn dòng)."""
        order_col = CUSTOMERS_SUMMARY_ORDER_COLUMNS.get(order_by, 'amount_net')
        order_dir_sql = 'ASC' if str(order_dir).lower() == 'asc' else 'DESC'

        limit_sql = ''
        query_params = list(params)
        if limit is not None:
            limit_sql = 'LIMIT %s OFFSET %s'
            query_params += [limit, offset]

        query = """
            SELECT
                grp.group_type, grp.group_id, grp.is_shopee_group, grp.order_count,
                grp.qty_delivered, grp.qty_returned, grp.qty_net,
                grp.amount_gross, grp.amount_returned, grp.amount_net,
                COALESCE(rp.name, ss.name) AS group_label
            FROM ({group_sql}) grp
            LEFT JOIN res_partner rp ON grp.group_type = 'partner' AND rp.id = grp.group_id
            LEFT JOIN shopee_shop ss ON grp.group_type = 'shop' AND ss.id = grp.group_id
            ORDER BY {order_col} {order_dir_sql} NULLS LAST
            {limit_sql}
        """.format(
            group_sql=CUSTOMERS_SUMMARY_GROUP_SQL.format(where_sql=where_sql),
            order_col=order_col, order_dir_sql=order_dir_sql, limit_sql=limit_sql,
        )
        self.env.cr.execute(query, query_params)
        rows = self.env.cr.dictfetchall()
        # SUM(...) trên cột numeric của Postgres trả về Decimal qua psycopg2 - ép về
        # float ngay ở đây để mọi nơi gọi (RPC nội bộ, API HTTP/json.dumps, Excel) đều
        # nhận kiểu số Python bình thường, tránh lỗi "Decimal is not JSON serializable".
        return [
            {
                'group_type': r['group_type'],
                'group_id': r['group_id'],
                'group_label': r['group_label'] or _('(Không xác định)'),
                'is_shopee_group': r['is_shopee_group'],
                'order_count': int(r['order_count']),
                'qty_delivered': float(r['qty_delivered']),
                'qty_returned': float(r['qty_returned']),
                'qty_net': float(r['qty_net']),
                'amount_gross': float(r['amount_gross']),
                'amount_returned': float(r['amount_returned']),
                'amount_net': float(r['amount_net']),
            }
            for r in rows
        ]

    def _count_customers_summary_groups(self, where_sql, params):
        query = """
            SELECT COUNT(*) FROM ({group_sql}) grp
        """.format(group_sql=CUSTOMERS_SUMMARY_GROUP_SQL.format(where_sql=where_sql))
        self.env.cr.execute(query, params)
        return self.env.cr.fetchone()[0]

    @api.model
    def get_customers_summary(self, date_from=False, date_to=False, search=False, shopee_filter='all',
                               order_by='amount_net', order_dir='desc', limit=50, offset=0):
        """Danh sách khách hàng/shop Shopee có phát sinh trong khoảng thời gian, có phân trang.

        Đơn Shopee được gộp theo shop (shopee_shop_id), không theo contact chung chung.
        Group + sắp xếp + phân trang đều thực hiện bằng SQL để tránh phải kéo toàn bộ dữ liệu
        (có thể hàng chục nghìn dòng) qua ORM rồi mới xử lý ở Python.
        """
        where_sql, params = self._customers_summary_where(date_from, date_to, search, shopee_filter)
        rows = self._fetch_customers_summary(where_sql, params, order_by, order_dir, limit, offset)
        total_count = self._count_customers_summary_groups(where_sql, params)
        return {'rows': rows, 'total_count': total_count}

    # ==================== Dashboard: tổng hợp theo tháng (1 khách hàng / 1 shop) ====================
    def _group_domain(self, group_type, group_id, date_from=False, date_to=False):
        if not group_id:
            raise UserError(_('Vui lòng chọn khách hàng hoặc shop Shopee.'))
        field = 'shopee_shop_id' if group_type == 'shop' else 'partner_id'
        return [(field, '=', group_id)] + self._base_date_domain(date_from, date_to)

    @api.model
    def get_group_monthly_summary(self, group_type, group_id, date_from=False, date_to=False):
        """Doanh thu theo tháng của 1 khách hàng/shop: tiền đặt hàng (gộp), trả hàng, xuất ròng."""
        domain = self._group_domain(group_type, group_id, date_from, date_to)
        groups = self.read_group(domain, MONTHLY_MEASURES, ['date_done:month', 'sale_order_id'], lazy=False)

        agg = {}
        for g in groups:
            month_label = g.get('date_done:month') or _('Không xác định')
            entry = agg.get(month_label)
            if entry is None:
                date_range = (g.get('__range') or {}).get('date_done:month') or {}
                entry = self._new_agg_entry(
                    month_label=month_label,
                    date_from=date_range.get('from'), date_to=date_range.get('to'),
                )
                agg[month_label] = entry
            self._accumulate(entry, g)

        rows = []
        for entry in agg.values():
            entry['order_count'] = len(entry.pop('order_ids'))
            rows.append(entry)
        rows.sort(key=lambda r: r['date_from'] or '')
        return rows

    @api.model
    def get_group_month_detail(self, group_type, group_id, date_from, date_to):
        """Chi tiết theo đơn hàng trong khoảng [date_from, date_to) - dùng cho drawer."""
        if not date_from or not date_to:
            return []
        domain = self._group_domain(group_type, group_id) + [
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

    def _build_workbook(self, sheets):
        """sheets: list of (name, headers, rows, money_cols)."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#2a78d6', 'font_color': '#ffffff',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_money = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0', 'align': 'right'})

        for name, headers, rows, money_cols in sheets:
            worksheet = workbook.add_worksheet(name[:31])
            worksheet.set_row(0, 22)
            for col, header in enumerate(headers):
                worksheet.write(0, col, header, fmt_header)
                worksheet.set_column(col, col, max(14, len(header) + 4))
            for row_idx, row in enumerate(rows, start=1):
                for col, value in enumerate(row):
                    worksheet.write(row_idx, col, value, fmt_money if col in money_cols else fmt_cell)

        workbook.close()
        output.seek(0)
        return output.read()

    @api.model
    def export_customers_summary_excel(self, date_from=False, date_to=False, search=False, shopee_filter='all'):
        where_sql, params = self._customers_summary_where(date_from, date_to, search, shopee_filter)
        rows = self._fetch_customers_summary(where_sql, params, limit=None)
        headers = [
            'Khách hàng / Shop', 'Đơn Shopee?', 'Số đơn hàng', 'SL xuất kho', 'SL trả hàng',
            'SL thực xuất (ròng)', 'Tiền đặt hàng (gộp)', 'Tiền hàng trả lại', 'Doanh thu xuất ròng',
        ]
        data = [
            [
                r['group_label'], 'Có' if r['is_shopee_group'] else '', r['order_count'],
                r['qty_delivered'], r['qty_returned'], r['qty_net'],
                r['amount_gross'], r['amount_returned'], r['amount_net'],
            ]
            for r in rows
        ]
        content = self._build_workbook([('Doanh thu khach hang', headers, data, {6, 7, 8})])
        return self._create_export_attachment('doanh_thu_khach_hang.xlsx', content)

    @api.model
    def export_group_revenue_excel(self, group_type, group_id, date_from=False, date_to=False):
        if group_type == 'shop':
            group = self.env['shopee.shop'].browse(group_id)
        else:
            group = self.env['res.partner'].browse(group_id)
        if not group.exists():
            raise UserError(_('Khách hàng / shop không tồn tại.'))

        monthly_rows = self.get_group_monthly_summary(group_type, group_id, date_from, date_to)

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
            for line in self.get_group_month_detail(
                group_type, group_id, month_row['date_from'], month_row['date_to'],
            ):
                detail_data.append([
                    month_row['month_label'], line['sale_order_name'],
                    line['qty_delivered'], line['qty_returned'], line['qty_net'],
                    line['amount_gross'], line['amount_returned'], line['amount_net'],
                ])

        content = self._build_workbook([
            ('Theo thang', monthly_headers, monthly_data, {5, 6, 7}),
            ('Chi tiet don hang', detail_headers, detail_data, {5, 6, 7}),
        ])
        filename = 'doanh_thu_%s.xlsx' % (group.name or group_id)
        return self._create_export_attachment(filename, content)
