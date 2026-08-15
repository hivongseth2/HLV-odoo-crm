# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HlvLoyaltyBanner(models.Model):
    _name = "hlv.loyalty.banner"
    _description = "Banner Khuyến Mãi / Ưu Đãi Loyalty Mobile App"
    _order = "sequence asc, id desc"

    name = fields.Char(string="Tên Banner / Chương trình", required=True)
    active = fields.Boolean(string="Đang hoạt động", default=True)
    sequence = fields.Integer(string="Thứ tự", default=10)
    image = fields.Image(string="Hình ảnh Banner", max_width=1024, max_height=1024, required=True)
    tag = fields.Char(string="Nhãn nổi bật", default="ƯU ĐÃI", help="Ví dụ: HOT, ĐỔI QUÀ 0Đ, VOUCHER 100K, NHÂN ĐÔI ĐIỂM")
    subtitle = fields.Char(string="Mô tả phụ / Dòng phụ", help="Dòng text mô tả ngắn hiển thị dưới banner")
    link = fields.Char(string="Trang đích khi click", default="redeem", help="redeem | vouchers | tiers | point_history | hoặc link web http(s)://")
    date_start = fields.Datetime(string="Thời gian bắt đầu")
    date_end = fields.Datetime(string="Thời gian kết thúc")
    description = fields.Text(string="Chi tiết chương trình")

    @api.model
    def get_active_banners_data(self, limit=10):
        """Helper lấy danh sách banners cho mobile API."""
        now = fields.Datetime.now()
        domain = [("active", "=", True)]
        records = self.search(domain, order="sequence asc, id desc", limit=limit)
        # Filter theo thời gian date_start / date_end nếu có
        valid_records = records.filtered(
            lambda r: (not r.date_start or r.date_start <= now) and (not r.date_end or r.date_end >= now)
        )
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        data = []
        for r in valid_records:
            img_url = f"{base_url}/api/v1/loyalty/banner/{r.id}/image" if r.image else ""
            data.append({
                "id": r.id,
                "name": r.name,
                "tag": r.tag or "ƯU ĐÃI",
                "subtitle": r.subtitle or "",
                "link": r.link or "redeem",
                "image_url": img_url,
                "sequence": r.sequence,
            })
        return data

