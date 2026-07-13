# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    misa_line_id = fields.Char(
        string="MISA Line ID",
        index=True,
        help="ID dòng từ MISA CRM Database, dùng làm khóa định danh duy nhất 1-1 giữa MISA và Odoo. "
             "Mỗi dòng trong Yêu Cầu Mua Hàng trên MISA có một ID riêng, không phụ thuộc vào Mã Hàng.",
    )

    history_po_line_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Chọn giá từ lịch sử PO",
        domain="[('product_id', '=', product_id), ('state', 'in', ['purchase', 'done'])]",
        help="Chọn một dòng từ lịch sử mua hàng để lấy giá cho chi phí ước tính."
    )

    # --- Các trường lấy từ MISA CRM (Sale tự điền) ---
    misa_supplier_id = fields.Many2one('res.partner', string="Mã/Tên NCC (MISA)")
    sale_proposed_supplier_id = fields.Many2one('res.partner', string="NCC Sale Đề Xuất")
    misa_price_before_tax = fields.Float(string="Đơn giá trước thuế (MISA)")
    misa_price_after_tax = fields.Float(string="Đơn giá sau thuế (MISA)")
    misa_amount = fields.Float(string="Thành tiền (MISA)")
    misa_tax_amount = fields.Float(string="Thuế (MISA)")
    misa_tax_rate = fields.Float(string="% Thuế (MISA)")
    misa_discount_rate = fields.Float(string="TL chiết khấu (MISA)")
    misa_discount_amount = fields.Float(string="Tiền chiết khấu (MISA)")
    misa_stock_total = fields.Float(string="Tổng SL tồn kho (MISA)")
    misa_stock_selected = fields.Float(string="SL tồn kho đã chọn (MISA)")
    misa_stock_undelivered = fields.Float(string="SL tồn kho chưa giao (MISA)")

    # --- Computed fields để tự tính tổng khi người dùng thay đổi số lượng ---
    misa_price_before_tax_total = fields.Float(
        string="Tổng tiền trước thuế",
        compute="_compute_misa_financial_totals",
        store=True,
        digits='Product Price',
        help="Số lượng * Đơn giá trước thuế"
    )

    misa_tax_amount_total = fields.Float(
        string="Tổng tiền thuế",
        compute="_compute_misa_financial_totals",
        store=True,
        digits='Product Price',
        help="Số lượng * (Đơn giá trước thuế * Thuế suất / 100)"
    )

    misa_price_after_tax_total = fields.Float(
        string="Tổng tiền sau thuế",
        compute="_compute_misa_financial_totals",
        store=True,
        digits='Product Price',
        help="Số lượng * Đơn giá sau thuế"
    )

    misa_amount = fields.Float(
        string="Thành tiền (MISA)",
        compute="_compute_misa_financial_totals",
        store=True,
        digits='Product Price',
        help="Tổng trước thuế - Tiền chiết khấu + Tổng thuế"
    )

    @api.depends('product_qty', 'misa_price_before_tax', 'misa_tax_amount',
                 'misa_discount_amount', 'misa_price_after_tax')
    def _compute_misa_financial_totals(self):
        for line in self:
            before_tax = line.misa_price_before_tax or 0.0
            qty = line.product_qty or 0.0
            tax_amount = line.misa_tax_amount or 0.0
            discount_amount = line.misa_discount_amount or 0.0
            after_tax = line.misa_price_after_tax or 0.0

            before_tax_total = qty * before_tax
            line.misa_price_before_tax_total = before_tax_total
            line.misa_tax_amount_total = qty * (before_tax * (line.misa_tax_rate or 0.0) / 100.0)
            line.misa_price_after_tax_total = qty * after_tax
            line.misa_amount = before_tax_total - discount_amount + tax_amount

    # --- Onchange: tự động tính thuế 2 chiều ---
    @api.onchange('misa_tax_rate')
    def _onchange_misa_tax_rate(self):
        if self.misa_tax_rate and self.misa_price_before_tax and self.product_qty:
            self.misa_tax_amount = self.product_qty * self.misa_price_before_tax * self.misa_tax_rate / 100.0
        elif self.misa_tax_rate == 0 and not self.misa_tax_amount:
            self.misa_tax_amount = 0.0

    @api.onchange('misa_tax_amount')
    def _onchange_misa_tax_amount(self):
        base = (self.misa_price_before_tax or 0.0) * (self.product_qty or 0.0)
        if self.misa_tax_amount and base:
            self.misa_tax_rate = self.misa_tax_amount / base * 100.0
        elif self.misa_tax_amount == 0 and not self.misa_tax_rate:
            self.misa_tax_rate = 0.0

    # --- Onchange: tự động tính chiết khấu 2 chiều ---
    @api.onchange('misa_discount_rate')
    def _onchange_misa_discount_rate(self):
        if self.misa_discount_rate and self.misa_price_before_tax and self.product_qty:
            self.misa_discount_amount = self.product_qty * self.misa_price_before_tax * self.misa_discount_rate / 100.0
        elif self.misa_discount_rate == 0 and not self.misa_discount_amount:
            self.misa_discount_amount = 0.0

    @api.onchange('misa_discount_amount')
    def _onchange_misa_discount_amount(self):
        base = (self.misa_price_before_tax or 0.0) * (self.product_qty or 0.0)
        if self.misa_discount_amount and base:
            self.misa_discount_rate = self.misa_discount_amount / base * 100.0
        elif self.misa_discount_amount == 0 and not self.misa_discount_rate:
            self.misa_discount_rate = 0.0

    @api.onchange("product_id")
    def onchange_product_id(self):
        res = super(PurchaseRequestLine, self).onchange_product_id()
        if self.product_id:
            # Ưu tiên lấy giá từ Nhà cung cấp, nếu không có thì lấy giá chuẩn (Cost)
            supplier_info = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)
            ], limit=1, order='sequence, min_qty desc, price')

            if supplier_info:
                self.estimated_cost = supplier_info.price
            else:
                last_po_line = self.env['purchase.order.line'].search([
                    ('product_id', '=', self.product_id.id),
                    ('state', 'in', ['purchase', 'done'])
                ], limit=1, order='create_date desc')

                if last_po_line:
                    self.estimated_cost = last_po_line.price_unit
                else:
                    self.estimated_cost = self.product_id.standard_price
        return res

    @api.onchange("history_po_line_id")
    def _onchange_history_po_line_id(self):
        if self.history_po_line_id:
            self.estimated_cost = self.history_po_line_id.price_unit

    def action_view_price_history(self):
        """Mở wizard chọn giá từ lịch sử mua hàng."""
        self.ensure_one()
        if not self.product_id:
            return
        wizard = self.env['price.history.wizard'].create({
            'line_id': self.id,
        })
        return wizard.action_load()