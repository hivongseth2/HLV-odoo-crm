# -*- coding: utf-8 -*-
import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _has_zalo_active_product(self):
        """Kiểm tra xem quant này có thuộc sản phẩm Zalo active không."""
        self.ensure_one()
        product = self.product_id
        return product.x_active_zalo and product.active and product.sale_ok

    def write(self, vals):
        # Kiểm tra trước khi write xem có quant nào thuộc sản phẩm Zalo không
        zalo_quants = self.filtered(lambda q: q._has_zalo_active_product())
        res = super().write(vals)
        if zalo_quants:
            affected_names = list(set(zalo_quants.mapped("product_id.display_name")))
            affected_name = ", ".join(affected_names[:3])
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_quant",
                    affected_model="stock.quant",
                    affected_record_name=affected_name,
                    trigger_reason=f"Thay đổi tồn kho sản phẩm Zalo: {affected_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version from stock.quant: %s", e)
        return res

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if record._has_zalo_active_product():
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_quant",
                    affected_model="stock.quant",
                    affected_record_name=record.product_id.display_name,
                    trigger_reason=f"Tạo mới tồn kho cho sản phẩm Zalo: {record.product_id.display_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version on stock.quant create: %s", e)
        return record