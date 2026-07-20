# Copyright 2018-2019 ForgeFlow, S.L.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from datetime import datetime

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import get_lang


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _name = "purchase.request.line.make.purchase.order"
    _description = "Tạo đơn mua hàng từ chi tiết yêu cầu mua hàng"

    hlv_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Sản phẩm yêu cầu",
        compute="_compute_hlv_product_ids",
    )
    supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Nhà cung cấp chung",
        context={
            "res_partner_search_mode": "supplier",
            "hlv_prioritize_company": True,
            "hlv_product_ids": "hlv_product_ids",
        },
        domain=[
            ("type", "!=", "delivery"),
            ("is_company", "=", True),
            ("active", "=", True),
            "|",
            ("hlv_business_role", "=", "supplier"),
            ("supplier_rank", ">", 0),
        ],
        help="Nếu chọn, sẽ được áp dụng cho tất cả các dòng bên dưới.",
    )
    item_ids = fields.One2many(
        comodel_name="purchase.request.line.make.purchase.order.item",
        inverse_name="wiz_id",
        string="Mục",
    )
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Đơn mua hàng",
        domain=[("state", "=", "draft")],
    )
    sync_data_planned = fields.Boolean(
        string="Chỉ gộp nếu trùng Ngày dự kiến",
        help=(
            "Nếu chọn, hệ thống chỉ cộng dồn số lượng vào mặt hàng đã có sẵn trong đơn mua hàng "
            "nếu trùng cả Ngày dự kiến nhận hàng. Nếu khác ngày, hệ thống sẽ tách thành một dòng riêng."
        ),
    )

    @api.depends("item_ids.product_id")
    def _compute_hlv_product_ids(self):
        for rec in self:
            rec.hlv_product_ids = rec.item_ids.mapped("product_id")

    @api.onchange("supplier_id")
    def _onchange_supplier_id(self):
        if self.supplier_id:
            for item in self.item_ids:
                item.supplier_id = self.supplier_id

    @api.model
    def _prepare_item(self, line):
        return {
            "line_id": line.id,
            "request_id": line.request_id.id,
            "product_id": line.product_id.id,
            "name": line.name or line.product_id.name,
            "product_qty": line.pending_qty_to_receive,
            "product_uom_id": line.product_uom_id.id,
            "estimated_cost": line.estimated_cost,
            "supplier_id": line.supplier_id.id,
        }

    @api.model
    def _check_valid_request_line(self, request_line_ids):
        picking_type = False
        company_id = False

        for line in self.env["purchase.request.line"].browse(request_line_ids):
            if line.request_id.state == "done":
                raise UserError(_("Việc mua hàng đã hoàn thành."))
            if line.request_id.state not in ["approved", "in_progress"]:
                raise UserError(
                    _("Yêu cầu mua hàng %s không được phê duyệt hoặc đang thực hiện")
                    % line.request_id.name
                )

            if line.purchase_state == "done":
                raise UserError(_("Việc mua hàng đã hoàn thành."))

            line_company_id = line.company_id and line.company_id.id or False
            if company_id is not False and line_company_id != company_id:
                raise UserError(_("Bạn phải chọn các dòng từ cùng một công ty."))
            else:
                company_id = line_company_id

            line_picking_type = line.request_id.picking_type_id or False
            if not line_picking_type:
                raise UserError(_("Bạn phải nhập một Loại lấy hàng."))
            if picking_type is not False and line_picking_type != picking_type:
                raise UserError(
                    _("Bạn phải chọn các dòng từ cùng một Loại lấy hàng.")
                )
            else:
                picking_type = line_picking_type

    @api.model
    def check_group(self, request_lines):
        if len(list(set(request_lines.mapped("request_id.group_id")))) > 1:
            raise UserError(
                _(
                    "Bạn không thể tạo một đơn mua hàng duy nhất từ "
                    "các yêu cầu mua hàng có nhóm cung ứng khác nhau."
                )
            )

    @api.model
    def get_items(self, request_line_ids):
        request_line_obj = self.env["purchase.request.line"]
        items = []
        request_lines = request_line_obj.browse(request_line_ids)
        self._check_valid_request_line(request_line_ids)
        self.check_group(request_lines)
        for line in request_lines:
            if line.pending_qty_to_receive > 0:
                items.append([0, 0, self._prepare_item(line)])
        return items

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        active_model = self.env.context.get("active_model", False)
        request_line_ids = []
        if active_model == "purchase.request.line":
            request_line_ids += self.env.context.get("active_ids", [])
        elif active_model == "purchase.request":
            request_ids = self.env.context.get("active_ids", False)
            request_line_ids += (
                self.env[active_model].browse(request_ids).mapped("line_ids.id")
            )
        if not request_line_ids:
            return res
        res["item_ids"] = self.get_items(request_line_ids)
        request_lines = self.env["purchase.request.line"].browse(request_line_ids)
        supplier_ids = request_lines.mapped("supplier_id").ids
        if len(supplier_ids) == 1 and supplier_ids[0]:
            res["supplier_id"] = supplier_ids[0]
        return res

    @api.model
    def _prepare_purchase_order(self, picking_type, group_id, company, origin, supplier):
        if not supplier:
            raise UserError(_("Nhập một nhà cung cấp."))
        data = {
            "origin": origin,
            "partner_id": supplier.id,
            "payment_term_id": supplier.property_supplier_payment_term_id.id,
            "fiscal_position_id": supplier.property_account_position_id
            and supplier.property_account_position_id.id
            or False,
            "picking_type_id": picking_type.id,
            "company_id": company.id,
            "group_id": group_id.id,
        }
        return data

    def create_allocation(self, po_line, pr_line, new_qty, alloc_uom):
        vals = {
            "requested_product_uom_qty": new_qty,
            "product_uom_id": alloc_uom.id,
            "purchase_request_line_id": pr_line.id,
            "purchase_line_id": po_line.id,
        }
        return self.env["purchase.request.allocation"].create(vals)

    def _get_date_with_user_tz(self, date):
        user_tz = pytz.timezone(self.env.user.tz or "UTC")
        return (
            user_tz.localize(datetime(date.year, date.month, date.day))
            .astimezone(pytz.utc)
            .replace(tzinfo=None)
        )

    @api.model
    def _prepare_purchase_order_line(self, po, item):
        if not item.product_id:
            raise UserError(_("Vui lòng chọn một sản phẩm cho tất cả các dòng"))
        product = item.product_id

        # Keep the standard product UOM for purchase order so we should
        # convert the product quantity to this UOM
        qty = item.product_uom_id._compute_quantity(
            item.product_qty, product.uom_po_id or product.uom_id
        )
        # Suggest the supplier min qty as it's done in Odoo core
        min_qty = item.line_id._get_supplier_min_qty(product, po.partner_id)
        qty = max(qty, min_qty)
        date_required = item.line_id.date_required
        return {
            "order_id": po.id,
            "product_id": product.id,
            "product_uom": product.uom_po_id.id or product.uom_id.id,
            "product_qty": qty,
            "analytic_distribution": item.line_id.analytic_distribution,
            "purchase_request_lines": [(4, item.line_id.id)],
            "date_planned": self._get_date_with_user_tz(date_required),
            "move_dest_ids": [(4, x.id) for x in item.line_id.move_dest_ids],
        }

    @api.model
    def _get_purchase_line_name(self, order, line):
        """Fetch the product name as per supplier settings"""
        supplier = line.supplier_id or order.partner_id
        product_lang = line.product_id.with_context(
            lang=get_lang(self.env, supplier.lang).code,
            partner_id=supplier.id,
            company_id=order.company_id.id,
        )
        name = product_lang.display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        return name

    @api.model
    def _get_order_line_search_domain(self, order, item):
        vals = self._prepare_purchase_order_line(order, item)
        name = self._get_purchase_line_name(order, item)
        order_line_data = [
            ("order_id", "=", order.id),
            ("name", "=", name),
            ("product_id", "=", item.product_id.id),
            ("product_uom", "=", vals["product_uom"]),
        ]

        if item.line_id.analytic_distribution:
            analytic_account_ids = list(item.line_id.analytic_distribution.keys())
            order_line_data.append(
                ("analytic_distribution", "in", analytic_account_ids)
            )
        else:
            order_line_data.append(("analytic_distribution", "=", False))

        if self.sync_data_planned:
            date_required = item.line_id.date_required
            order_line_data += [
                ("date_planned", "=", self._get_date_with_user_tz(date_required))
            ]
        if not item.product_id:
            order_line_data.append(("name", "=", item.name))
        return order_line_data

    def make_purchase_order(self):
        res = []
        purchase_obj = self.env["purchase.order"]
        po_line_obj = self.env["purchase.order.line"]

        # If header supplier is set, override all item suppliers
        if self.supplier_id:
            for item in self.item_ids:
                item.supplier_id = self.supplier_id

        # Group items by supplier to create multiple POs if needed
        items_by_supplier = {}
        for item in self.item_ids:
            if not item.supplier_id:
                raise UserError(_("Vui lòng chọn nhà cung cấp cho sản phẩm %s.") % item.product_id.display_name)
            if item.supplier_id not in items_by_supplier:
                items_by_supplier[item.supplier_id] = []
            items_by_supplier[item.supplier_id].append(item)

        for supplier, items in items_by_supplier.items():
            purchase = False
            # Only use the header purchase_order_id if the partner matches
            if self.purchase_order_id and self.purchase_order_id.partner_id == supplier:
                purchase = self.purchase_order_id
            
            for item in items:
                line = item.line_id
                if item.product_qty <= 0.0:
                    raise UserError(_("Nhập một số lượng dương."))
                if not purchase:
                    po_data = self._prepare_purchase_order(
                        line.request_id.picking_type_id,
                        line.request_id.group_id,
                        line.company_id,
                        line.origin,
                        supplier,
                    )
                    purchase = purchase_obj.create(po_data)

            # Look for any other PO line in the selected PO with same
                # product and UoM to sum quantities instead of creating a new
                # po line
                domain = self._get_order_line_search_domain(purchase, item)
                available_po_lines = po_line_obj.search(domain)
                new_pr_line = True
                # If Unit of Measure is not set, update from wizard.
                if not line.product_uom_id:
                    line.product_uom_id = item.product_uom_id
                # Allocation UoM has to be the same as PR line UoM
                alloc_uom = line.product_uom_id
                wizard_uom = item.product_uom_id
                if (
                    available_po_lines
                    and not item.keep_description
                    and not item.keep_estimated_cost
                ):
                    new_pr_line = False
                    po_line = available_po_lines[0]
                    po_line.purchase_request_lines = [(4, line.id)]
                    po_line.move_dest_ids |= line.move_dest_ids
                    po_line_product_uom_qty = po_line.product_uom._compute_quantity(
                        po_line.product_uom_qty, alloc_uom
                    )
                    wizard_product_uom_qty = wizard_uom._compute_quantity(
                        item.product_qty, alloc_uom
                    )
                    all_qty = min(po_line_product_uom_qty, wizard_product_uom_qty)
                    self.create_allocation(po_line, line, all_qty, alloc_uom)
                else:
                    po_line_data = self._prepare_purchase_order_line(purchase, item)
                    if item.keep_description:
                        po_line_data["name"] = item.name
                    po_line = po_line_obj.create(po_line_data)
                    po_line_product_uom_qty = po_line.product_uom._compute_quantity(
                        po_line.product_uom_qty, alloc_uom
                    )
                    wizard_product_uom_qty = wizard_uom._compute_quantity(
                        item.product_qty, alloc_uom
                    )
                    all_qty = min(po_line_product_uom_qty, wizard_product_uom_qty)
                    self.create_allocation(po_line, line, all_qty, alloc_uom)
                self._post_process_po_line(item, po_line, new_pr_line)
            if purchase.id not in res:
                res.append(purchase.id)

        # purchase_requests = self.item_ids.mapped("request_id")
        # purchase_requests.sudo().button_done()
        return {
            "domain": [("id", "in", res)],
            "name": _("Yêu cầu báo giá"),
            "view_mode": "list,form",
            "res_model": "purchase.order",
            "view_id": False,
            "context": False,
            "type": "ir.actions.act_window",
        }

    def _post_process_po_line(self, item, po_line, new_pr_line):
        self.ensure_one()
        line = item.line_id
        user_tz = pytz.timezone(self.env.user.tz or "UTC")
        # TODO: Check propagate_uom compatibility:
        price_unit = item.estimated_cost / item.product_qty
        new_qty = self.env["purchase.request.line"]._calc_new_qty(
            line, po_line=po_line, new_pr_line=new_pr_line
        )
        po_line.product_qty = new_qty
        if item.keep_estimated_cost:
            po_line.price_unit = price_unit
            po_line._compute_amount()
        # The quantity update triggers a compute method that alters the
        # unit price (which is what we want, to honor graduate pricing)
        # but also the scheduled date which is what we don't want.
        date_required = line.date_required
        # we enforce to save the datetime value in the current tz of the user
        po_line.date_planned = (
            user_tz.localize(
                datetime(date_required.year, date_required.month, date_required.day)
            )
            .astimezone(pytz.utc)
            .replace(tzinfo=None)
        )


