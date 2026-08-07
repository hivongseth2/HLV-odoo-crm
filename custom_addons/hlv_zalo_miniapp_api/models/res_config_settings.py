# -*- coding: utf-8 -*-
import logging
import time

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    x_zalo_oa_id = fields.Char(
        string='Zalo OA ID',
        config_parameter='hlv_zalo_miniapp.oa_id',
        default='3668388836585145887',
        help='ID tài khoản Zalo Official Account (OA)',
    )
    x_zalo_oa_name = fields.Char(
        string='Tên Zalo OA',
        config_parameter='hlv_zalo_miniapp.oa_name',
        default='Hoàng Long Vũ',
        help='Tên Zalo OA hiển thị trên Mini App',
    )
    x_zalo_oa_subtext = fields.Char(
        string='Mô tả ngắn OA',
        config_parameter='hlv_zalo_miniapp.oa_subtext',
        default='Theo dõi OA để nhận thông tin khuyến mãi, bảo hành và ưu đãi mới nhất!',
        help='Mô tả ngắn hiển thị trên thẻ kết nối OA',
    )

    # ===== Cấu hình Thông báo Yêu cầu Đổi/Trả Zalo =====
    x_zalo_return_notify_user_ids = fields.Many2many(
        "res.users",
        "res_config_settings_zalo_return_user_rel",
        "config_id",
        "user_id",
        string="Người dùng nhận Activity Đổi/Trả Zalo",
        help="Danh sách người dùng Odoo sẽ được giao Activity Task và nhận chuông thông báo khi có yêu cầu đổi/trả từ Zalo Mini App",
    )

    x_zalo_return_zalo_uids = fields.Char(
        string="Zalo User ID nhận tin nhắn Zalo",
        config_parameter="hlv_zalo_miniapp.return_zalo_uids",
        help="Danh sách Zalo User ID (phân cách bằng dấu phẩy) nhận tin nhắn Zalo trực tiếp về điện thoại khi có yêu cầu đổi/trả",
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        raw_user_ids = ICP.get_param("hlv_zalo_miniapp.return_notify_user_ids", "")
        user_ids = []
        if raw_user_ids:
            try:
                clean_ids = raw_user_ids.replace("[", "").replace("]", "").split(",")
                user_ids = [int(u.strip()) for u in clean_ids if u.strip().isdigit()]
            except Exception:
                pass
        res.update(
            x_zalo_return_notify_user_ids=[fields.Command.set(user_ids)],
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        user_ids_str = ",".join(str(u_id) for u_id in self.x_zalo_return_notify_user_ids.ids)
        ICP.set_param("hlv_zalo_miniapp.return_notify_user_ids", user_ids_str)

    # ===== Snapshot Version Monitoring & Controls =====
    x_zalo_catalog_version = fields.Char(
        string="Catalog Version hiện tại",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_catalog_version_dt = fields.Datetime(
        string="Thời điểm Catalog Version",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_banner_version = fields.Char(
        string="Banner Version hiện tại",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_banner_version_dt = fields.Datetime(
        string="Thời điểm Banner Version",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_total_categories = fields.Integer(
        string="Số danh mục Zalo active",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_total_products = fields.Integer(
        string="Số sản phẩm Zalo active",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_total_banners = fields.Integer(
        string="Số Banner Zalo active",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_latest_category_info = fields.Char(
        string="Danh mục sửa mới nhất",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_latest_product_info = fields.Char(
        string="Sản phẩm sửa mới nhất",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_latest_quant_info = fields.Char(
        string="Tồn kho sửa mới nhất",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )
    x_zalo_forced_catalog_version = fields.Char(
        string="Catalog Version ép buộc",
        compute="_compute_zalo_snapshot_info",
        readonly=True,
    )

    def _compute_zalo_snapshot_info(self):
        Param = self.env["ir.config_parameter"].sudo()
        forced_cat_v = Param.get_param("zalo_miniapp_forced_catalog_version", "")
        forced_ban_v = Param.get_param("zalo_miniapp_forced_banner_version", "")

        for rec in self:
            timestamps = []

            # 1. Categories
            cat = self.env["pos.category"].sudo().search([("x_active_zalo", "=", True)], order="write_date desc, id desc", limit=1)
            cat_count = self.env["pos.category"].sudo().search_count([("x_active_zalo", "=", True)])
            rec.x_zalo_total_categories = cat_count
            if cat:
                wdate = cat.write_date or cat.create_date
                rec.x_zalo_latest_category_info = f"{cat.name} ({wdate})" if wdate else cat.name
                if wdate:
                    timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
            else:
                rec.x_zalo_latest_category_info = "Chưa có danh mục Zalo"

            # 2. Products
            prod_domain = [("x_active_zalo", "=", True), ("active", "=", True), ("sale_ok", "=", True)]
            prod = self.env["product.product"].sudo().search(prod_domain, order="write_date desc, id desc", limit=1)
            prod_count = self.env["product.product"].sudo().search_count(prod_domain)
            rec.x_zalo_total_products = prod_count
            if prod:
                wdate = prod.write_date or prod.create_date
                rec.x_zalo_latest_product_info = f"{prod.display_name} ({wdate})" if wdate else prod.display_name
                if wdate:
                    timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
            else:
                rec.x_zalo_latest_product_info = "Chưa có sản phẩm Zalo"

            # 3. Quants
            active_prods = self.env["product.product"].sudo().search(prod_domain)
            quant = self.env["stock.quant"].sudo().search([("product_id", "in", active_prods.ids)], order="write_date desc, id desc", limit=1) if active_prods else self.env["stock.quant"]
            if quant:
                wdate = quant.write_date or quant.create_date
                rec.x_zalo_latest_quant_info = f"{quant.product_id.display_name}: {quant.quantity} {quant.product_uom_id.name} ({wdate})" if wdate else quant.product_id.display_name
                if wdate:
                    timestamps.append(int(fields.Datetime.to_datetime(wdate).timestamp()))
            else:
                rec.x_zalo_latest_quant_info = "Chưa có dữ liệu tồn kho"

            # 4. Banner
            ban = self.env["zalo.miniapp.banner"].sudo().search([("active", "=", True)], order="write_date desc, id desc", limit=1)
            ban_count = self.env["zalo.miniapp.banner"].sudo().search_count([("active", "=", True)])
            rec.x_zalo_total_banners = ban_count

            # Base computed timestamp
            computed_cat_ts = max(timestamps) if timestamps else int(time.time())
            computed_ban_ts = int(fields.Datetime.to_datetime(ban.write_date or ban.create_date).timestamp()) if ban and (ban.write_date or ban.create_date) else int(time.time())

            # Apply forced version if higher
            final_cat_ts = max(computed_cat_ts, int(forced_cat_v)) if forced_cat_v and forced_cat_v.isdigit() else computed_cat_ts
            final_ban_ts = max(computed_ban_ts, int(forced_ban_v)) if forced_ban_v and forced_ban_v.isdigit() else computed_ban_ts

            rec.x_zalo_catalog_version = str(final_cat_ts)
            rec.x_zalo_catalog_version_dt = fields.Datetime.to_string(fields.Datetime.from_timestamp(final_cat_ts))
            rec.x_zalo_banner_version = str(final_ban_ts)
            rec.x_zalo_banner_version_dt = fields.Datetime.to_string(fields.Datetime.from_timestamp(final_ban_ts))
            rec.x_zalo_forced_catalog_version = forced_cat_v or "Tự động"

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
