from odoo import api, fields, models, Command


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    supplier_id = fields.Many2one(required=False)

    toggle_keep_description = fields.Boolean(
        string="Giữ Mô tả (Tất cả)",
        default=True,
    )
    toggle_keep_estimated_cost = fields.Boolean(
        string="Giữ Giá (Tất cả)",
        default=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super(PurchaseRequestLineMakePurchaseOrder, self).default_get(fields_list)
        if 'supplier_id' in res:
            res['supplier_id'] = False
        return res

    @api.model
    def get_items(self, request_line_ids):
        request_line_obj = self.env["purchase.request.line"]
        items = []
        request_lines = request_line_obj.browse(request_line_ids)
        self._check_valid_request_line(request_line_ids)
        self.check_group(request_lines)
        for line in request_lines:
            remaining_qty = line.product_qty - line.purchased_qty
            if remaining_qty > 0:
                items.append([0, 0, self._prepare_item(line)])
        return items

    @api.model
    def _prepare_item(self, line):
        res = super(PurchaseRequestLineMakePurchaseOrder, self)._prepare_item(line)
        res['keep_description'] = True
        res['keep_estimated_cost'] = True

        remaining_qty = line.product_qty - line.purchased_qty
        res['product_qty'] = max(0.0, remaining_qty)
        res['actual_qty'] = max(0.0, remaining_qty)

        # --- Giá từ MISA / estimated_cost ---
        if hasattr(line, 'misa_price_before_tax') and line.misa_price_before_tax:
            res['estimated_cost'] = line.misa_price_before_tax * res['product_qty']
        elif line.estimated_cost:
            res['estimated_cost'] = line.estimated_cost

        # --- Sale đề xuất fields (chỉ đọc) ---
        if hasattr(line, 'misa_price_before_tax') and line.misa_price_before_tax:
            res['misa_price_before_tax'] = line.misa_price_before_tax
        if hasattr(line, 'misa_tax_rate') and line.misa_tax_rate:
            res['misa_tax_rate'] = line.misa_tax_rate
        if hasattr(line, 'misa_tax_amount') and line.misa_tax_amount:
            res['misa_tax_amount'] = line.misa_tax_amount
        if hasattr(line, 'misa_discount_rate') and line.misa_discount_rate:
            res['misa_discount_rate'] = line.misa_discount_rate
        if hasattr(line, 'misa_discount_amount') and line.misa_discount_amount:
            res['misa_discount_amount'] = line.misa_discount_amount

        # --- Actual fields (editable, mặc định = giá trị sale đề xuất) ---
        res['actual_price_unit'] = line.misa_price_before_tax if (hasattr(line, 'misa_price_before_tax') and line.misa_price_before_tax) else (line.estimated_cost / res['product_qty'] if line.estimated_cost and res['product_qty'] else 0.0)
        res['actual_tax_rate'] = line.misa_tax_rate if (hasattr(line, 'misa_tax_rate') and line.misa_tax_rate) else 0.0
        res['actual_discount_rate'] = line.misa_discount_rate if (hasattr(line, 'misa_discount_rate') and line.misa_discount_rate) else 0.0
        res['actual_discount_amount'] = line.misa_discount_amount if (hasattr(line, 'misa_discount_amount') and line.misa_discount_amount) else 0.0

        # Tìm account.tax cho misa_tax_id (sale đề xuất) và actual_tax_id (thực tế)
        company = line.company_id or self.env.company
        tax_rate = line.misa_tax_rate if (hasattr(line, 'misa_tax_rate') and line.misa_tax_rate) else 0.0
        if float(tax_rate) > 0:
            matched_tax = self.env['account.tax'].with_company(company).search([
                ('type_tax_use', '=', 'purchase'),
                ('amount_type', '=', 'percent'),
                ('amount', '=', float(tax_rate)),
                ('company_id', '=', company.id)
            ], limit=1)
            if matched_tax:
                res['misa_tax_id'] = matched_tax.id
                res['actual_tax_id'] = matched_tax.id

        # NCC: ưu tiên sale_proposed_supplier_id, fallback misa_supplier_id
        supplier = line.sale_proposed_supplier_id if hasattr(line, 'sale_proposed_supplier_id') and line.sale_proposed_supplier_id else False
        if not supplier:
            supplier = line.misa_supplier_id if hasattr(line, 'misa_supplier_id') and line.misa_supplier_id else False
        if supplier:
            res['supplier_id'] = supplier.id
        return res

    def _prepare_purchase_order_line(self, po, item):
        res = super()._prepare_purchase_order_line(po, item)

        # Số lượng thực mua
        if item.actual_qty and item.actual_qty > 0:
            res['product_qty'] = item.actual_qty

        # Đơn giá thực mua (ưu tiên actual_price_unit)
        if item.actual_price_unit and item.actual_price_unit > 0:
            res['price_unit'] = item.actual_price_unit

        # Thuế thực tế (ưu tiên actual_tax_id)
        if item.actual_tax_id:
            res['taxes_id'] = [Command.set(item.actual_tax_id.ids)]
        else:
            # Fallback: tìm theo actual_tax_rate
            tax_rate = item.actual_tax_rate
            if not tax_rate and hasattr(item.line_id.request_id, 'misa_id') and item.line_id.request_id.misa_id:
                tax_rate = 0  
            if tax_rate:
                if 'misa.po.fetch' in self.env:
                    misa_po_fetch_obj = self.env['misa.po.fetch'].with_company(po.company_id)
                    tax_ids = misa_po_fetch_obj._tax_ids_from_misa_line({'vat_rate': float(tax_rate)})
                    if tax_ids:
                        res['taxes_id'] = [Command.set(tax_ids)]
                    else:
                        res['taxes_id'] = [Command.clear()]
                else:
                    Tax = self.env['account.tax'].with_company(po.company_id)
                    matched_tax = Tax.search([
                        ('type_tax_use', '=', 'purchase'),
                        ('amount_type', '=', 'percent'),
                        ('amount', '=', float(tax_rate)),
                        ('company_id', '=', po.company_id.id)
                    ], limit=1)
                    if matched_tax:
                        res['taxes_id'] = [Command.set(matched_tax.ids)]
                    else:
                        res['taxes_id'] = [Command.clear()]
        return res

    def _reload_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_toggle_description_on(self):
        self.ensure_one()
        self.toggle_keep_description = True
        self.item_ids.write({'keep_description': True})
        return self._reload_wizard()

    def action_toggle_description_off(self):
        self.ensure_one()
        self.toggle_keep_description = False
        self.item_ids.write({'keep_description': False})
        return self._reload_wizard()

    def action_toggle_cost_on(self):
        self.ensure_one()
        self.toggle_keep_estimated_cost = True
        self.item_ids.write({'keep_estimated_cost': True})
        return self._reload_wizard()

    def action_toggle_cost_off(self):
        self.ensure_one()
        self.toggle_keep_estimated_cost = False
        self.item_ids.write({'keep_estimated_cost': False})
        return self._reload_wizard()


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(default=True)
    keep_estimated_cost = fields.Boolean(default=True)

    # === Sale đề xuất (từ PR, readonly) ===
    misa_price_before_tax = fields.Float(
        string="Đơn giá sale đề xuất",
        readonly=True,
    )
    misa_tax_id = fields.Many2one(
        'account.tax',
        string="Thuế sale yêu cầu",
        readonly=True,
        domain="[('type_tax_use', '=', 'purchase'), ('amount_type', '=', 'percent')]",
    )
    misa_tax_rate = fields.Float(
        string="Thuế sale yêu cầu (%)",
        readonly=True,
    )
    misa_tax_amount = fields.Float(
        string="Thuế",
        readonly=True,
    )
    misa_discount_rate = fields.Float(
        string="CK sale đề xuất (%)",
        readonly=True,
    )
    misa_discount_amount = fields.Float(
        string="Tiền CK sale đề xuất",
        readonly=True,
    )

    # === Thực tế (editable, dùng để lên PO) ===
    actual_qty = fields.Float(
        string="SL thực mua",
        help="Số lượng thực tế cần mua. Để trống sẽ dùng số lượng đề xuất.",
    )
    actual_price_unit = fields.Float(
        string="Đơn giá thực mua",
        help="Đơn giá thực tế mua hàng. Để trống sẽ dùng đơn giá từ yêu cầu.",
    )
    actual_tax_id = fields.Many2one(
        'account.tax',
        string="Thuế (%) thu mua",
        domain="[('type_tax_use', '=', 'purchase'), ('amount_type', '=', 'percent')]",
        help="Chọn thuế mua hàng. Ưu tiên sử dụng cột này trước actual_tax_rate.",
    )
    actual_tax_rate = fields.Float(
        string="Thuế thu mua (%)",
        help="Thuế suất (số). Chỉ dùng khi không chọn được Thuế từ danh sách.",
    )
    actual_discount_rate = fields.Float(
        string="CK thu mua (%)",
        help="Chiết khấu thực tế (%). Nhập % → tự tính tiền. Nhập tiền → tự tính %.",
    )
    actual_discount_amount = fields.Float(
        string="Tiền CK thu mua",
        help="Chiết khấu thực tế (tiền). Nhập tiền → tự tính %. Nhập % → tự tính tiền.",
    )

    # === Computed fields (readonly) ===
    misa_price_before_tax_total = fields.Float(
        string="Tổng tiền trước thuế",
        compute="_compute_wizard_financials",
        readonly=True,
        digits='Product Price',
    )
    misa_tax_amount_total = fields.Float(
        string="Tổng tiền thuế",
        compute="_compute_wizard_financials",
        readonly=True,
        digits='Product Price',
    )
    misa_amount = fields.Float(
        string="Thành tiền",
        compute="_compute_wizard_financials",
        readonly=True,
        digits='Product Price',
    )

    supplier_ref = fields.Char(
        related='supplier_id.ref',
        string="Mã NCC",
        readonly=True
    )

    @api.depends('actual_qty', 'actual_price_unit', 'actual_tax_rate', 'actual_discount_amount')
    def _compute_wizard_financials(self):
        for item in self:
            qty = item.actual_qty or item.product_qty or 0.0
            price = item.actual_price_unit or 0.0
            tax_rate = item.actual_tax_rate or 0.0
            discount = item.actual_discount_amount or 0.0

            before_tax_total = qty * price
            tax_total = qty * price * tax_rate / 100.0
            item.misa_price_before_tax_total = before_tax_total
            item.misa_tax_amount_total = tax_total
            item.misa_amount = before_tax_total - discount + tax_total

    # --- Onchange: tự động tính chiết khấu 2 chiều ---
    @api.onchange('actual_discount_rate')
    def _onchange_actual_discount_rate(self):
        qty = self.actual_qty or self.product_qty or 0.0
        if self.actual_discount_rate and self.actual_price_unit and qty:
            self.actual_discount_amount = qty * self.actual_price_unit * self.actual_discount_rate / 100.0
        elif self.actual_discount_rate == 0 and not self.actual_discount_amount:
            self.actual_discount_amount = 0.0

    @api.onchange('actual_discount_amount')
    def _onchange_actual_discount_amount(self):
        qty = self.actual_qty or self.product_qty or 0.0
        base = (self.actual_price_unit or 0.0) * qty
        if self.actual_discount_amount and base:
            self.actual_discount_rate = self.actual_discount_amount / base * 100.0
        elif self.actual_discount_amount == 0 and not self.actual_discount_rate:
            self.actual_discount_rate = 0.0

    @api.onchange('actual_tax_id')
    def _onchange_actual_tax_id(self):
        """Khi chọn thuế từ danh sách, tự động cập nhật actual_tax_rate."""
        if self.actual_tax_id and self.actual_tax_id.amount_type == 'percent':
            self.actual_tax_rate = self.actual_tax_id.amount

    @api.onchange('actual_qty', 'actual_price_unit', 'actual_tax_rate')
    def _onchange_actual_qty_price_tax(self):
        """Kích hoạt tính toán lại cho các trường phụ thuộc."""
        # Gọi hàm tương tự vì Odoo sẽ tự động update UI
        pass
