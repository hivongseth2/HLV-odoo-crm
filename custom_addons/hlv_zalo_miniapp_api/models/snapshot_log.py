# -*- coding: utf-8 -*-
import logging
import time

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ZaloMiniAppSnapshotLog(models.Model):
    _name = "zalo.miniapp.snapshot.log"
    _description = "Lịch sử Version Snapshot Zalo Mini App"
    _order = "id desc"

    name = fields.Char(string="Tiêu đề nhật ký", required=True, default="Snapshot Log")
    snapshot_type = fields.Selection(
        [
            ("catalog", "Catalog (Sản phẩm & Danh mục)"),
            ("banner", "Banner"),
        ],
        string="Loại Snapshot",
        default="catalog",
        required=True,
        index=True,
    )
    version_code = fields.Char(string="Mã Version (Timestamp)", required=True, index=True)
    version_datetime = fields.Datetime(string="Thời gian sinh Version", default=fields.Datetime.now, required=True)
    trigger_source = fields.Selection(
        [
            ("auto_prod", "Sửa sản phẩm Zalo"),
            ("auto_cat", "Sửa danh mục Zalo"),
            ("auto_quant", "Thay đổi tồn kho"),
            ("manual", "Admin ép buộc làm mới"),
        ],
        string="Nguồn kích hoạt",
        default="auto_prod",
        required=True,
    )
    trigger_reason = fields.Char(string="Nguyên nhân chi tiết")
    affected_model = fields.Char(string="Model tác động")
    affected_record_name = fields.Char(string="Bản ghi thay đổi mới nhất")
    user_id = fields.Many2one("res.users", string="Người thực hiện", default=lambda self: self.env.user)
    state = fields.Selection(
        [
            ("active", "Đang áp dụng"),
            ("historical", "Phiên bản cũ"),
        ],
        string="Trạng thái",
        default="active",
        required=True,
        index=True,
    )
    active_products_count = fields.Integer(string="Số SP Zalo Active")
    active_categories_count = fields.Integer(string="Số Danh mục Zalo Active")
    note = fields.Text(string="Ghi chú")

    def action_make_active(self):
        """Đánh dấu log này làm active version hiện tại."""
        for rec in self:
            # Chuyển tất cả log cùng loại về historical
            self.search([("snapshot_type", "=", rec.snapshot_type)]).write({"state": "historical"})
            rec.write({"state": "active"})
            if rec.snapshot_type == "catalog":
                self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_catalog_version", rec.version_code)
            elif rec.snapshot_type == "banner":
                self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_banner_version", rec.version_code)
        return True

    def action_force_bump_catalog(self):
        """Tạo một log thủ công ép buộc làm mới Catalog Version."""
        new_v = str(int(time.time()))
        cat_count = self.env["pos.category"].sudo().search_count([("x_active_zalo", "=", True)])
        prod_count = self.env["product.product"].sudo().search_count([("x_active_zalo", "=", True), ("active", "=", True), ("sale_ok", "=", True)])

        # Set older active logs to historical
        self.search([("snapshot_type", "=", "catalog"), ("state", "=", "active")]).write({"state": "historical"})

        # Create new active log
        new_log = self.create({
            "name": f"Catalog Snapshot #{new_v} (Manual)",
            "snapshot_type": "catalog",
            "version_code": new_v,
            "version_datetime": fields.Datetime.now(),
            "trigger_source": "manual",
            "trigger_reason": "Admin chủ động bấm làm mới Version trên Odoo UI",
            "user_id": self.env.user.id,
            "state": "active",
            "active_products_count": prod_count,
            "active_categories_count": cat_count,
        })
        self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_catalog_version", new_v)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Đã tạo Version mới!"),
                "message": _("Đã sinh Catalog Version %s thành công. Tất cả client Zalo Mini App sẽ nạp lại dữ liệu mới!", new_v),
                "sticky": False,
                "type": "success",
            },
        }

    def action_force_bump_banner(self):
        """Tạo một log thủ công ép buộc làm mới Banner Version."""
        new_v = str(int(time.time()))
        ban_count = self.env["zalo.miniapp.banner"].sudo().search_count([("active", "=", True)])

        self.search([("snapshot_type", "=", "banner"), ("state", "=", "active")]).write({"state": "historical"})

        new_log = self.create({
            "name": f"Banner Snapshot #{new_v} (Manual)",
            "snapshot_type": "banner",
            "version_code": new_v,
            "version_datetime": fields.Datetime.now(),
            "trigger_source": "manual",
            "trigger_reason": "Admin chủ động bấm làm mới Banner Version trên Odoo UI",
            "user_id": self.env.user.id,
            "state": "active",
        })
        self.env["ir.config_parameter"].sudo().set_param("zalo_miniapp_forced_banner_version", new_v)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Đã tạo Version Banner mới!"),
                "message": _("Đã sinh Banner Version %s thành công!", new_v),
                "sticky": False,
                "type": "success",
            },
        }
