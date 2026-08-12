# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class ProductProduct(models.Model):
    _inherit = "product.product"

    hlv_merged_into_product_id = fields.Many2one(
        "product.product",
        string="Đã gộp vào sản phẩm",
        readonly=True,
        copy=False,
        index=True,
    )
    hlv_merged_at = fields.Datetime(
        string="Thời điểm gộp",
        readonly=True,
        copy=False,
    )
    hlv_merged_by_id = fields.Many2one(
        "res.users",
        string="Người gộp",
        readonly=True,
        copy=False,
    )
    hlv_merge_note = fields.Text(
        string="Ghi chú gộp",
        readonly=True,
        copy=False,
    )

    def action_open_hlv_product_merge_wizard(self):
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError(_("Chỉ Quản lý kho mới được phép gộp sản phẩm."))
        if not self:
            raise UserError(_("Hãy chọn một hoặc hai sản phẩm để gộp."))
        if len(self) > 2:
            raise UserError(_("Mỗi lần chỉ được gộp hai sản phẩm."))

        products = self.with_context(active_test=False)
        base_product = products[0]
        source_product = products[1] if len(products) == 2 else self.env["product.product"]
        context = dict(self.env.context)
        context.update({
            "default_base_product_id": base_product.id,
            "default_source_product_id": source_product.id or False,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Gộp sản phẩm"),
            "res_model": "hlv.product.merge.wizard",
            "view_mode": "form",
            "target": "new",
            "context": context,
        }


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_open_hlv_product_merge_wizard(self):
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError(_("Chỉ Quản lý kho mới được phép gộp sản phẩm."))
        if not self:
            raise UserError(_("Hãy chọn một hoặc hai sản phẩm để gộp."))
        if len(self) > 2:
            raise UserError(_("Mỗi lần chỉ được gộp hai sản phẩm."))

        variants = self.mapped("product_variant_ids")
        if any(len(template.product_variant_ids) != 1 for template in self):
            raise UserError(_(
                "Không thể mở chức năng từ mẫu sản phẩm có nhiều biến thể. "
                "Hãy thực hiện từ danh sách Biến thể sản phẩm."
            ))
        return variants.action_open_hlv_product_merge_wizard()
