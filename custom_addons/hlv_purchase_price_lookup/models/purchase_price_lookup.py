# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class PurchasePriceLookup(models.Model):
    """Một dòng = một dòng đơn mua đã nhập kho, để sale tra giá nhập theo mã / tên hàng."""

    _name = "hlv.purchase.price.lookup"
    _description = "Tra giá nhập cho Sale"
    _auto = False
    _rec_name = "order_ref"
    _order = "date_order desc, id desc"

    # Sale thường không có quyền đọc đơn mua: giữ tên đơn dạng chữ cho mọi người,
    # còn link mở đơn chỉ cho người có quyền mua hàng.
    order_id = fields.Many2one("purchase.order", "Đơn mua", readonly=True,
                               groups="purchase.group_purchase_user")
    order_ref = fields.Char("Số đơn mua", readonly=True)
    company_id = fields.Many2one("res.company", "Công ty", readonly=True)
    product_id = fields.Many2one("product.product", "Hàng hóa", readonly=True)
    default_code = fields.Char("Mã hàng", readonly=True)
    vendor_id = fields.Many2one("res.partner", "Nhà cung cấp", readonly=True)
    currency_id = fields.Many2one("res.currency", "Tiền tệ", readonly=True)
    product_uom_id = fields.Many2one("uom.uom", "ĐVT", readonly=True)

    price_incl = fields.Monetary("Giá sau VAT", readonly=True, aggregator=None)
    price_excl = fields.Monetary("Giá chưa VAT", readonly=True, aggregator=None)

    date_order = fields.Datetime("Ngày đơn hàng", readonly=True)
    date_received = fields.Datetime("Ngày nhập", readonly=True)
    date_returned = fields.Datetime("Ngày trả NCC", readonly=True)

    qty_ordered = fields.Float("SL mua", digits="Product Unit of Measure", readonly=True)
    qty_in = fields.Float("SL đã nhập", digits="Product Unit of Measure", readonly=True)
    qty_returned = fields.Float("SL trả NCC", digits="Product Unit of Measure", readonly=True)
    qty_net = fields.Float("SL còn giữ", digits="Product Unit of Measure", readonly=True,
                           help="SL đã nhập trừ SL đã trả nhà cung cấp.")
    return_state = fields.Selection([
        ("none", "Không trả"),
        ("partial", "Trả một phần"),
        ("full", "Trả hết"),
    ], "Trả NCC", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
            WITH moves AS (
                -- Chỉ lấy chặng chạm kho NCC: chặng nội bộ của nhập nhiều bước không gắn
                -- dòng mua nên không bị đếm trùng. SL quy về ĐVT của dòng mua (phiếu trả
                -- dùng ĐVT gốc của sản phẩm, có thể khác ĐVT trên đơn).
                SELECT sm.purchase_line_id AS line_id,
                       sm.date,
                       sm.quantity / mu.factor * lu.factor AS qty,
                       dst.usage = 'supplier' AS is_return
                  FROM stock_move sm
                  JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                  JOIN uom_uom mu ON mu.id = sm.product_uom
                  JOIN uom_uom lu ON lu.id = pol.product_uom
                  JOIN stock_location src ON src.id = sm.location_id
                  JOIN stock_location dst ON dst.id = sm.location_dest_id
                 WHERE sm.state = 'done'
                   AND sm.product_id = pol.product_id
                   AND (src.usage = 'supplier' OR dst.usage = 'supplier')
            ), per_line AS (
                -- Không dùng qty_received của Odoo: phiếu trả bỏ tick "Update quantities
                -- on SO/PO" thì Odoo không trừ, sale sẽ thấy hàng vẫn còn dù đã trả NCC.
                SELECT line_id,
                       COALESCE(SUM(qty) FILTER (WHERE NOT is_return), 0) AS qty_in,
                       COALESCE(SUM(qty) FILTER (WHERE is_return), 0) AS qty_returned,
                       MIN(date) FILTER (WHERE NOT is_return) AS date_received,
                       MAX(date) FILTER (WHERE is_return) AS date_returned
                  FROM moves
                 GROUP BY line_id
            )
            SELECT pol.id,
                   po.id AS order_id,
                   po.name AS order_ref,
                   po.company_id,
                   pol.product_id,
                   pp.default_code,
                   COALESCE(rp.commercial_partner_id, rp.id) AS vendor_id,
                   po.currency_id,
                   pol.product_uom AS product_uom_id,
                   pol.price_total / NULLIF(pol.product_qty, 0) AS price_incl,
                   pol.price_subtotal / NULLIF(pol.product_qty, 0) AS price_excl,
                   po.date_order,
                   pl.date_received,
                   pl.date_returned,
                   pol.product_qty AS qty_ordered,
                   pl.qty_in,
                   pl.qty_returned,
                   pl.qty_in - pl.qty_returned AS qty_net,
                   CASE
                       WHEN pl.qty_returned <= 0 THEN 'none'
                       WHEN pl.qty_returned >= pl.qty_in THEN 'full'
                       ELSE 'partial'
                   END AS return_state
              FROM purchase_order_line pol
              JOIN purchase_order po ON po.id = pol.order_id
              JOIN product_product pp ON pp.id = pol.product_id
              JOIN res_partner rp ON rp.id = po.partner_id
              JOIN per_line pl ON pl.line_id = pol.id
             WHERE po.state IN ('purchase', 'done')
               AND pol.display_type IS NULL
               -- Chỉ lần mua đã thực nhập kho: giá trên đơn chưa nhập chưa chắc là giá
               -- chốt. Dòng nhập rồi trả hết vẫn giữ để sale thấy lần mua đó bị trả.
               AND pl.qty_in > 0
            )
        """)