class PurchaseRequestLineMakePurchaseOrderItem(models.TransientModel):
    _name = "purchase.request.line.make.purchase.order.item"
    _description = "Mục tạo đơn mua hàng từ chi tiết yêu cầu mua hàng"

    wiz_id = fields.Many2one(
        comodel_name="purchase.request.line.make.purchase.order",
        string="Trình thuật sĩ",
        required=True,
        ondelete="cascade",
        readonly=True,
    )
    line_id = fields.Many2one(
        comodel_name="purchase.request.line", string="Dòng yêu cầu mua hàng"
    )
    request_id = fields.Many2one(
        comodel_name="purchase.request",
        related="line_id.request_id",
        string="Yêu cầu mua hàng",
        readonly=False,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Sản phẩm",
        related="line_id.product_id",
        readonly=False,
    )
    supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Nhà cung cấp",
        context={
            "res_partner_search_mode": "supplier",
            "hlv_prioritize_company": True,
            "default_is_company": True,
        },
        domain=[
            ("is_company", "=", True),
            ("active", "=", True),
            "|",
            ("hlv_business_role", "=", "supplier"),
            ("supplier_rank", ">", 0),
        ],
        required=True,
    )
    name = fields.Char(string="Mô tả", required=True)
    product_qty = fields.Float(
        string="Số lượng cần mua", digits="Product Unit of Measure"
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom", string="ĐVT", required=True
    )
    estimated_cost = fields.Monetary(string="Chi phí ước tính", currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", string="Tiền tệ", related="line_id.currency_id", readonly=True
    )
    keep_description = fields.Boolean(
        string="Lấy mô tả từ Yêu cầu (Tạo dòng riêng)",
        help=(
            "Nếu chọn, hệ thống sẽ giữ nguyên nội dung mô tả chi tiết từ yêu cầu này sang "
            "đơn mua hàng và luôn tạo thành một dòng riêng (không cộng dồn với các mặt hàng khác)."
        ),
    )
    keep_estimated_cost = fields.Boolean(
        string="Lấy giá dự trù làm giá mua (Tạo dòng riêng)",
        help=(
            "Nếu chọn, hệ thống sẽ lấy giá bạn đã dự trù để làm giá mua chính thức và "
            "luôn tạo thành một dòng riêng (không cộng dồn với các mặt hàng khác)."
        ),
    )

    @api.onchange("product_id", "supplier_id")
    def onchange_product_id(self):
        if self.product_id:
            if not self.keep_description:
                name = self.product_id.name
            code = self.product_id.code
            supplier = self.supplier_id or self.wiz_id.supplier_id
            domain = [
                "|",
                ("product_id", "=", self.product_id.id),
                ("product_tmpl_id", "=", self.product_id.product_tmpl_id.id),
            ]
            if supplier:
                domain.append(("partner_id", "=", supplier.id))
            sup_info_id = self.env["product.supplierinfo"].search(domain)
            if sup_info_id:
                p_code = sup_info_id[0].product_code
                p_name = sup_info_id[0].product_name
                name = f"[{p_code if p_code else code}] {p_name if p_name else name}"
            else:
                if code:
                    name = f"[{code}] {self.name if self.keep_description else name}"
            if self.product_id.description_purchase and not self.keep_description:
                name += "\n" + self.product_id.description_purchase
            self.product_uom_id = self.product_id.uom_id.id
            if name:
                self.name = name
