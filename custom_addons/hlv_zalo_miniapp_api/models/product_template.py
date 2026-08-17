# -*- coding: utf-8 -*-
import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)

# Các trường trên product.template ảnh hưởng đến dữ liệu hiển thị trên Zalo Mini App
_ZALO_SENSITIVE_TMPL_FIELDS = {
    "name",
    "x_zalo_price",
    "x_active_zalo",
    "x_zalo_categ_ids",
    "pos_categ_ids",
    "active",
    "sale_ok",
    "list_price",
    "image_1920",
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_zalo_price = fields.Float(
        string="Giá Zalo App",
        digits="Product Price",
        help="Giá hiển thị trên Zalo Mini App",
    )
    x_active_zalo = fields.Boolean(
        string="Hiển thị trên Zalo",
        default=False,
        help="Chỉ sản phẩm có flag này = True mới xuất hiện trên Zalo Mini App",
    )
    x_zalo_categ_ids = fields.Many2many(
        "pos.category",
        relation="product_template_x_zalo_categ_ids_rel",
        column1="product_template_id",
        column2="pos_category_id",
        string="Danh mục Zalo",
        help="Danh mục sản phẩm hiển thị trên Zalo Mini App (kế thừa từ POS category)",
    )

    def _is_zalo_relevant_write(self, vals):
        """Kiểm tra xem các giá trị sắp được write có ảnh hưởng đến Zalo không."""
        if any(f in vals for f in _ZALO_SENSITIVE_TMPL_FIELDS):
            return True
        return False

    def write(self, vals):
        res = super().write(vals)
        if self._is_zalo_relevant_write(vals):
            for record in self:
                # Bump nếu sản phẩm đang active Zalo HOẶC đang được set active Zalo
                if record.x_active_zalo or vals.get("x_active_zalo"):
                    try:
                        self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                            self.env,
                            trigger_source="auto_prod",
                            affected_model="product.template",
                            affected_record_name=record.display_name,
                            trigger_reason=f"Sửa template sản phẩm: {record.display_name}",
                        )
                        break  # Chỉ bump 1 lần cho cả batch
                    except Exception as e:
                        _logger.warning("[VersionBump] Failed to bump catalog version: %s", e)
        return res

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if record.x_active_zalo:
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_prod",
                    affected_model="product.template",
                    affected_record_name=record.display_name,
                    trigger_reason=f"Tạo mới sản phẩm Zalo: {record.display_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version on create: %s", e)
        return record