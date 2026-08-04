# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Các trường trên banner ảnh hưởng đến dữ liệu hiển thị trên Zalo Mini App
_ZALO_SENSITIVE_BANNER_FIELDS = {
    "name",
    "active",
    "sequence",
    "image",
    "link",
}


class ZaloMiniAppBanner(models.Model):
    _name = 'zalo.miniapp.banner'
    _description = 'Zalo Mini App Banner'
    _order = 'sequence, id'

    name = fields.Char(string='Tên Banner', required=True)
    active = fields.Boolean(string='Active', default=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    image = fields.Image(string='Hình ảnh', max_width=1024, max_height=1024, required=True)
    link = fields.Char(string='Link khi click', help="Đường dẫn hoặc trang đích sẽ mở ra khi khách hàng bấm vào banner này trên ứng dụng (không bắt buộc)")

    def _is_zalo_relevant_write(self, vals):
        """Kiểm tra xem các giá trị sắp được write có ảnh hưởng đến Zalo không."""
        if any(f in vals for f in _ZALO_SENSITIVE_BANNER_FIELDS):
            return True
        return False

    def write(self, vals):
        res = super().write(vals)
        if self._is_zalo_relevant_write(vals):
            for record in self:
                if record.active or vals.get("active"):
                    try:
                        self.env["zalo.miniapp.snapshot.log"]._bump_banner_version(
                            self.env,
                            trigger_source="manual",
                            affected_model="zalo.miniapp.banner",
                            affected_record_name=record.name,
                            trigger_reason=f"Sửa banner: {record.name}",
                        )
                        break
                    except Exception as e:
                        _logger.warning("[VersionBump] Failed to bump banner version: %s", e)
        return res

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if record.active:
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_banner_version(
                    self.env,
                    trigger_source="manual",
                    affected_model="zalo.miniapp.banner",
                    affected_record_name=record.name,
                    trigger_reason=f"Tạo mới banner: {record.name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump banner version on create: %s", e)
        return record

    def unlink(self):
        active_banners = self.filtered(lambda r: r.active)
        if active_banners:
            affected_name = ", ".join(active_banners.mapped("name")[:3])
            res = super().unlink()
            try:
                self.env["zalo.miniapp.snapshot.log"]._bump_banner_version(
                    self.env,
                    trigger_source="manual",
                    affected_model="zalo.miniapp.banner",
                    affected_record_name=affected_name,
                    trigger_reason=f"Xóa banner: {affected_name}",
                )
            except Exception as e:
                _logger.warning("[VersionBump] Failed to bump banner version on unlink: %s", e)
            return res
        return super().unlink()
