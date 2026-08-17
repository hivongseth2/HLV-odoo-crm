# -*- coding: utf-8 -*-
import logging
import time
from datetime import datetime

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ZaloMiniAppSnapshot(models.Model):
    _name = "zalo.miniapp.snapshot"
    _description = "Quản lý & Theo dõi Version Snapshot Zalo Mini App"
    _order = "id desc"

    name = fields.Char(string="Tên bảng tin", compute="_compute_snapshot_info", store=False)
    catalog_version = fields.Char(string="Catalog Version hiện tại", compute="_compute_snapshot_info", store=False)
    catalog_version_datetime = fields.Datetime(string="Thời điểm Catalog Version", compute="_compute_snapshot_info", store=False)
    banner_version = fields.Char(string="Banner Version hiện tại", compute="_compute_snapshot_info", store=False)
    banner_version_datetime = fields.Datetime(string="Thời điểm Banner Version", compute="_compute_snapshot_info", store=False)

    latest_category_id = fields.Many2one("pos.category", string="Danh mục sửa mới nhất", compute="_compute_snapshot_info", store=False)
    latest_category_write_date = fields.Datetime(string="Thời điểm sửa danh mục", compute="_compute_snapshot_info", store=False)

    latest_product_id = fields.Many2one("product.product", string="Sản phẩm sửa mới nhất", compute="_compute_snapshot_info", store=False)
    latest_product_write_date = fields.Datetime(string="Thời điểm sửa sản phẩm", compute="_compute_snapshot_info", store=False)

    latest_quant_id = fields.Many2one("stock.quant", string="Tồn kho sửa mới nhất", compute="_compute_snapshot_info", store=False)
    latest_quant_write_date = fields.Datetime(string="Thời điểm sửa tồn kho", compute="_compute_snapshot_info", store=False)

    latest_banner_id = fields.Many2one("zalo.miniapp.banner", string="Banner sửa mới nhất", compute="_compute_snapshot_info", store=False)
    latest_banner_write_date = fields.Datetime(string="Thời điểm sửa banner", compute="_compute_snapshot_info", store=False)

    total_zalo_categories = fields.Integer(string="Số danh mục Zalo active", compute="_compute_snapshot_info", store=False)
    total_zalo_products = fields.Integer(string="Số sản phẩm Zalo active", compute="_compute_snapshot_info", store=False)
    total_zalo_banners = fields.Integer(string="Số Banner Zalo active", compute="_compute_snapshot_info", store=False)

    forced_catalog_version = fields.Char(string="Version Catalog ép làm mới", compute="_compute_snapshot_info", store=False)
    forced_banner_version = fields.Char(string="Version Banner ép làm mới", compute="_compute_snapshot_info", store=False)

    def _compute_snapshot_info(self):
        Param = self.env["ir.config_parameter"].sudo()
        forced_cat_v = Param.get_param("zalo_miniapp_forced_catalog_version", "")
        forced_ban_v = Param.get_param("zalo_miniapp_forced_banner_version", "")

        for rec in self:
            timestamps = []

            # 1. Categories
            cat = self.env["pos.category"].sudo().search([("x_active_zalo", "=", True)], order="write_date desc, id desc", limit=1)
            cat_count = self.env["pos.category"].sudo().search_count([("x_active_zalo", "=", True)])
            rec.latest_category_id = cat.id if cat else False
            rec.latest_category_write_date = (cat.write_date or cat.create_date) if cat else False
            rec.total_zalo_categories = cat_count
            if cat and (cat.write_date or cat.create_date):
                timestamps.append(int(fields.Datetime.to_datetime(cat.write_date or cat.create_date).timestamp()))

            # 2. Products
            prod_domain = [("x_active_zalo", "=", True), ("active", "=", True), ("sale_ok", "=", True)]
            prod = self.env["product.product"].sudo().search(prod_domain, order="write_date desc, id desc", limit=1)
            prod_count = self.env["product.product"].sudo().search_count(prod_domain)
            rec.latest_product_id = prod.id if prod else False
            rec.latest_product_write_date = (prod.write_date or prod.create_date) if prod else False
            rec.total_zalo_products = prod_count
            if prod and (prod.write_date or prod.create_date):
                timestamps.append(int(fields.Datetime.to_datetime(prod.write_date or prod.create_date).timestamp()))

            # 3. Quants
            active_prods = self.env["product.product"].sudo().search(prod_domain)
            quant = self.env["stock.quant"].sudo().search([("product_id", "in", active_prods.ids)], order="write_date desc, id desc", limit=1) if active_prods else self.env["stock.quant"]
            rec.latest_quant_id = quant.id if quant else False
            rec.latest_quant_write_date = (quant.write_date or quant.create_date) if quant else False
            if quant and (quant.write_date or quant.create_date):
                timestamps.append(int(fields.Datetime.to_datetime(quant.write_date or quant.create_date).timestamp()))

            # 4. Banner
            ban = self.env["zalo.miniapp.banner"].sudo().search([("active", "=", True)], order="write_date desc, id desc", limit=1)
            ban_count = self.env["zalo.miniapp.banner"].sudo().search_count([("active", "=", True)])
            rec.latest_banner_id = ban.id if ban else False
            rec.latest_banner_write_date = (ban.write_date or ban.create_date) if ban else False
            rec.total_zalo_banners = ban_count

            # Base computed timestamp
            computed_cat_ts = max(timestamps) if timestamps else int(time.time())
            computed_ban_ts = int(fields.Datetime.to_datetime(ban.write_date or ban.create_date).timestamp()) if ban and (ban.write_date or ban.create_date) else int(time.time())

            # Apply forced version if higher
            final_cat_ts = max(computed_cat_ts, int(forced_cat_v)) if forced_cat_v and forced_cat_v.isdigit() else computed_cat_ts
            final_ban_ts = max(computed_ban_ts, int(forced_ban_v)) if forced_ban_v and forced_ban_v.isdigit() else computed_ban_ts

            rec.catalog_version = str(final_cat_ts)
            rec.catalog_version_datetime = fields.Datetime.to_string(datetime.fromtimestamp(final_cat_ts))
            rec.banner_version = str(final_ban_ts)
            rec.banner_version_datetime = fields.Datetime.to_string(datetime.fromtimestamp(final_ban_ts))
            rec.forced_catalog_version = forced_cat_v or "Tự động"
            rec.forced_banner_version = forced_ban_v or "Tự động"
            rec.name = f"Zalo Snapshot Version: {final_cat_ts}"

    def action_force_bump_catalog_version(self):
        """Buộc làm mới Catalog Version: gán forced timestamp mới để tất cả client Zalo reload."""
        new_v = str(int(time.time()))
        self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_catalog_version", new_v)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Thành công"),
                "message": _("Đã làm mới Catalog Version thành %s. Tất cả Zalo Mini App client sẽ nạp lại snapshot mới!", new_v),
                "sticky": False,
                "type": "success",
            },
        }

    def action_force_bump_banner_version(self):
        """Buộc làm mới Banner Version."""
        new_v = str(int(time.time()))
        self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_banner_version", new_v)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Thành công"),
                "message": _("Đã làm mới Banner Version thành %s!", new_v),
                "sticky": False,
                "type": "success",
            },
        }

    def action_reset_forced_version(self):
        """Xóa ép buộc version, quay về tự động theo write_date."""
        Param = self.env["ir.config_parameter"].sudo()
        Param.set_param("zalo_miniapp_forced_catalog_version", "")
        Param.set_param("zalo_miniapp_forced_banner_version", "")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Đã xoá ép buộc version"),
                "message": _("Hệ thống quay lại tính version tự động theo thời gian chỉnh sửa dữ liệu."),
                "sticky": False,
                "type": "info",
            },
        }

    def action_refresh(self):
        """Refresh view."""
        return True
