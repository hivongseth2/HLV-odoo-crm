# -*- coding: utf-8 -*-
import json
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    # === Số thứ tự & Bỏ qua ===
    sequence = fields.Integer(
        string="STT",
        default=10,
        help="Số thứ tự dòng trong YCMH.",
    )
    skip_processing = fields.Boolean(
        string="Bỏ qua?",
        default=False,
        help="Nếu bật, dòng này sẽ bị bỏ qua khi tạo RFQ và không tính vào tiến độ mua.",
    )

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
    
    # --- Các trường lưu thực tế mua hàng (từ Wizard chuyển qua) ---
    actual_qty = fields.Float(string="SL thực mua")
    actual_price_unit = fields.Float(string="Đơn giá thực mua")
    actual_tax_id = fields.Many2one('account.tax', string="Thuế (%) thu mua")
    actual_tax_rate = fields.Float(string="Thuế thu mua (%)")
    actual_discount_rate = fields.Float(string="CK thu mua (%)")
    actual_discount_amount = fields.Float(string="Tiền CK thu mua")
    actual_supplier_id = fields.Many2one('res.partner', string="NCC thực mua")

    # --- Các trường HTML hiển thị so sánh ở list view ---
    display_qty_html = fields.Html(string="Số lượng", compute="_compute_display_qty_html")
    display_price_unit_html = fields.Html(string="Đơn giá trước thuế (MISA)", compute="_compute_display_price_unit_html")
    display_tax_rate_html = fields.Html(string="% Thuế (MISA)", compute="_compute_display_tax_rate_html")
    display_discount_rate_html = fields.Html(string="TL chiết khấu (MISA)", compute="_compute_display_discount_rate_html")
    display_supplier_html = fields.Html(string="NCC", compute="_compute_display_supplier_html")

    # --- Dữ liệu NCC mới từ MISA (per-line) ---
    misa_new_supplier_json = fields.Text(
        string="Dữ liệu NCC mới (JSON)",
        help="Lưu thông tin NCC mới từ MISA cho riêng dòng này.",
    )
    misa_has_new_supplier = fields.Boolean(
        string="Có NCC mới",
        compute="_compute_line_has_new_supplier",
    )

    @api.depends('misa_new_supplier_json')
    def _compute_line_has_new_supplier(self):
        for line in self:
            if line.misa_new_supplier_json:
                try:
                    data = json.loads(line.misa_new_supplier_json)
                    line.misa_has_new_supplier = bool(data and data.get('name'))
                except (json.JSONDecodeError, TypeError, AttributeError):
                    line.misa_has_new_supplier = False
            else:
                line.misa_has_new_supplier = False

    def action_create_line_supplier(self):
        """Mở form tạo NCC mới với dữ liệu pre-fill từ MISA cho dòng này."""
        self.ensure_one()
        if not self.misa_new_supplier_json:
            raise UserError(_("Dòng này không có thông tin Nhà cung cấp mới từ MISA."))
        try:
            data = json.loads(self.misa_new_supplier_json)
        except (json.JSONDecodeError, TypeError):
            raise UserError(_("Dữ liệu NCC mới không hợp lệ."))

        context = {
            'default_name': data.get('name'),
            'default_phone': data.get('phone'),
            'default_street': data.get('address'),
            'default_vat': data.get('vat'),
            'default_supplier_rank': 1,
            'default_is_company': True,
            'default_company_type': 'company',
            'default_hlv_business_role': 'supplier',
            'link_to_pr_line_id': self.id,
            'default_x_partner_source': 'manual',
        }
        return {
            'name': _('Xác nhận & Tạo NCC – %s') % (data.get('name') or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

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

    def _format_misa_float(self, val):
        if not val:
            return "0"
        s = f"{val:,.2f}"
        s = s.replace(',', 'tmp').replace('.', ',').replace('tmp', '.')
        if ',' in s:
            s = s.rstrip('0').rstrip(',')
        return s

    @api.depends('product_qty', 'actual_qty')
    def _compute_display_qty_html(self):
        for line in self:
            qty_str = line._format_misa_float(line.product_qty)
            if line.actual_qty:
                act_qty_str = line._format_misa_float(line.actual_qty)
                line.display_qty_html = Markup(f"<div>{qty_str}</div><div style='font-size: 0.85rem; color: #2e7d32; font-weight: bold; font-style: italic;'>PO: {act_qty_str}</div>")
            else:
                line.display_qty_html = Markup(f"<div>{qty_str}</div>")

    @api.depends('misa_price_before_tax', 'actual_price_unit', 'actual_qty')
    def _compute_display_price_unit_html(self):
        for line in self:
            price_str = line._format_misa_float(line.misa_price_before_tax)
            if line.actual_qty:
                act_price_str = line._format_misa_float(line.actual_price_unit)
                line.display_price_unit_html = Markup(f"<div>{price_str}</div><div style='font-size: 0.85rem; color: #2e7d32; font-weight: bold; font-style: italic;'>PO: {act_price_str}</div>")
            else:
                line.display_price_unit_html = Markup(f"<div>{price_str}</div>")

    @api.depends('misa_tax_rate', 'actual_tax_rate', 'actual_qty')
    def _compute_display_tax_rate_html(self):
        for line in self:
            tax_str = line._format_misa_float(line.misa_tax_rate)
            if line.actual_qty:
                act_tax_str = line._format_misa_float(line.actual_tax_rate)
                line.display_tax_rate_html = Markup(f"<div>{tax_str}%</div><div style='font-size: 0.85rem; color: #2e7d32; font-weight: bold; font-style: italic;'>PO: {act_tax_str}%</div>")
            else:
                line.display_tax_rate_html = Markup(f"<div>{tax_str}%</div>")

    @api.depends('misa_discount_rate', 'actual_discount_rate', 'actual_qty')
    def _compute_display_discount_rate_html(self):
        for line in self:
            discount_str = line._format_misa_float(line.misa_discount_rate)
            if line.actual_qty:
                act_discount_str = line._format_misa_float(line.actual_discount_rate)
                line.display_discount_rate_html = Markup(f"<div>{discount_str}%</div><div style='font-size: 0.85rem; color: #2e7d32; font-weight: bold; font-style: italic;'>PO: {act_discount_str}%</div>")
            else:
                line.display_discount_rate_html = Markup(f"<div>{discount_str}%</div>")

    @api.depends('sale_proposed_supplier_id', 'actual_supplier_id', 'actual_qty')
    def _compute_display_supplier_html(self):
        for line in self:
            supplier_name = line.sale_proposed_supplier_id.name or ''
            if line.actual_qty:
                act_supplier_name = line.actual_supplier_id.name or ''
                line.display_supplier_html = Markup(f"<div>{supplier_name}</div><div style='font-size: 0.85rem; color: #2e7d32; font-weight: bold; font-style: italic;'>PO: {act_supplier_name}</div>")
            else:
                line.display_supplier_html = Markup(f"<div>{supplier_name}</div>")