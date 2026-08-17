# -*- coding: utf-8 -*-
import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)

# Các trường trên pos.category ảnh hưởng đến dữ liệu hiển thị trên Zalo Mini App
_ZALO_SENSITIVE_CAT_FIELDS = {
    "name",
    "x_active_zalo",
    "x_is_featured_zalo",
    "x_zalo_display_name",
    "sequence",
    "active",
    "parent_id",
    "image_128",
    "image_256",
    "image_512",
    "image_1024",
    "image_1920",
    "image",
}


class PosCategory(models.Model):
    _inherit = "pos.category"

    x_zalo_display_name = fields.Char(
        string="Tên hiển thị Zalo",
        help="Tên hiển thị của danh mục trên Zalo Mini App. Nếu để trống, sẽ tự động dùng tên danh mục POS.",
    )
    x_active_zalo = fields.Boolean(
        string="Hiển thị trên Zalo Mini App",
        default=True,
        help="Tích chọn để danh mục này xuất hiện trên Zalo Mini App. Nếu bỏ tích, danh mục sẽ bị ẩn trên Zalo Mini App.",
    )
    x_is_featured_zalo = fields.Boolean(
        string="Nổi bật Zalo Mini App",
        default=False,
        help="Tích chọn danh mục nổi bật. 7 danh mục có thứ tự ưu tiên (sequence) cao nhất sẽ xuất hiện ngoài Trang chủ Zalo Mini App, tất cả danh mục nổi bật sẽ nằm trong trang Xem thêm.",
    )

    @api.onchange("x_active_zalo")
    def _onchange_x_active_zalo(self):
        if self.x_active_zalo and self.parent_id and not self.parent_id.x_active_zalo:
            self.parent_id.x_active_zalo = True

    def _auto_activate_parents(self):
        """Kích hoạt x_active_zalo = True cho tất cả các danh mục cha/tổ tiên của record."""
        for record in self:
            if record.x_active_zalo and record.parent_id:
                parent = record.parent_id
                while parent:
                    if not parent.x_active_zalo:
                        parent.sudo().write({"x_active_zalo": True})
                    parent = parent.parent_id

    @api.model
    def _fix_existing_parent_active_zalo(self):
        """Quét và kích hoạt x_active_zalo cho tất cả danh mục cha của các danh mục con đang active."""
        active_children = self.search([("x_active_zalo", "=", True), ("parent_id", "!=", False)])
        if active_children:
            active_children._auto_activate_parents()

    def _is_zalo_relevant_write(self, vals):
        """Kiểm tra xem các giá trị sắp được write có ảnh hưởng đến Zalo không."""
        if any(f in vals for f in _ZALO_SENSITIVE_CAT_FIELDS):
            return True
        return False

    def write(self, vals):
        res = super().write(vals)
        if vals.get("x_active_zalo") or vals.get("parent_id"):
            self.filtered(lambda r: r.x_active_zalo)._auto_activate_parents()
        if self._is_zalo_relevant_write(vals):
            is_image_change = any(f in vals for f in ("image_128", "image_256", "image_512", "image_1024", "image_1920", "image"))
            for record in self:
                if record.x_active_zalo or vals.get("x_active_zalo"):
                    try:
                        reason = f"Đổi ảnh danh mục Zalo: {record.name}" if is_image_change else f"Sửa danh mục Zalo: {record.name}"
                        self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                            self.env,
                            trigger_source="auto_cat",
                            affected_model="pos.category",
                            affected_record_name=record.name,
                            trigger_reason=reason,
                        )
                        break
                    except Exception as e:
                        _logger.warning("[VersionBump] Failed to bump catalog version from category: %s", e)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.x_active_zalo)._auto_activate_parents()
        for record in records:
            if record.x_active_zalo:
                try:
                    self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                        self.env,
                        trigger_source="auto_cat",
                        affected_model="pos.category",
                        affected_record_name=record.name,
                        trigger_reason=f"Tạo mới danh mục Zalo: {record.name}",
                    )
                    break
                except Exception as e:
                    _logger.warning("[VersionBump] Failed to bump catalog version on category create: %s", e)
        return records

    def unlink(self):
        zalo_cats = self.filtered(lambda r: r.x_active_zalo)
        if zalo_cats:
            affected_name = ", ".join(zalo_cats.mapped("name")[:3])
            res = super().unlink()
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_catalog_version(
                    self.env,
                    trigger_source="auto_cat",
                    affected_model="pos.category",
                    affected_record_name=affected_name,
                    trigger_reason=f"Xóa danh mục Zalo: {affected_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump catalog version on category unlink: %s", e)
            return res
        return super().unlink()