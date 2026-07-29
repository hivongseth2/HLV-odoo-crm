# -*- coding: utf-8 -*-

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import (
    ProductMergeBlockerMixin,
    ProductMergeChatterMixin,
    ProductMergeStockMixin,
)


class HlvProductMergeWizard(
    ProductMergeBlockerMixin,
    ProductMergeStockMixin,
    ProductMergeChatterMixin,
    models.TransientModel,
):
    _name = "hlv.product.merge.wizard"
    _description = "Gộp hai sản phẩm"

    base_product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm gốc (giữ lại)",
        required=True,
        domain="[('active', '=', True), ('id', '!=', source_product_id)]",
    )
    source_product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm được gộp (sẽ lưu trữ)",
        required=True,
        domain="[('active', '=', True), ('id', '!=', base_product_id)]",
    )
    base_uom_id = fields.Many2one(
        "uom.uom",
        string="ĐVT sản phẩm gốc",
        related="base_product_id.uom_id",
        readonly=True,
    )
    source_uom_id = fields.Many2one(
        "uom.uom",
        string="ĐVT sản phẩm được gộp",
        related="source_product_id.uom_id",
        readonly=True,
    )
    is_uom_different = fields.Boolean(
        string="Khác đơn vị tính",
        compute="_compute_is_uom_different",
    )
    line_ids = fields.One2many(
        "hlv.product.merge.wizard.line",
        "wizard_id",
        string="Tồn kho sẽ chuyển",
    )
    blocker_text = fields.Text(
        string="Chứng từ đang chặn",
        compute="_compute_blocker_text",
    )
    note = fields.Text(string="Ghi chú")
    confirm = fields.Boolean(
        string="Tôi xác nhận chuyển tồn và lưu trữ sản phẩm được gộp",
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        base_product = self.env["product.product"].browse(
            values.get("base_product_id")
        ).exists()
        source_product = self.env["product.product"].browse(
            values.get("source_product_id")
        ).exists()
        if (
            "line_ids" in field_names
            and base_product
            and source_product
            and base_product != source_product
        ):
            values["line_ids"] = [
                Command.create(self._quant_line_values(quants))
                for quants in self._source_quant_groups(source_product)
            ]
        return values

    @api.depends("base_product_id", "source_product_id")
    def _compute_is_uom_different(self):
        for wizard in self:
            wizard.is_uom_different = bool(
                wizard.base_product_id
                and wizard.source_product_id
                and wizard.base_product_id.uom_id != wizard.source_product_id.uom_id
            )

    @api.depends("source_product_id")
    def _compute_blocker_text(self):
        for wizard in self:
            blockers = (
                wizard._get_merge_blockers(wizard.source_product_id)
                if wizard.source_product_id
                else []
            )
            wizard.blocker_text = "\n".join(blockers)

    @api.onchange("base_product_id", "source_product_id")
    def _onchange_products(self):
        for wizard in self:
            commands = [Command.clear()]
            if (
                wizard.base_product_id
                and wizard.source_product_id
                and wizard.base_product_id != wizard.source_product_id
            ):
                commands.extend(
                    Command.create(wizard._quant_line_values(quants))
                    for quants in wizard._source_quant_groups(wizard.source_product_id)
                )
            wizard.line_ids = commands

    def _validate_products(self):
        self.ensure_one()
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError(_("Chỉ Quản lý kho mới được phép gộp sản phẩm."))
        if not self.base_product_id or not self.source_product_id:
            raise UserError(_("Phải chọn đủ sản phẩm gốc và sản phẩm được gộp."))
        if self.base_product_id == self.source_product_id:
            raise UserError(_("Hai sản phẩm gộp phải khác nhau."))
        if not self.base_product_id.active or not self.source_product_id.active:
            raise UserError(_("Chỉ được gộp hai sản phẩm đang hoạt động."))
        if self.source_product_id.hlv_merged_into_product_id:
            raise UserError(_("Sản phẩm nguồn đã được gộp trước đó."))
        base_company = self.base_product_id.company_id
        source_company = self.source_product_id.company_id
        if base_company and source_company and base_company != source_company:
            raise UserError(_("Không thể gộp hai sản phẩm thuộc hai công ty khác nhau."))
        self._validate_company_scope()

    def action_confirm_merge(self):
        self.ensure_one()
        self._validate_products()
        if not self.confirm:
            raise UserError(_("Bạn phải xác nhận trước khi gộp sản phẩm."))
        blockers = self._get_merge_blockers(self.source_product_id)
        if blockers:
            raise UserError(_(
                "Không thể gộp vì sản phẩm nguồn còn chứng từ cần xử lý:\n%s"
            ) % "\n".join(blockers))
        self._validate_quant_snapshot()
        self._validate_target_quantities()

        details = self._transfer_quants()
        self._archive_source()
        self._post_chatter_logs(details)
        return {
            "type": "ir.actions.act_window",
            "name": _("Sản phẩm sau khi gộp"),
            "res_model": "product.product",
            "res_id": self.base_product_id.id,
            "view_mode": "form",
            "target": "current",
        }


class HlvProductMergeWizardLine(models.TransientModel):
    _name = "hlv.product.merge.wizard.line"
    _description = "Dòng tồn kho gộp sản phẩm"
    _order = "location_id, lot_id, id"

    wizard_id = fields.Many2one(
        "hlv.product.merge.wizard",
        required=True,
        ondelete="cascade",
    )
    quant_ids = fields.Many2many(
        "stock.quant",
        string="Các dòng tồn gốc",
        readonly=True,
    )
    quant_count = fields.Integer(string="Số dòng gốc", readonly=True)
    location_id = fields.Many2one(
        "stock.location",
        string="Vị trí",
        required=True,
        readonly=True,
    )
    lot_id = fields.Many2one("stock.lot", string="Lô/Serial", readonly=True)
    company_id = fields.Many2one("res.company", string="Công ty", readonly=True)
    source_quantity = fields.Float(
        string="Tồn nguồn",
        digits="Product Unit of Measure",
        readonly=True,
    )
    source_uom_id = fields.Many2one(
        "uom.uom",
        string="ĐVT nguồn",
        related="wizard_id.source_uom_id",
        readonly=True,
    )
    target_quantity = fields.Float(
        string="SL sau quy đổi",
        digits="Product Unit of Measure",
    )
    target_uom_id = fields.Many2one(
        "uom.uom",
        string="ĐVT sản phẩm gốc",
        related="wizard_id.base_uom_id",
        readonly=True,
    )
