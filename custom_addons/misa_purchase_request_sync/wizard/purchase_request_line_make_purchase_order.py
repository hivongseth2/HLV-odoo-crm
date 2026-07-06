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
        # Xóa trường supplier_id (Nhà cung cấp chung) để không tự động chọn,
        # tránh việc Odoo (hoặc module OCA) tự động gán tên NCC chung và ghi đè lên các dòng bên dưới.
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
            # Thay vì dùng pending_qty_to_receive (trừ đi số lượng đã nhận), 
            # dùng purchased_qty để trừ đi số lượng đã lên PO (kể cả nháp)
            remaining_qty = line.product_qty - line.purchased_qty
            if remaining_qty > 0:
                items.append([0, 0, self._prepare_item(line)])
        return items

    @api.model
    def _prepare_item(self, line):
        res = super(PurchaseRequestLineMakePurchaseOrder, self)._prepare_item(line)
        res['keep_description'] = True
        res['keep_estimated_cost'] = True

        # Sửa lại số lượng cần mua = SL yêu cầu - SL đã lên PO (kể cả nháp)
        remaining_qty = line.product_qty - line.purchased_qty
        res['product_qty'] = max(0.0, remaining_qty)

        # Cập nhật estimated_cost tạm thời (OCA dùng để tính price_unit mặc định)
        # _post_process_po_line sẽ ghi đè price_unit sau cùng
        misa_price = False
        if hasattr(line, 'misa_price_before_tax') and line.misa_price_before_tax:
            misa_price = line.misa_price_before_tax
        if not misa_price and line.estimated_cost:
            misa_price = line.estimated_cost
        if misa_price:
            res['estimated_cost'] = misa_price

        # NCC: ưu tiên sale_proposed_supplier_id, fallback misa_supplier_id
        supplier = line.sale_proposed_supplier_id if hasattr(line, 'sale_proposed_supplier_id') and line.sale_proposed_supplier_id else False
        if not supplier:
            supplier = line.misa_supplier_id if hasattr(line, 'misa_supplier_id') and line.misa_supplier_id else False
        if supplier:
            res['supplier_id'] = supplier.id
        return res

    @api.model
    def _prepare_purchase_order_line(self, po, item):
        res = super()._prepare_purchase_order_line(po, item)
        # ── Cập nhật thuế trong lúc prepare (an toàn hơn là write sau khi create) ──
        if hasattr(item.line_id, 'misa_tax_rate') and item.line_id.misa_tax_rate is not False:
            is_from_misa = hasattr(item.line_id.request_id, 'misa_id') and item.line_id.request_id.misa_id
            if item.line_id.misa_tax_rate > 0 or is_from_misa:
                tax_rate = item.line_id.misa_tax_rate
                
                if 'misa.po.fetch' in self.env:
                    misa_po_fetch_obj = self.env['misa.po.fetch'].with_company(po.company_id)
                    tax_ids = misa_po_fetch_obj._tax_ids_from_misa_line({'vat_rate': tax_rate})
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
        """Trả về action mở lại wizard hiện tại (đã lưu) để refresh giao diện."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Toggle Giữ Mô tả ──────────────────────────────────────────
    def action_toggle_description_on(self):
        """Bật Giữ Mô tả cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_description = True
        self.item_ids.write({'keep_description': True})
        return self._reload_wizard()

    def action_toggle_description_off(self):
        """Tắt Giữ Mô tả cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_description = False
        self.item_ids.write({'keep_description': False})
        return self._reload_wizard()

    # ── Toggle Giữ Giá ────────────────────────────────────────────
    def action_toggle_cost_on(self):
        """Bật Giữ Giá cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_estimated_cost = True
        self.item_ids.write({'keep_estimated_cost': True})
        return self._reload_wizard()

    def action_toggle_cost_off(self):
        """Tắt Giữ Giá cho TẤT CẢ dòng."""
        self.ensure_one()
        self.toggle_keep_estimated_cost = False
        self.item_ids.write({'keep_estimated_cost': False})
        return self._reload_wizard()


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order.item"

    keep_description = fields.Boolean(default=True)
    keep_estimated_cost = fields.Boolean(default=True)
    misa_price_before_tax = fields.Float(
        related='line_id.misa_price_before_tax', 
        string="Đơn giá MISA", 
        readonly=True
    )

    def _post_process_po_line(self, item, po_line, new_pr_line):
        super()._post_process_po_line(item, po_line, new_pr_line)
        if item.line_id:
            # ── Cập nhật đơn giá ──
            # Sử dụng write để đảm bảo Odoo 18 lưu dữ liệu và không bị compute đè lại
            price = False
            if hasattr(item.line_id, 'misa_price_before_tax') and item.line_id.misa_price_before_tax:
                price = item.line_id.misa_price_before_tax
            elif item.line_id.estimated_cost:
                price = item.line_id.estimated_cost
            
            if price:
                po_line.write({'price_unit': price})
