# -*- coding: utf-8 -*-
"""
Model chính: return.sale.request
Quản lý đề nghị trả hàng bán từ khách hàng về nhà cung cấp
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

_STATES = [
    ("draft", "Nháp"),
    ("to_approve", "Chờ phê duyệt"),
    ("approved", "Đã phê duyệt"),
    ("in_progress", "Đang thực hiện"),
    ("done", "Hoàn thành"),
    ("rejected", "Từ chối"),
]


class ReturnSaleRequest(models.Model):
    _name = "return.sale.request"
    _description = "Đề nghị trả hàng bán"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    # ==================== Basic Fields ====================
    name = fields.Char(
        string="Mã đề nghị",
        required=True,
        default=lambda self: _("Mới"),
        tracking=True,
        copy=False,
    )
    date = fields.Date(
        string="Ngày đề nghị",
        default=fields.Date.context_today,
        tracking=True,
    )
    state = fields.Selection(
        selection=_STATES,
        string="Trạng thái",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    # ==================== MISA Fields ====================
    misa_id = fields.Integer(string="MISA ID", copy=False, index=True)
    # misa_return_sale_no removed - using name field for MISA code
    
    # ==================== Relations ====================
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Khách hàng",
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Đơn hàng gốc",
        tracking=True,
    )
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Đơn mua hàng",
        compute="_compute_purchase_order",
        store=True,
    )
    vendor_id = fields.Many2one(
        comodel_name="res.partner",
        string="Nhà cung cấp",
        compute="_compute_purchase_order",
        store=True,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Kho",
        compute="_compute_warehouse",
        store=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Công ty",
        default=lambda self: self.env.company,
    )
    requested_by = fields.Many2one(
        comodel_name="res.users",
        string="Người yêu cầu",
        default=lambda self: self.env.user,
        tracking=True,
    )

    # ==================== Detail Fields ====================
    line_ids = fields.One2many(
        comodel_name="return.sale.request.line",
        inverse_name="request_id",
        string="Chi tiết sản phẩm",
        copy=True,
    )
    total_amount = fields.Monetary(
        string="Tổng tiền",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        readonly=True,
    )
    return_reason = fields.Text(string="Lý do trả hàng")
    handling_method = fields.Char(string="Hướng xử lý")
    delivery_address = fields.Text(string="Địa chỉ giao hàng")
    description = fields.Text(string="Ghi chú")
    misa_owner_text = fields.Char(string="Người phụ trách (MISA)")

    # ==================== Stock Pickings ====================
    picking_in_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Phiếu nhập kho",
        copy=False,
    )
    picking_out_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Phiếu xuất NCC",
        copy=False,
    )
    picking_in_count = fields.Integer(
        compute="_compute_picking_count",
    )
    picking_out_count = fields.Integer(
        compute="_compute_picking_count",
    )

    # ==================== Computed Fields ====================
    is_editable = fields.Boolean(compute="_compute_is_editable")

    @api.depends("state")
    def _compute_is_editable(self):
        for rec in self:
            rec.is_editable = rec.state == "draft"

    @api.depends("line_ids.subtotal")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("subtotal"))

    @api.depends("sale_order_id")
    def _compute_purchase_order(self):
        """Tìm Purchase Order qua origin chứa mã SO"""
        PurchaseOrder = self.env["purchase.order"].sudo()
        for rec in self:
            po = False
            vendor = False
            if rec.sale_order_id:
                # Tìm PO có origin = tên SO
                po = PurchaseOrder.search([
                    ("origin", "ilike", rec.sale_order_id.name)
                ], limit=1)
                if po:
                    vendor = po.partner_id
            rec.purchase_order_id = po
            rec.vendor_id = vendor

    @api.depends("sale_order_id")
    def _compute_warehouse(self):
        """Lấy kho từ picking xuất bán của SO"""
        for rec in self:
            warehouse = False
            if rec.sale_order_id:
                # Tìm picking xuất (outgoing) của SO
                outgoing_pickings = rec.sale_order_id.picking_ids.filtered(
                    lambda p: p.picking_type_code == "outgoing"
                )
                if outgoing_pickings:
                    # Lấy warehouse từ location của picking đầu tiên
                    warehouse = outgoing_pickings[0].picking_type_id.warehouse_id
            if not warehouse:
                # Fallback về kho mặc định
                warehouse = self.env["stock.warehouse"].search([], limit=1)
            rec.warehouse_id = warehouse

    def _compute_picking_count(self):
        for rec in self:
            rec.picking_in_count = 1 if rec.picking_in_id else 0
            rec.picking_out_count = 1 if rec.picking_out_id else 0

    # ==================== CRUD Overrides ====================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Mới")) == _("Mới"):
                vals["name"] = self.env["ir.sequence"].next_by_code("return.sale.request") or _("Mới")
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Chỉ có thể xóa đề nghị ở trạng thái Nháp."))
        return super().unlink()

    # ==================== Workflow Actions ====================
    def button_submit(self):
        """Gửi duyệt"""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Vui lòng thêm ít nhất một dòng sản phẩm."))
        self.write({"state": "to_approve"})

    def button_approve(self):
        """Phê duyệt và tạo phiếu nhập kho"""
        for rec in self:
            rec._create_incoming_picking()
        self.write({"state": "approved"})

    def button_confirm_incoming(self):
        """Xác nhận hoàn thành nhập kho và tạo phiếu xuất NCC"""
        for rec in self:
            if rec.picking_in_id and rec.picking_in_id.state != "done":
                raise UserError(_("Phiếu nhập kho chưa hoàn thành."))
            rec._create_outgoing_picking()
        self.write({"state": "in_progress"})

    def button_done(self):
        """Hoàn thành"""
        for rec in self:
            if rec.picking_out_id and rec.picking_out_id.state != "done":
                raise UserError(_("Phiếu xuất NCC chưa hoàn thành."))
        self.write({"state": "done"})

    def button_reject(self):
        """Từ chối"""
        self.write({"state": "rejected"})

    def button_draft(self):
        """Đặt về nháp"""
        for rec in self:
            if rec.picking_in_id or rec.picking_out_id:
                raise UserError(_("Không thể đặt về nháp khi đã có phiếu kho."))
        self.write({"state": "draft"})

    # ==================== Stock Picking Creation ====================
    def _create_incoming_picking(self):
        """Tạo phiếu nhập kho từ Customer về Warehouse"""
        self.ensure_one()
        if not self.warehouse_id:
            raise UserError(_("Không xác định được kho."))
        
        picking_type = self.warehouse_id.in_type_id
        if not picking_type:
            raise UserError(_("Không tìm thấy loại phiếu nhập kho."))

        customer_location = self.env.ref("stock.stock_location_customers")
        
        picking_vals = {
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": customer_location.id,
            "location_dest_id": self.warehouse_id.lot_stock_id.id,
            "origin": self.name,
            "move_type": "direct",
        }
        picking = self.env["stock.picking"].create(picking_vals)
        
        # Tạo stock moves từ lines
        for line in self.line_ids:
            self.env["stock.move"].create({
                "name": line.product_id.name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.product_qty,
                "product_uom": line.product_uom_id.id,
                "picking_id": picking.id,
                "location_id": customer_location.id,
                "location_dest_id": self.warehouse_id.lot_stock_id.id,
            })
        
        picking.action_confirm()
        self.picking_in_id = picking
        _logger.info("Đã tạo phiếu nhập kho %s cho đề nghị %s", picking.name, self.name)

    def _create_outgoing_picking(self):
        """Tạo phiếu xuất kho về NCC"""
        self.ensure_one()
        if not self.warehouse_id or not self.vendor_id:
            raise UserError(_("Không xác định được kho hoặc nhà cung cấp."))
        
        picking_type = self.warehouse_id.out_type_id
        if not picking_type:
            raise UserError(_("Không tìm thấy loại phiếu xuất kho."))

        supplier_location = self.env.ref("stock.stock_location_suppliers")
        
        picking_vals = {
            "partner_id": self.vendor_id.id,
            "picking_type_id": picking_type.id,
            "location_id": self.warehouse_id.lot_stock_id.id,
            "location_dest_id": supplier_location.id,
            "origin": self.name,
            "move_type": "direct",
        }
        picking = self.env["stock.picking"].create(picking_vals)
        
        # Tạo stock moves từ lines
        for line in self.line_ids:
            self.env["stock.move"].create({
                "name": line.product_id.name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.product_qty,
                "product_uom": line.product_uom_id.id,
                "picking_id": picking.id,
                "location_id": self.warehouse_id.lot_stock_id.id,
                "location_dest_id": supplier_location.id,
            })
        
        picking.action_confirm()
        self.picking_out_id = picking
        _logger.info("Đã tạo phiếu xuất NCC %s cho đề nghị %s", picking.name, self.name)

    # ==================== View Actions ====================
    def action_view_picking_in(self):
        """Xem phiếu nhập kho"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": self.picking_in_id.id,
            "target": "current",
        }

    def action_view_picking_out(self):
        """Xem phiếu xuất NCC"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": self.picking_out_id.id,
            "target": "current",
        }

    # ==================== API Sync Methods ====================
    @api.model
    def api_sync_by_code(self, return_sale_code, create_when_missing=True):
        """API để sync đơn lẻ theo mã MISA"""
        try:
            misa_utils = self.env["misa.api.utils"]
            misa_config = self.env["misa.config"]
            
            # Lấy token
            crm_token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(crm_token)
            
            # Tìm ID từ Grid API
            grid_url = "https://amisapp.misa.vn/crm/g2/api/business/ReturnSale/Grid"
            payload = self._get_grid_payload_by_code(return_sale_code)
            
            import requests
            response = requests.post(grid_url, headers=headers, json=payload, timeout=60)
            if response.status_code != 200:
                return {"ok": False, "error": "api_error", "message": f"API error: {response.status_code}"}
            
            data = response.json().get("Data", [])
            if not data:
                if create_when_missing:
                    return {"ok": False, "action": "not_found", "message": f"Không tìm thấy {return_sale_code}"}
                return {"ok": True, "action": "not_found"}
            
            record_data = data[0]
            misa_id = record_data.get("ID")
            
            # Fetch detail
            return self._sync_from_misa_detail(misa_id, headers, record_data)
            
        except Exception as e:
            _logger.exception("Error syncing return sale %s", return_sale_code)
            return {"ok": False, "error": "exception", "message": str(e)}

    def _get_grid_payload_by_code(self, code):
        """Payload để tìm theo mã"""
        return {
            "Columns": "SUQsUmV0dXJuU2FsZU5vLFJldHVyblNhbGVOYW1lLFJldHVyblNhbGVEYXRlLEFjY291bnRJRCxBY2NvdW50SURUZXh0LFNhbGVPcmRlcklELFNhbGVPcmRlcklEVGV4dCxUb3RhbFN1bW1hcnksU3VnZ2VzdFN0YXR1c0lELFN1Z2dlc3RTdGF0dXNJRFRleHQsT3duZXJJRCxPd25lcklEVGV4dA==",
            "Filters": [
                {"Field": "ReturnSaleNo", "Operator": "=", "Value": code}
            ],
            "Start": 0,
            "Page": 1,
            "PageSize": 1,
        }

    def _sync_from_misa_detail(self, misa_id, headers, grid_data):
        """Sync từ MISA detail API"""
        import requests
        from dateutil.parser import parse
        
        # Fetch detail - Use correct URL pattern like SaleOrder: FormDataNew/{Entity}/{layout_id}/{form_type}
        detail_url = "https://amisapp.misa.vn/crm/g2/api/business/ReturnSale/FormDataNew/ReturnSale/122/4"
        payload = {
            "ID": str(misa_id),
            "MISAEntityState": 2,
            "ActiveLayoutCode": None,
            "CustomDicData": None
        }
        
        response = requests.post(detail_url, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            return {"ok": False, "error": "detail_error", "message": f"HTTP {response.status_code}"}
        
        result = response.json()
        if not result.get("Success"):
            return {"ok": False, "error": "detail_failed", "message": str(result)}
        
        detail_data = result.get("Data", {}).get("CurrentData", {})
        # Note: If CurrentData is null, detail_data will be {}
        if not detail_data and result.get("Data"):
             # Fallback if structure is different
             detail_data = result.get("Data")

        if not detail_data:
             return {"ok": False, "error": "no_detail_data"}

        # Parse data
        return_sale_no = detail_data.get("ReturnSaleNo", "")
        sale_order_text = detail_data.get("SaleOrderIDText", "")
        account_text = detail_data.get("AccountIDText", "")
        total_amount = detail_data.get("TotalSummary", 0)
        return_reason = detail_data.get("CustomField13", "")
        handling_method = detail_data.get("CustomField14", "")
        billing_address = detail_data.get("BillingAddress", "")
        owner_text = detail_data.get("OwnerIDText", "")
        product_codes_text = detail_data.get("ListProductIDText", "")
        
        # Parse date
        date_str = detail_data.get("ReturnSaleDate", "")
        request_date = False
        if date_str:
            try:
                request_date = parse(date_str).date()
            except Exception:
                pass
        
        # Find or create partner
        odoo_utils = self.env["odoo.utils"]
        partner = odoo_utils._get_or_create_partner(account_text) if account_text else False
        
        # Find Sale Order
        sale_order = False
        if sale_order_text:
            sale_order = self.env["sale.order"].search([("name", "=", sale_order_text)], limit=1)
        
        # Check existing by name (which is MISA code now)
        existing = self.search([("name", "=", return_sale_no)], limit=1)
        
        vals = {
            "name": return_sale_no,  # Use MISA code as name
            "misa_id": misa_id,
            "date": request_date or fields.Date.today(),
            "partner_id": partner.id if partner else False,
            "sale_order_id": sale_order.id if sale_order else False,
            "total_amount": total_amount,
            "return_reason": return_reason,
            "handling_method": handling_method,
            "delivery_address": billing_address,
            "misa_owner_text": owner_text,
        }
        
        if existing:
            existing.write(vals)
            # Update lines
            existing._sync_lines_from_misa(product_codes_text)
            return {"ok": True, "action": "updated", "res_id": existing.id, "name": existing.name}
        else:
            vals["state"] = "to_approve"
            new_record = self.create(vals)
            new_record._sync_lines_from_misa(product_codes_text)
            return {"ok": True, "action": "created", "res_id": new_record.id, "name": new_record.name}

    def _sync_lines_from_misa(self, product_codes_text, detail_data=None):
        """Sync lines từ danh sách mã sản phẩm MISA (fallback khi Lines API thất bại)
        
        Args:
            product_codes_text: comma-separated product codes from ListProductIDText
            detail_data: optional dict containing TotalSummary, AmountSummary for price calc
        """
        self.ensure_one()
        if not product_codes_text:
            return
        
        # Xóa lines cũ
        self.line_ids.unlink()
        
        codes = [c.strip() for c in product_codes_text.split(",") if c.strip()]
        Product = self.env["product.product"].sudo()
        OdooUtils = self.env["odoo.utils"].sudo()
        
        # Calculate unit price from detail_data if available
        unit_price = 0.0
        total_qty = 1.0
        if detail_data:
            total_summary = float(detail_data.get("ToCurrencySummary") or detail_data.get("TotalSummary") or 0)
            amount_summary = float(detail_data.get("AmountSummary") or 1)
            num_products = len(codes)
            if num_products > 0 and amount_summary > 0:
                # Phân bổ tổng tiền cho các sản phẩm, chia đều số lượng
                total_qty = amount_summary / num_products
                unit_price = total_summary / amount_summary if amount_summary > 0 else 0
        
        import logging
        _logger = logging.getLogger(__name__)
        
        for code in codes:
            product = Product.search([("default_code", "=", code)], limit=1)
            if not product:
                product = OdooUtils._get_or_create_product(
                    code=code, name=code, unit_name="Cái",
                    purchase_ok=True, sale_ok=True
                )
            
            if product:
                qty = total_qty if detail_data else 1.0
                price = unit_price if detail_data else product.lst_price
                
                self.env["return.sale.request.line"].create({
                    "request_id": self.id,
                    "product_id": product.id,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "unit_price": price,
                })
                _logger.info("📦 Fallback line: %s x%.2f @ %.2f", code, qty, price)

    def _sync_lines_from_misa_data(self, line_data):
        """Sync lines từ dữ liệu chi tiết MISA (DataSubPaging) với qty và price
        
        Args:
            line_data: list of dicts từ DataSubPaging API, mỗi dict chứa:
                - ProductIDText: mã sản phẩm
                - Amount: số lượng
                - Price: đơn giá
                - TotalAmount: thành tiền
                - UnitIDText: tên đơn vị
                - Description: mô tả
        """
        self.ensure_one()
        if not line_data:
            return
        
        # Xóa lines cũ
        self.line_ids.unlink()
        
        Product = self.env["product.product"].sudo()
        OdooUtils = self.env["odoo.utils"].sudo()
        
        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv
        
        import logging
        _logger = logging.getLogger(__name__)
        
        for line in line_data:
            code = (line.get("ProductIDText") or "").strip()
            if not code:
                continue
                
            # Parse data
            qty = _flt(line.get("Amount"), 1.0)
            price = _flt(line.get("Price"), 0.0)
            uom_name = (line.get("UnitIDText") or "Cái").strip()
            
            product = Product.search([("default_code", "=", code)], limit=1)
            if not product:
                product = OdooUtils._get_or_create_product(
                    code=code, name=code, unit_name=uom_name,
                    purchase_ok=True, sale_ok=True
                )
            
            if product:
                self.env["return.sale.request.line"].create({
                    "request_id": self.id,
                    "product_id": product.id,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "unit_price": price,
                })
                _logger.info("📦 Created line: %s x%.2f @ %.2f", code, qty, price)
