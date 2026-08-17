# -*- coding: utf-8 -*-
import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)

# Các trường trên product.product liên quan đến Zalo (nếu có variant-level custom fields sau này)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def action_sync_to_wordpress(self):
        """
        Dummy method để bypass lỗi ParseError khi Odoo compile view product.product_normal_form_view.
        Nút bấm này được kế thừa từ wordpress_sync vào product.template nhưng product.product cũng kế thừa view.
        """
        for record in self:
            if hasattr(record.product_tmpl_id, "action_sync_to_wordpress"):
                return record.product_tmpl_id.action_sync_to_wordpress()
        return True

    def action_sync_stock_to_wordpress(self):
        """
        Dummy method để bypass lỗi ParseError (tương tự như hàm trên).
        """
        for record in self:
            if hasattr(record.product_tmpl_id, "action_sync_stock_to_wordpress"):
                return record.product_tmpl_id.action_sync_stock_to_wordpress()
        return True

    def action_open_combo_to_bom_wizard(self):
        """
        Dummy method để bypass lỗi ParseError từ module hlv_combo_to_bom.
        """
        for record in self:
            if hasattr(record.product_tmpl_id, "action_open_combo_to_bom_wizard"):
                return record.product_tmpl_id.action_open_combo_to_bom_wizard()
        return True

    def _is_zalo_active_variant(self):
        """Kiểm tra variant này có thuộc sản phẩm Zalo active không."""
        self.ensure_one()
        return self.x_active_zalo and self.active and self.sale_ok

    def write(self, vals):
        res = super().write(vals)
        for record in self:
            # Bump nếu variant đang active Zalo (kiểm tra cả sau khi write)
            if record._is_zalo_active_variant():
                try:
                    self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                        self.env,
                        trigger_source="auto_prod",
                        affected_model="product.product",
                        affected_record_name=record.display_name,
                        trigger_reason=f"Sửa variant sản phẩm Zalo: {record.display_name}",
                    )
                    break  # Chỉ bump 1 lần cho cả batch
                except Exception as e:
                    _logger.warning("[VersionBump] Failed to bump catalog version from variant: %s", e)
        return res

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if record._is_zalo_active_variant():
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_prod",
                    affected_model="product.product",
                    affected_record_name=record.display_name,
                    trigger_reason=f"Tạo mới variant sản phẩm Zalo: {record.display_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version on variant create: %s", e)
        return record

    def unlink(self):
        """Khi xóa variant của sản phẩm Zalo, bump catalog version."""
        zalo_variants = self.filtered(lambda r: r._is_zalo_active_variant())
        if zalo_variants:
            affected_name = ", ".join(zalo_variants.mapped("display_name")[:3])
            # Lưu lại thông tin trước khi unlink
            res = super().unlink()
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_prod",
                    affected_model="product.product",
                    affected_record_name=affected_name,
                    trigger_reason=f"Xóa variant sản phẩm Zalo: {affected_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version on variant unlink: %s", e)
            return res
        return super().unlink()