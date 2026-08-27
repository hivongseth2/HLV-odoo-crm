import base64
import io
from datetime import timedelta

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

# Whitelist cột ngày được phép dùng làm trục "theo tháng" cho thống kê tổng toàn công ty -
# date_field đến từ client nên KHÔNG được nội suy trực tiếp vào SQL, chỉ tra qua dict này.
MONTHLY_TOTALS_DATE_FIELDS = {
    'date_done': 'date_done',
    'order_date': 'order_date',
    'misa_order_date': 'misa_order_date',
}


class HlvCustomerRevenueReport(models.Model):
    _name = 'hlv.customer.revenue.report'
    _description = 'Báo cáo doanh thu theo khách hàng'
    _auto = False
    _rec_name = 'sale_order_id'
    _order = 'date_done desc'

    # ==================== Relations ====================
    # Grain = 1 dòng / 1 sale.order.line (không phải 1 stock.move) - xem ghi chú dài trong init().
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu xuất kho (đại diện)', readonly=True,
        help='1 dòng đơn bán có thể được xuất qua nhiều phiếu/nhiều đợt (đặc biệt với sản phẩm '
             'combo/kit - xem BOM) - trường này chỉ mang tính đại diện, không dùng để đối soát.',
    )
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
    order_date = fields.Datetime(string='Ngày đặt hàng (Odoo)', readonly=True)
    misa_order_date = fields.Date(
        string='Ngày đơn hàng (MISA)', readonly=True,
        help='sale.order.x_studio_misa_order_date - ngày đơn hàng ghi nhận trên MISA, '
             'có thể khác ngày tạo/xác nhận đơn trên Odoo.',
    )
    date_done = fields.Datetime(string='Ngày xuất kho', readonly=True)

    # ==================== Quantities ====================
    qty_delivered = fields.Float(
        string='SL xuất kho', readonly=True,
        help='= sale.order.line.qty_delivered (Odoo tự tính, đúng cho cả sản phẩm combo/kit - '
             'KHÔNG cộng trực tiếp từ stock.move vì 1 dòng combo có thể nổ ra nhiều move theo '
             'từng linh kiện, cộng thẳng sẽ bị nhân sai số lượng).',
    )
    qty_returned = fields.Float(
        string='SL trả hàng', readonly=True,
        help='= qty_delivered × (tỉ lệ trả hàng), tỉ lệ này tính từ tổng SL trả / tổng SL xuất '
             'trên các stock.move của dòng - tỉ lệ vẫn đúng cho combo/kit (phần nhân do nổ BOM '
             'bị triệt tiêu ở tử và mẫu), miễn linh kiện được trả tương ứng tỉ lệ với nhau.',
    )
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
        help='= amount_gross × tỉ lệ trả hàng. Tỉ lệ trả hàng xác định qua '
             'stock.move.origin_returned_move_id của các phiếu nhập trả hàng (xem qty_returned).',
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
        """Grain = 1 dòng / 1 sale.order.line (KHÔNG phải 1 stock.move).

        Lý do đổi từ "1 dòng / 1 stock.move" sang "1 dòng / 1 sale.order.line": với sản phẩm
        combo/kit (BOM loại phantom), Odoo xuất kho bằng cách nổ 1 dòng đơn bán thành NHIỀU
        stock.move riêng theo từng linh kiện (VD 1 dòng "Combo x4 Bộ" nổ ra 3 move: máy x4,
        pin x8, sạc x4 - tất cả cùng trỏ về 1 sale_line_id). Nếu tính "đơn giá combo × số
        lượng của mỗi move" như bản cũ, số tiền sẽ bị nhân theo SỐ LINH KIỆN (VD x3), sai
        gấp nhiều lần giá trị thật của dòng đơn.

        Cách sửa: lấy SỐ LƯỢNG ĐÃ XUẤT trực tiếp từ sale_order_line.qty_delivered (field có
        sẵn của Odoo, tự tính đúng cho cả combo/kit qua logic BOM - không tự cộng từ
        stock_move). stock_move chỉ còn dùng để tính TỈ LỆ TRẢ HÀNG (return_ratio = tổng SL
        trả / tổng SL xuất trên các move của dòng) - tỉ lệ này vẫn đúng cho combo/kit vì hệ số
        nhân do nổ BOM xuất hiện ở CẢ tử và mẫu nên tự triệt tiêu, miễn các linh kiện được trả
        theo đúng tỉ lệ với nhau (trả nguyên combo, không trả lẻ 1 linh kiện).
        """
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
                ),
                line_moves AS (
                    SELECT
                        sm.sale_line_id AS sale_line_id,
                        MAX(sm.picking_id) AS picking_id,
                        MAX(sp.picking_type_id) AS picking_type_id,
                        MAX(spt.warehouse_id) AS warehouse_id,
                        MAX(sp.date_done) AS date_done,
                        SUM(sm.quantity) AS raw_qty,
                        SUM(COALESCE(mr.returned_qty, 0.0)) AS raw_returned_qty
                    FROM stock_move sm
                    JOIN stock_picking sp ON sp.id = sm.picking_id
                    JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                    LEFT JOIN move_return mr ON mr.move_id = sm.id
                    WHERE sm.state = 'done'
                      AND spt.code = 'outgoing'
                      AND sm.sale_line_id IS NOT NULL
                    GROUP BY sm.sale_line_id
                )
                SELECT
                    sol.id AS id,
                    lm.picking_id AS picking_id,
                    lm.picking_type_id AS picking_type_id,
                    sol.id AS sale_line_id,
                    sol.order_id AS sale_order_id,
                    so.company_id AS company_id,
                    lm.warehouse_id AS warehouse_id,
                    so.user_id AS user_id,
                    so.partner_id AS order_partner_id,
                    COALESCE(rp.commercial_partner_id, so.partner_id) AS partner_id,
                    so.shopee_shop_id AS shopee_shop_id,
                    (so.shopee_shop_id IS NOT NULL OR so.shopee_order_ref IS NOT NULL
                        OR rp.name ILIKE '%shopee%') AS is_shopee,
                    sol.product_id AS product_id,
                    pt.categ_id AS product_categ_id,
                    sol.product_uom AS product_uom_id,
                    sol.currency_id AS currency_id,

                    so.date_order AS order_date,
                    so.x_studio_misa_order_date AS misa_order_date,
                    lm.date_done AS date_done,

                    sol.qty_delivered AS qty_delivered,
                    sol.qty_delivered * (CASE WHEN lm.raw_qty != 0
                        THEN lm.raw_returned_qty / lm.raw_qty ELSE 0.0 END) AS qty_returned,
                    sol.qty_delivered * (1 - CASE WHEN lm.raw_qty != 0
                        THEN lm.raw_returned_qty / lm.raw_qty ELSE 0.0 END) AS qty_net,

                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END AS price_unit_after_tax,
                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END AS price_unit_before_tax,

                    sol.qty_delivered * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_gross,
                    sol.qty_delivered * (CASE WHEN lm.raw_qty != 0
                        THEN lm.raw_returned_qty / lm.raw_qty ELSE 0.0 END)
                        * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_returned,
                    sol.qty_delivered * (1 - CASE WHEN lm.raw_qty != 0
                        THEN lm.raw_returned_qty / lm.raw_qty ELSE 0.0 END)
                        * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_net,

                    sol.qty_delivered * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_gross_untaxed,
                    sol.qty_delivered * (1 - CASE WHEN lm.raw_qty != 0
                        THEN lm.raw_returned_qty / lm.raw_qty ELSE 0.0 END)
                        * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_net_untaxed

                FROM sale_order_line sol
                JOIN sale_order so ON so.id = sol.order_id
                JOIN line_moves lm ON lm.sale_line_id = sol.id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                LEFT JOIN product_product pp ON pp.id = sol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE sol.qty_delivered > 0
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

    def _extra_date_domain(self, order_date_from=False, order_date_to=False,
                            misa_order_date_from=False, misa_order_date_to=False):
        """3 trục ngày độc lập, dùng được đồng thời: ngày xuất kho (date_done, ở
        _base_date_domain), ngày đặt hàng gốc trên Odoo (order_date) và ngày đơn hàng
        ghi nhận trên MISA (misa_order_date, x_studio_misa_order_date - có thể khác
        order_date do backdating khi sync)."""
        domain = []
        if order_date_from:
            domain.append(('order_date', '>=', '%s 00:00:00' % order_date_from))
        if order_date_to:
            domain.append(('order_date', '<=', '%s 23:59:59' % order_date_to))
        if misa_order_date_from:
            domain.append(('misa_order_date', '>=', misa_order_date_from))
        if misa_order_date_to:
            domain.append(('misa_order_date', '<=', misa_order_date_to))
        return domain

    def _customers_summary_where(self, date_from, date_to, search, shopee_filter,
                                  order_date_from=False, order_date_to=False,
                                  misa_order_date_from=False, misa_order_date_to=False):
        """WHERE áp lên bảng gốc (chưa GROUP BY) - trả về (sql, params), luôn tham số hoá."""
        clauses = ['1 = 1']
        params = []
        if date_from:
            clauses.append('date_done >= %s')
            params.append('%s 00:00:00' % date_from)
        if date_to:
            clauses.append('date_done <= %s')
            params.append('%s 23:59:59' % date_to)
        if order_date_from:
            clauses.append('order_date >= %s')
            params.append('%s 00:00:00' % order_date_from)
        if order_date_to:
            clauses.append('order_date <= %s')
            params.append('%s 23:59:59' % order_date_to)
        if misa_order_date_from:
            clauses.append('misa_order_date >= %s')
            params.append(misa_order_date_from)
        if misa_order_date_to:
            clauses.append('misa_order_date <= %s')
            params.append(misa_order_date_to)
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
                               order_date_from=False, order_date_to=False,
                               misa_order_date_from=False, misa_order_date_to=False,
                               order_by='amount_net', order_dir='desc', limit=50, offset=0):
        """Danh sách khách hàng/shop Shopee có phát sinh trong khoảng thời gian, có phân trang.

        Đơn Shopee được gộp theo shop (shopee_shop_id), không theo contact chung chung.
        Group + sắp xếp + phân trang đều thực hiện bằng SQL để tránh phải kéo toàn bộ dữ liệu
        (có thể hàng chục nghìn dòng) qua ORM rồi mới xử lý ở Python.

        date_from/date_to lọc theo ngày xuất kho; order_date_from/to lọc theo ngày đặt hàng
        gốc trên Odoo; misa_order_date_from/to lọc theo ngày đơn hàng ghi nhận trên MISA -
        3 trục độc lập, có thể dùng đồng thời.
        """
        where_sql, params = self._customers_summary_where(
            date_from, date_to, search, shopee_filter,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )
        rows = self._fetch_customers_summary(where_sql, params, order_by, order_dir, limit, offset)
        total_count = self._count_customers_summary_groups(where_sql, params)
        return {'rows': rows, 'total_count': total_count}

    # ==================== Tổng toàn công ty theo tháng (KHÔNG tách theo khách hàng) ====================
    @api.model
    def get_overall_monthly_summary(self, date_from=False, date_to=False, search=False, shopee_filter='all',
                                     order_date_from=False, order_date_to=False,
                                     misa_order_date_from=False, misa_order_date_to=False,
                                     date_field='date_done'):
        """Doanh thu theo tháng CỘNG GỘP TẤT CẢ khách hàng/shop - dùng cho câu hỏi kiểu
        "tổng công ty bán ra bao nhiêu mỗi tháng trong khoảng T5-T7". Khác get_customers_summary
        (liệt kê từng khách hàng) và get_group_monthly_summary (theo tháng nhưng chỉ 1 khách
        hàng/shop) - đây là 1 dòng / 1 tháng, cộng dồn toàn bộ dữ liệu khớp filter.

        date_field chọn cột nào được dùng làm trục "tháng": 'date_done' (ngày xuất kho,
        mặc định), 'order_date' (ngày đặt hàng gốc Odoo) hoặc 'misa_order_date' (ngày đơn
        hàng MISA). date_from/date_to (+ order_date_from/to, misa_order_date_from/to) vẫn
        lọc dữ liệu độc lập với date_field như các API khác - muốn lọc theo tháng 5-7 dựa
        trên ngày nào thì truyền date_from/date_to (hoặc order_date_from/to...) tương ứng
        VÀ đặt date_field = trục đó để tháng hiển thị khớp với khoảng đã lọc.
        """
        date_col = MONTHLY_TOTALS_DATE_FIELDS.get(date_field, 'date_done')
        where_sql, params = self._customers_summary_where(
            date_from, date_to, search, shopee_filter,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )
        query = """
            SELECT
                TO_CHAR(DATE_TRUNC('month', {date_col}), 'YYYY-MM') AS month_key,
                TO_CHAR(DATE_TRUNC('month', {date_col}), 'YYYY-MM-DD') AS month_from,
                TO_CHAR(DATE_TRUNC('month', {date_col}) + INTERVAL '1 month' - INTERVAL '1 day', 'YYYY-MM-DD') AS month_to,
                COUNT(DISTINCT sale_order_id) AS order_count,
                COUNT(DISTINCT CASE WHEN is_shopee AND shopee_shop_id IS NOT NULL
                    THEN -shopee_shop_id ELSE partner_id END) AS customer_count,
                COALESCE(SUM(qty_delivered), 0) AS qty_delivered,
                COALESCE(SUM(qty_returned), 0) AS qty_returned,
                COALESCE(SUM(qty_net), 0) AS qty_net,
                COALESCE(SUM(amount_gross), 0) AS amount_gross,
                COALESCE(SUM(amount_returned), 0) AS amount_returned,
                COALESCE(SUM(amount_net), 0) AS amount_net
            FROM hlv_customer_revenue_report
            WHERE {where_sql} AND {date_col} IS NOT NULL
            GROUP BY 1, 2, 3
            ORDER BY 1
        """.format(where_sql=where_sql, date_col=date_col)
        self.env.cr.execute(query, params)
        rows = self.env.cr.dictfetchall()
        return [
            {
                'month_label': r['month_key'],
                'date_from': r['month_from'],
                'date_to': r['month_to'],
                'order_count': int(r['order_count']),
                'customer_count': int(r['customer_count']),
                'qty_delivered': float(r['qty_delivered']),
                'qty_returned': float(r['qty_returned']),
                'qty_net': float(r['qty_net']),
                'amount_gross': float(r['amount_gross']),
                'amount_returned': float(r['amount_returned']),
                'amount_net': float(r['amount_net']),
            }
            for r in rows
        ]

    # ==================== Dashboard: tổng hợp theo tháng (1 khách hàng / 1 shop) ====================
    def _group_domain(self, group_type, group_id, date_from=False, date_to=False,
                       order_date_from=False, order_date_to=False,
                       misa_order_date_from=False, misa_order_date_to=False):
        if not group_id:
            raise UserError(_('Vui lòng chọn khách hàng hoặc shop Shopee.'))
        field = 'shopee_shop_id' if group_type == 'shop' else 'partner_id'
        return (
            [(field, '=', group_id)]
            + self._base_date_domain(date_from, date_to)
            + self._extra_date_domain(order_date_from, order_date_to, misa_order_date_from, misa_order_date_to)
        )

    @staticmethod
    def _month_range_to_inclusive_dates(date_range):
        """Odoo read_group trả __range dạng {'from': đầu tháng, 'to': đầu THÁNG SAU (exclusive)}.
        Toàn bộ API này coi date_from/date_to là 2 đầu mút BAO GỒM (inclusive, giống
        _base_date_domain/_extra_date_domain) - nên chuẩn hoá về 'YYYY-MM-DD' và lùi 'to'
        lại 1 ngày để thành ngày cuối tháng thực, tránh lệch khi dùng lại ở endpoint khác
        (VD /customers/detail) mà không biết quy ước exclusive riêng của read_group."""
        raw_from = date_range.get('from')
        raw_to = date_range.get('to')
        date_from = fields.Datetime.from_string(raw_from).date().isoformat() if raw_from else False
        date_to = (
            (fields.Datetime.from_string(raw_to) - timedelta(days=1)).date().isoformat()
            if raw_to else False
        )
        return date_from, date_to

    @api.model
    def get_group_monthly_summary(self, group_type, group_id, date_from=False, date_to=False,
                                   order_date_from=False, order_date_to=False,
                                   misa_order_date_from=False, misa_order_date_to=False):
        """Doanh thu theo tháng của 1 khách hàng/shop: tiền đặt hàng (gộp), trả hàng, xuất ròng.

        date_from/date_to trả về trong mỗi dòng tháng là 2 đầu mút BAO GỒM (inclusive) của
        tháng đó (VD tháng 7: '2026-07-01' -> '2026-07-31') - dùng thẳng được cho
        get_group_month_detail hay bất kỳ endpoint nào khác nhận date_from/date_to.
        """
        domain = self._group_domain(
            group_type, group_id, date_from, date_to,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )
        groups = self.read_group(domain, MONTHLY_MEASURES, ['date_done:month', 'sale_order_id'], lazy=False)

        agg = {}
        for g in groups:
            month_label = g.get('date_done:month') or _('Không xác định')
            entry = agg.get(month_label)
            if entry is None:
                date_range = (g.get('__range') or {}).get('date_done:month') or {}
                month_from, month_to = self._month_range_to_inclusive_dates(date_range)
                entry = self._new_agg_entry(
                    month_label=month_label,
                    date_from=month_from, date_to=month_to,
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
    def get_group_month_detail(self, group_type, group_id, date_from, date_to,
                                order_date_from=False, order_date_to=False,
                                misa_order_date_from=False, misa_order_date_to=False):
        """Chi tiết theo đơn hàng trong khoảng [date_from, date_to] (2 đầu mút BAO GỒM,
        giống mọi endpoint khác trong API này) - dùng cho drawer / để lấy danh sách đơn
        hàng của 1 khách hàng trong 1 tháng. date_from/date_to nên lấy nguyên từ dòng
        tháng do get_group_monthly_summary trả về.

        order_date_from/to, misa_order_date_from/to nên truyền lại giống hệt lúc gọi
        get_group_monthly_summary, để tổng các dòng ở đây khớp với dòng tháng đã hiển thị
        (tránh lệch khi tháng đó được lọc thêm theo ngày đặt hàng/MISA).
        """
        if not date_from or not date_to:
            return []
        domain = self._group_domain(
            group_type, group_id, date_from, date_to,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )
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

    # ==================== Chi tiết từng dòng sản phẩm (giá, số lượng...) ====================
    @api.model
    def get_order_lines_detail(self, order_name=False, group_type='partner', group_id=False,
                                date_from=False, date_to=False,
                                order_date_from=False, order_date_to=False,
                                misa_order_date_from=False, misa_order_date_to=False,
                                limit=500, offset=0):
        """Chi tiết TỪNG DÒNG SẢN PHẨM (không gộp theo đơn hàng như get_group_month_detail)
        - trả về sản phẩm, số lượng, đơn giá, thành tiền của từng dòng.

        2 cách gọi:
        - order_name: chỉ lấy đúng 1 đơn hàng này (VD "DH125524949234726") - bỏ qua group_id/date.
        - Không truyền order_name: bắt buộc group_type + group_id, lọc thêm theo date_from/date_to
          (+ order_date_from/to, misa_order_date_from/to) như các endpoint khác - lấy TẤT CẢ dòng
          sản phẩm của khách hàng/shop đó trong khoảng thời gian.
        """
        if order_name:
            domain = [('sale_order_id.name', '=', order_name)]
        else:
            if not group_id:
                raise UserError(_('Vui lòng truyền order_name, hoặc group_id + khoảng ngày.'))
            domain = self._group_domain(
                group_type, group_id, date_from, date_to,
                order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
            )

        total_count = self.search_count(domain)
        records = self.search(domain, order='sale_order_id, id', limit=limit, offset=offset)
        rows = [{
            'sale_order_id': r.sale_order_id.id,
            'sale_order_name': r.sale_order_id.name,
            'partner_id': r.partner_id.id,
            'partner_name': r.partner_id.name,
            'product_id': r.product_id.id,
            'product_name': r.product_id.display_name,
            'product_code': r.product_id.default_code or '',
            'product_category': r.product_categ_id.name or '',
            'uom': r.product_uom_id.name or '',
            'qty_delivered': r.qty_delivered,
            'qty_returned': r.qty_returned,
            'qty_net': r.qty_net,
            'price_unit_before_tax': r.price_unit_before_tax,
            'price_unit_after_tax': r.price_unit_after_tax,
            'amount_gross_untaxed': r.amount_gross_untaxed,
            'amount_gross': r.amount_gross,
            'amount_returned': r.amount_returned,
            'amount_net': r.amount_net,
            'date_done': fields.Datetime.to_string(r.date_done) if r.date_done else False,
            'order_date': fields.Datetime.to_string(r.order_date) if r.order_date else False,
            'misa_order_date': fields.Date.to_string(r.misa_order_date) if r.misa_order_date else False,
        } for r in records]
        return {'rows': rows, 'total_count': total_count}

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
    def export_customers_summary_excel(self, date_from=False, date_to=False, search=False, shopee_filter='all',
                                        order_date_from=False, order_date_to=False,
                                        misa_order_date_from=False, misa_order_date_to=False):
        where_sql, params = self._customers_summary_where(
            date_from, date_to, search, shopee_filter,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )
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
    def export_group_revenue_excel(self, group_type, group_id, date_from=False, date_to=False,
                                    order_date_from=False, order_date_to=False,
                                    misa_order_date_from=False, misa_order_date_to=False):
        if group_type == 'shop':
            group = self.env['shopee.shop'].browse(group_id)
        else:
            group = self.env['res.partner'].browse(group_id)
        if not group.exists():
            raise UserError(_('Khách hàng / shop không tồn tại.'))

        monthly_rows = self.get_group_monthly_summary(
            group_type, group_id, date_from, date_to,
            order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
        )

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
                order_date_from, order_date_to, misa_order_date_from, misa_order_date_to,
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
