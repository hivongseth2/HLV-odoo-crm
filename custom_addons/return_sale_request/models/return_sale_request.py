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
    # ("return_sale", "Xử lý trả đơn bán"),
    # ("return_purchase", "Xử lý trả hàng mua"),
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
    misa_summary_total = fields.Monetary(
        string="Tổng tiền MISA (SummaryData)",
        currency_field="currency_id",
        copy=False,
    )
    use_misa_summary_total = fields.Boolean(
        string="Dùng tổng tiền MISA",
        copy=False,
        default=False,
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

    @api.depends("line_ids.line_total", "use_misa_summary_total", "misa_summary_total")
    def _compute_total_amount(self):
        for rec in self:
            if rec.use_misa_summary_total:
                rec.total_amount = rec.misa_summary_total or 0.0
            else:
                rec.total_amount = sum(rec.line_ids.mapped("line_total"))

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
        """Xác nhận đề nghị (Hoàn thành) - Đã comment quy trình kho theo yêu cầu"""
        # self._auto_start_processing(force=True)
        self.write({"state": "done"})
        for rec in self:
            try:
                rec._send_zns_notification()
            except Exception as e:
                _logger.exception("Lỗi khi gửi thông báo Zalo cho đề nghị %s: %s", rec.name, e)

    def _send_zns_notification(self):
        """Gửi thông báo Zalo cho kho khi đề nghị trả hàng được xác nhận (Done).

        Lấy recipients theo kho từ incoming_warehouse_mapping_text của config,
        fallback về incoming_recipient_user_id nếu không có mapping riêng.
        """
        self.ensure_one()

        config = self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
        if not config:
            _logger.info("Zalo: Không tìm thấy config active, bỏ qua gửi thông báo cho %s", self.name)
            return

        # Xác định warehouse_code từ warehouse_id
        warehouse_code = self.warehouse_id.code if self.warehouse_id else None

        # Lấy danh sách recipients theo kho
        recipient_user_ids = []
        if warehouse_code:
            recipient_user_ids = config.get_recipients_for_incoming_warehouse(warehouse_code)

        # Fallback về global incoming recipient
        if not recipient_user_ids and config.incoming_recipient_user_id:
            recipient_user_ids = [config.incoming_recipient_user_id]

        if not recipient_user_ids:
            _logger.warning(
                "Zalo: Không có recipient nào được cấu hình cho kho '%s' (đề nghị %s)",
                warehouse_code, self.name
            )
            return

        # Khử trùng
        recipient_user_ids = list(dict.fromkeys(str(u).strip() for u in recipient_user_ids if u))

        # Build nội dung tin nhắn
        message = self._format_zns_return_message()

        # Lấy access token
        try:
            access_token = config.get_valid_access_token()
            if not access_token:
                _logger.error("Zalo: Không có access_token hợp lệ, bỏ qua gửi thông báo cho %s", self.name)
                return
        except Exception as e:
            _logger.exception("Zalo: Lỗi lấy access_token cho %s: %s", self.name, e)
            return

        _logger.info(
            "Zalo Return Notification: Gửi thông báo cho đề nghị %s, kho=%s, recipients=%s",
            self.name, warehouse_code, recipient_user_ids
        )

        for uid in recipient_user_ids:
            try:
                result = config.send_notification_message(uid, message)
                if result and result.get("error") == 0:
                    _logger.info("✓ Zalo: Gửi thành công tới %s cho đề nghị %s", uid, self.name)
                else:
                    _logger.error(
                        "✗ Zalo: Gửi thất bại tới %s cho đề nghị %s. Kết quả: %s",
                        uid, self.name, result
                    )
            except Exception as e:
                _logger.exception("✗ Zalo: Exception khi gửi tới %s cho đề nghị %s: %s", uid, self.name, e)

    def _format_zns_return_message(self):
        """Tạo nội dung tin nhắn Zalo cho đề nghị trả hàng."""
        self.ensure_one()

        partner_name = self.partner_id.name if self.partner_id else "(chưa có)"
        sale_order_name = self.sale_order_id.name if self.sale_order_id else "(chưa có)"
        warehouse_name = self.warehouse_id.name if self.warehouse_id else "(chưa có)"
        date_str = self.date.strftime("%d/%m/%Y") if self.date else ""

        message = f"🔔 ĐỀ NGHỊ TRẢ HÀNG XÁC NHẬN\n"
        message += f"  • Mã đề nghị: {self.name}\n"
        message += f"  • Ngày: {date_str}\n"
        message += f"  • Đơn hàng gốc: {sale_order_name}\n"
        message += f"  • Khách hàng: {partner_name}\n"
        message += f"  • Kho: {warehouse_name}\n"

        if self.line_ids:
            message += "\n📦 Sản phẩm trả:\n"
            for line in self.line_ids:
                product_name = line.product_id.display_name if line.product_id else "?"
                qty = line.product_qty
                uom = line.product_uom_id.name if line.product_uom_id else ""
                message += f"  • {product_name}: {qty:g} {uom}\n"

        if self.return_reason:
            message += f"\n📝 Lý do: {self.return_reason}\n"

        return message

    # def button_approve(self):
    #     """Deprecated - Same as button_submit now"""
    #     self.button_submit()

    # def button_confirm_incoming(self):
    #     """Xác nhận hoàn thành nhập kho và chuyển bước tiếp theo
    #     - Nếu có NCC: tạo phiếu xuất NCC -> chuyển sang 'return_purchase'
    #     - Nếu không có NCC: hoàn thành luôn -> chuyển sang 'done'
    #     """
    #     self._process_after_incoming_done(check_done=True)

    # def button_done(self):
    #     """Hoàn thành (sau khi xuất trả NCC)"""
    #     self._process_after_outgoing_done(check_done=True)

    def button_reject(self):
        """Từ chối"""
        self.write({"state": "rejected"})

    def button_draft(self):
        """Đặt về nháp"""
        # for rec in self:
        #     # Xử lý xóa phiếu nhập/xuất nếu có thể
        #     pickings = rec.picking_in_id | rec.picking_out_id
        #     for picking in pickings:
        #         if picking.state not in ('done', 'cancel'):
        #             picking.action_cancel()
        #         if picking.state == 'cancel':
        #             picking.unlink()
        #     
        #     # Kiểm tra lại xem còn phiếu không
        #     if rec.picking_in_id.exists() or rec.picking_out_id.exists():
        #         raise UserError(_("Không thể đặt về nháp khi đã có phiếu kho (đã hoàn thành hoặc không thể xóa)."))
                 
        self.write({"state": "draft"})

    def _auto_start_processing(self, force=False):
        """Chỉ chuyển trạng thái sang Hoàn thành (Đã comment logic kho)"""
        for rec in self:
            if rec.state == "draft":
                rec.state = "done"

    def _process_after_incoming_done(self, check_done=False):
        pass
        # """Move workflow after incoming picking is done."""
        # for rec in self:
        #     if check_done and (not rec.picking_in_id or rec.picking_in_id.state != "done"):
        #         raise UserError(_("Phiếu nhập kho chưa hoàn thành."))
        #     if not rec.picking_in_id or rec.picking_in_id.state != "done":
        #         continue
        #     if rec.state not in ("draft", "return_sale", "return_purchase"):
        #         continue
        #     if rec.vendor_id and rec._has_vendor_return_lines():
        #         if not rec.picking_out_id:
        #             rec._create_outgoing_picking()
        #         rec.state = "return_purchase"
        #     else:
        #         rec.state = "done"

    def _process_after_outgoing_done(self, check_done=False):
        pass
        # """Move workflow to done after outgoing picking is done."""
        # for rec in self:
        #     if check_done and (not rec.picking_out_id or rec.picking_out_id.state != "done"):
        #         raise UserError(_("Phiếu xuất NCC chưa hoàn thành."))
        #     if not rec.picking_out_id or rec.picking_out_id.state != "done":
        #         continue
        #     if rec.state != "done":
        #         rec.state = "done"

    # ==================== Stock Picking Creation ====================
    def _create_incoming_picking(self):
        """Đã comment logic tạo phiếu nhập kho"""
        return False
        # """Tạo phiếu nhập kho từ Customer về Warehouse"""
        # self.ensure_one()
        # if self.picking_in_id:
        #     return self.picking_in_id
        # if not self.line_ids:
        #     raise UserError(_("Không có dòng sản phẩm để tạo phiếu nhập kho."))
        # if not self.warehouse_id:
        #     raise UserError(_("Không xác định được kho."))
        # 
        # picking_type = self.warehouse_id.in_type_id
        # if not picking_type:
        #     raise UserError(_("Không tìm thấy loại phiếu nhập kho."))
        # 
        # customer_location = self.env.ref("stock.stock_location_customers")
        # 
        # picking_vals = {
        #     "partner_id": self.partner_id.id,
        #     "picking_type_id": picking_type.id,
        #     "location_id": customer_location.id,
        #     "location_dest_id": self.warehouse_id.lot_stock_id.id,
        #     "origin": self.name,
        #     "move_type": "direct",
        # }
        # picking = self.env["stock.picking"].create(picking_vals)
        # 
        # # Tạo stock moves từ lines
        # for line in self.line_ids:
        #     self.env["stock.move"].create({
        #         "name": line.product_id.name,
        #         "product_id": line.product_id.id,
        #         "product_uom_qty": line.product_qty,
        #         "product_uom": line.product_uom_id.id,
        #         "picking_id": picking.id,
        #         "location_id": customer_location.id,
        #         "location_dest_id": self.warehouse_id.lot_stock_id.id,
        #     })
        # 
        # picking.action_confirm()
        # self.picking_in_id = picking
        # _logger.info("Đã tạo phiếu nhập kho %s cho đề nghị %s", picking.name, self.name)
        # return picking

    def _create_outgoing_picking(self):
        """Đã comment logic tạo phiếu xuất NCC"""
        return False
        # """Tạo phiếu xuất kho về NCC"""
        # self.ensure_one()
        # if self.picking_out_id:
        #     return self.picking_out_id
        # if not self.line_ids:
        #     raise UserError(_("Không có dòng sản phẩm để tạo phiếu xuất kho."))
        # if not self.warehouse_id or not self.vendor_id:
        #     return # Skip if no vendor or warehouse
        # if not self._has_vendor_return_lines():
        #     return False
        # 
        # picking_type = self.warehouse_id.out_type_id
        # if not picking_type:
        #     raise UserError(_("Không tìm thấy loại phiếu xuất kho."))
        # 
        # supplier_location = self.env.ref("stock.stock_location_suppliers")
        # 
        # picking_vals = {
        #     "partner_id": self.vendor_id.id,
        #     "picking_type_id": picking_type.id,
        #     "location_id": self.warehouse_id.lot_stock_id.id,
        #     "location_dest_id": supplier_location.id,
        #     "origin": self.name,
        #     "move_type": "direct",
        # }
        # picking = self.env["stock.picking"].create(picking_vals)
        # 
        # # Tạo stock moves từ lines có số lượng trả NCC
        # return_lines = self.line_ids.filtered(lambda l: (l.return_to_vendor_qty or 0.0) > 0)
        # for line in return_lines:
        #     self.env["stock.move"].create({
        #         "name": line.product_id.name,
        #         "product_id": line.product_id.id,
        #         "product_uom_qty": line.return_to_vendor_qty,
        #         "product_uom": line.product_uom_id.id,
        #         "picking_id": picking.id,
        #         "location_id": self.warehouse_id.lot_stock_id.id,
        #         "location_dest_id": supplier_location.id,
        #     })
        # 
        # picking.action_confirm()
        # self.picking_out_id = picking
        # _logger.info("Đã tạo phiếu xuất NCC %s cho đề nghị %s", picking.name, self.name)
        # return picking

    def _has_vendor_return_lines(self):
        self.ensure_one()
        return any((line.return_to_vendor_qty or 0.0) > 0 for line in self.line_ids)

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
            
            # --- SAFETY CHECK: Ensure we got the correct record ---
            found_code = record_data.get("ReturnSaleNo")
            if found_code != return_sale_code:
                msg = f"MISA API Filter failed: Requested '{return_sale_code}' but got '{found_code}'. Aborting sync."
                _logger.error(msg)
                return {"ok": False, "error": "api_filter_failed", "message": msg}
            # -----------------------------------------------------

            misa_id = record_data.get("ID")
            
            # Fetch detail
            return self._sync_from_misa_detail(misa_id, headers, record_data)
            
        except Exception as e:
            _logger.exception("Error syncing return sale %s", return_sale_code)
            return {"ok": False, "error": "exception", "message": str(e)}

    def _get_grid_payload_by_code(self, code):
        """Payload để tìm theo mã - Structure V2 Grid API"""
        return {
            "Columns": "SUQsUmV0dXJuU2FsZU5vLFJldHVyblNhbGVOYW1lLFJldHVyblNhbGVEYXRlLEFjY291bnRJRCxBY2NvdW50SURUZXh0LFNhbGVPcmRlcklELFNhbGVPcmRlcklEVGV4dCxUb3RhbFN1bW1hcnksU3VnZ2VzdFN0YXR1c0lELFN1Z2dlc3RTdGF0dXNJRFRleHQsT3duZXJJRCxPd25lcklEVGV4dA==",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 1,
            "Filters": [
                {
                    "Group": None,
                    "Addition": 1,
                    "InputType": 1,
                    "IsFromFormula": True,
                    "Operator": 1,  # Equal / Contains
                    "Property": "ReturnSaleNo",
                    "Text": code,
                    "Value": code
                }
            ],
            "Formula": "( 1 )",  # Use the first filter
            "LayoutCode": "ReturnSale",
            "DefaultTotal": False,
            "IsMappingData": False,
            "MappingValueObject": {},
            "SessionID": "864e2811-5edd-5ccc-6b85-178b59007e93",  # Random/Static SessionID
            "LayoutCodeCheckPermission": "ReturnSale",
            "AISearchKeyword": ""
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
        
        raw_data = result.get("Data", {})
        detail_data = raw_data.get("CurrentData", {})
        # Note: If CurrentData is null, detail_data will be {}
        if not detail_data and raw_data:
             # Fallback if structure is different
             detail_data = raw_data
        
        # Try to get lines from DetailData (FormDataNew)
        detail_lines = []
        full_detail = raw_data.get("DetailData", [])
        if full_detail:
            for d in full_detail:
                if d.get("TableName") == "return_sale_product":
                    detail_lines = d.get("Data", [])
                    break

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
            "return_reason": return_reason,
            "handling_method": handling_method,
            "delivery_address": billing_address,
            "misa_owner_text": owner_text,
        }
        
        line_data = []
        summary_data = None
        
        # 1. Preferred source: DataSubPaging (contains Price/ToCurrency/Total)
        lines_result = (existing or self)._fetch_lines_datasubpaging(misa_id, headers)
        line_data = lines_result.get("lines", [])
        summary_data = lines_result.get("summary")
        if line_data:
            _logger.info("✅ Using DataSubPaging lines for ReturnSale ID %s: %s lines", misa_id, len(line_data))

        # 2. Fallback to DetailData lines when DataSubPaging has no data
        if not line_data and detail_lines:
            has_line_price = any(
                (x.get("Price") is not None)
                or (x.get("UnitPrice") is not None)
                or (x.get("ToCurrency") is not None)
                or (x.get("AmountOC") is not None)
                or (x.get("Total") is not None)
                or (x.get("TotalAmount") is not None)
                for x in detail_lines
            )
            if has_line_price:
                line_data = detail_lines
                summary_data = {"Total": total_amount}
                _logger.info("⚠️ DataSubPaging empty, fallback to DetailData lines for ID %s: %s lines", misa_id, len(line_data))

        if existing:
            existing.write(vals)
            
            if line_data:
                existing._sync_lines_from_misa_data(line_data, summary_data)
            else:
                # Fallback
                _logger.warning("⚠️ No priced line data for ID %s, fallback by product_codes_text", misa_id)
                existing._sync_lines_from_misa(product_codes_text, detail_data)
                existing._set_total_from_summary({"Total": total_amount})

            if existing.state == "draft":
                existing._auto_start_processing()
                
            return {"ok": True, "action": "updated", "res_id": existing.id, "name": existing.name}
        else:
            vals["state"] = "draft"
            new_record = self.create(vals)
            
            if line_data:
                new_record._sync_lines_from_misa_data(line_data, summary_data)
            else:
                # Fallback
                _logger.warning("⚠️ No priced line data for ID %s, fallback by product_codes_text", misa_id)
                new_record._sync_lines_from_misa(product_codes_text, detail_data)
                new_record._set_total_from_summary({"Total": total_amount})

            new_record._auto_start_processing()
                
            return {"ok": True, "action": "created", "res_id": new_record.id, "name": new_record.name}

    def _set_total_from_summary(self, summary_data):
        """Store SummaryData total as source for total_amount compute."""
        self.ensure_one()
        if not summary_data:
            self.write({
                "use_misa_summary_total": False,
                "misa_summary_total": 0.0,
            })
            return

        raw_total = summary_data.get("Total")
        if raw_total is None:
            raw_total = summary_data.get("TotalSummary")

        if raw_total is None:
            self.write({
                "use_misa_summary_total": False,
                "misa_summary_total": 0.0,
            })
            return

        try:
            summary_total = float(raw_total or 0.0)
        except Exception:
            summary_total = 0.0

        self.write({
            "use_misa_summary_total": True,
            "misa_summary_total": summary_total,
        })

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
                # Fallback không còn chia đều giá từ tổng đơn để tránh sai dữ liệu line.
                qty = 1.0
                price = product.lst_price or 0.0
                
                self.env["return.sale.request.line"].create({
                    "request_id": self.id,
                    "product_id": product.id,
                    "product_qty": qty,
                    "return_to_vendor_qty": 0.0,
                    "unit_price": price,
                    "subtotal": qty * price,
                    "line_total": qty * price,
                })
                _logger.info("📦 Fallback line: %s x%.2f @ %.2f", code, qty, price)

    def _sync_lines_from_misa_data(self, line_data, summary_data=None):
        """Sync lines từ dữ liệu chi tiết MISA (DataSubPaging) với qty và price
        
        Args:
            line_data: list of dicts từ DataSubPaging API, mỗi dict chứa:
                - ProductIDText: mã sản phẩm
                - Amount: số lượng
                - CustomField1: số lượng trả NCC
                - Price: đơn giá (trước thuế)
                - ToCurrency: thành tiền (trước thuế)
                - Total: tổng tiền (sau thuế)
                - UnitIDText: tên đơn vị
                - Description: mô tả
            summary_data: dict từ SummaryData[0] chứa Total cho tổng đơn
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
                if x is None:
                    return dv
                if isinstance(x, str):
                    val = x.replace(",", "").strip()
                    if val == "":
                        return dv
                    return float(val)
                return float(x)
            except Exception:
                return dv
        
        import logging
        _logger = logging.getLogger(__name__)
        
        for line in line_data:
            code = str(line.get("ProductIDText") or "").strip()
            if not code:
                continue
                
            # Parse data from API
            qty = _flt(line.get("Quantity") or line.get("Amount"), 1.0)
            return_to_vendor_qty = _flt(line.get("CustomField1"), 0.0)
            unit_price = _flt(line.get("Price") or line.get("UnitPrice"), 0.0)
            subtotal = _flt(line.get("ToCurrency") or line.get("AmountOC"), 0.0)
            line_total = _flt(line.get("Total") or line.get("TotalAmount"), 0.0)
            tax_amount = _flt(line.get("Tax"), 0.0)
            uom_name = (line.get("UnitIDText") or "Cái").strip()
            
            # Fallback subtotal if not provided
            if not subtotal and unit_price and qty:
                subtotal = qty * unit_price
            
            # Fallback line_total if not provided
            if not line_total:
                line_total = subtotal + tax_amount if tax_amount else subtotal
            
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
                    "return_to_vendor_qty": max(return_to_vendor_qty, 0.0),
                    "unit_price": unit_price,
                    "subtotal": subtotal,
                    "line_total": line_total,
                })
                _logger.info("📦 Created line: %s x%.2f @ %.2f | subtotal=%.2f | line_total=%.2f", 
                            code, qty, unit_price, subtotal, line_total)

        # Cập nhật tổng đơn từ SummaryData
        self._set_total_from_summary(summary_data)

    def _fetch_lines_datasubpaging(self, misa_id, headers):
        """Fetch chi tiết sản phẩm từ DataSubPaging API
        
        Returns dict: {
            "lines": [{ProductIDText, Amount, Price, ToCurrency, Total, UnitIDText, ...}, ...],
            "summary": {Total, TotalSummary, ...} or None
        }
        """
        try:
            import requests
            import uuid
            url = "https://amisapp.misa.vn/crm/g2/api/business/ReturnSale/DataSubPaging"
            
            # Dùng payload theo cấu trúc thực tế đang hoạt động trên MISA.
            # SessionID cần định dạng GUID, nếu không MISA có thể trả 500.
            session_id = str(uuid.uuid4())

            base_payload = {
                "Columns": "SUQsU29ydE9yZGVyLFByb2R1Y3RJRCxQcm9kdWN0SURUZXh0LERlc2NyaXB0aW9uLFVuaXRJRCxVbml0SURUZXh0LFN0b2NrSUQsU3RvY2tJRFRleHQsQW1vdW50LEN1c3RvbUZpZWxkMSxQcmljZUFmdGVyVGF4LFByaWNlLFRvQ3VycmVuY3ksRGlzY291bnRQZXJjZW50LERpc2NvdW50LFRheFBlcmNlbnRJRCxUYXhQZXJjZW50SURUZXh0LFRheCxUb3RhbCxTYWxlT3JkZXJJRCxTYWxlT3JkZXJJRFRleHQsSXNQcm9tb3Rpb24sUHJvbW90aW9uSUQsUHJvbW90aW9uSURUZXh0LElzU2V0UHJvZHVjdCxJc0NoaWxkUHJvZHVjdA==",
                "Sorts": [],
                "Start": 0,
                "Page": 1,
                "PageSize": 20,
                "Filters": [],
                "DefaultTotal": False,
                "IsMappingData": False,
                "MappingValueObject": {
                    "MasterID": str(misa_id),
                    "TableName": "return_sale_product",
                    "MasterKey": "CustomID",
                    "SumColumn": ""
                },
                "IsApproved": False,
                "CustomPagingData": {
                    "SubFormConfig": {
                        "ColumnFieldSubForm": "",
                        "ColumnAggregateSubForm": "AmountSummary,ToCurrencySummary,DiscountSummary,TaxSummary,TotalSummary,DiscountOverall,DiscountOverallOC,TaxOverall,TaxOverallOC,TotalOverall,TotalOverallOC,IsDiscountDirectlyOverall,DiscountPercentOverall,TaxPercentOverallID,ToCurrencyAfterDiscountSummary,DiscountAfterTaxSummary,ToCurrencyOCAfterDiscountSummary,TotalSummaryOC,TaxSummaryOC,DiscountSummaryOC,ToCurrencySummaryOC,UsageUnitAmountSummary,PromotionOverAllID,IsPromotionDiscountOverAll",
                        "TableName": "return_sale_product",
                        "IsSystem": True,
                        "ParentIDKey": "CustomID",
                        "IsBringSerialType": False,
                        "AggregateField": []
                    }
                },
                "IsUsedELTS": True,
                "ListGmailPage": [],
                "ListFacebookPage": {},
                "IsListPaging": True,
                "IsGetCache": True,
                "IsCheckInactive": False,
                "IsConverted": False,
                "SessionID": session_id,
                "AISearchKeyword": ""
            }

            _logger.info("📡 Fetching lines (Model) for ID %s", misa_id)

            all_lines = []
            summary = None
            page = 1
            page_size = int(base_payload["PageSize"])

            while True:
                payload = dict(base_payload)
                payload["Page"] = page
                payload["Start"] = (page - 1) * page_size

                response = requests.post(url, headers=headers, json=payload, timeout=60)

                if response.status_code != 200:
                    body = (response.text or "")[:500]
                    _logger.warning(
                        "Lines API failed for ID %s page %s: HTTP %s | body=%s",
                        misa_id,
                        page,
                        response.status_code,
                        body,
                    )
                    return {"lines": [], "summary": None}

                result = response.json()

                if not result.get("Success"):
                    # Retry 1 lần với cấu hình cache khác để giảm khả năng lỗi nội bộ phía MISA.
                    error_code = result.get("Code")
                    if page == 1 and error_code == 500:
                        retry_payload = dict(payload)
                        retry_payload["IsGetCache"] = False
                        retry_payload["SessionID"] = str(uuid.uuid4())
                        retry_resp = requests.post(url, headers=headers, json=retry_payload, timeout=60)
                        if retry_resp.status_code == 200:
                            retry_result = retry_resp.json()
                            if retry_result.get("Success"):
                                result = retry_result
                            else:
                                _logger.warning(
                                    "Lines API retry still failed for ID %s: %s",
                                    misa_id,
                                    retry_result,
                                )
                                return {"lines": [], "summary": None}
                        else:
                            _logger.warning(
                                "Lines API retry HTTP failed for ID %s: %s",
                                misa_id,
                                retry_resp.status_code,
                            )
                            return {"lines": [], "summary": None}
                    else:
                        _logger.warning(
                            "Lines API Success=False for ID %s page %s: %s",
                            misa_id,
                            page,
                            result,
                        )
                        return {"lines": [], "summary": None}

                page_lines = result.get("Data", []) or []
                all_lines.extend(page_lines)

                summary_data = result.get("SummaryData", [])
                if summary_data and summary is None:
                    summary = summary_data[0]

                total_rows = int(result.get("Total") or 0)
                if not page_lines:
                    break
                if len(page_lines) < page_size:
                    break
                if total_rows and len(all_lines) >= total_rows:
                    break

                page += 1

            _logger.info("📥 Found %d lines for ID %s", len(all_lines), misa_id)
            return {"lines": all_lines, "summary": summary}
            
        except Exception as e:
            _logger.warning("Error fetching lines for ID %s: %s", misa_id, e)
            return {"lines": [], "summary": None}
