# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HlvLoyaltyStore(models.Model):
    _name = "hlv.loyalty.store"
    _description = "Chi nhánh / Cửa hàng Hoàng Long Vũ"
    _order = "sequence asc, id asc"

    name = fields.Char(string="Tên chi nhánh / Cửa hàng", required=True)
    active = fields.Boolean(string="Đang hoạt động", default=True)
    sequence = fields.Integer(string="Thứ tự hiển thị", default=10)
    tag = fields.Char(
        string="Nhãn nổi bật",
        default="Chi nhánh",
        help="Ví dụ: Trụ sở chính, Chi nhánh, Showroom, Trung tâm bảo hành...",
    )
    address = fields.Text(string="Địa chỉ chi nhánh", required=True)
    hotline = fields.Char(string="Số điện thoại gọi (Hotline)", required=True, help="vd: 0932632563")
    hotline_display = fields.Char(
        string="Số hotline hiển thị",
        help="vd: 0932.63.25.63 (nếu để trống sẽ tự lấy theo hotline)",
    )
    hours = fields.Char(
        string="Giờ mở cửa / làm việc",
        default="08:00 – 17:30 (Thứ 2 – Thứ 7)",
    )
    map_query = fields.Char(
        string="Link nhúng Google Maps",
        help="Dán URL nhúng Google Maps (Google Maps → Chia sẻ → Nhúng bản đồ). Ứng dụng sẽ mở trực tiếp liên kết này.",
    )
    image = fields.Image(string="Hình ảnh cửa hàng / Showroom", max_width=1024, max_height=1024)
    description = fields.Text(string="Ghi chú thêm")

    image = fields.Image(string="Hình ảnh cửa hàng / Showroom", max_width=1024, max_height=1024)
    description = fields.Text(string="Ghi chú thêm")

    @api.model
    def get_active_stores_data(self):
        """Helper lấy danh sách chi nhánh cho mobile API."""
        records = self.search([("active", "=", True)], order="sequence asc, id asc")
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        data = []
        for r in records:
            img_url = f"{base_url}/api/v1/loyalty/store/{r.id}/image" if r.image else ""
            data.append({
                "id": r.id,
                "name": r.name,
                "tag": r.tag or "",
                "address": r.address or "",
                "hotline": r.hotline or "",
                "hotline_display": r.hotline_display or r.hotline or "",
                "hours": r.hours or "",
                "map_query": r.map_query or r.address or "",
                "image_url": img_url,
                "description": r.description or "",
                "sequence": r.sequence,
            })
        return data
