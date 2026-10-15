# -*- coding: utf-8 -*-
"""Hướng dẫn từng endpoint của API MISA CRM — xem trong app "MISA CRM API → Hướng dẫn API".

Nội dung (tham số, payload, response mẫu) nằm ở data/api_docs.xml, nâng cấp module là cập nhật.
URL và lệnh curl tính lúc xem: điền sẵn địa chỉ Odoo đang chạy và key hiện tại để copy chạy thử.
"""
from odoo import api, fields, models

from ..services.api_doc_utils import build_curl, parse_params, pretty_json
from .api_config import PARAM_KEY

SECTIONS = [
    ("general", "Chung"),
    ("account", "Khách hàng"),
    ("product", "Hàng hóa"),
    ("opportunity", "Cơ hội"),
    ("quote", "Báo giá"),
    ("sale_order", "Đơn hàng"),
]


class MisaCrmApiDoc(models.Model):
    _name = "hlv.misa.crm.api.doc"
    _description = "Hướng dẫn endpoint API MISA CRM"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Việc", required=True)
    section = fields.Selection(SECTIONS, string="Nhóm", required=True)
    route = fields.Char(string="Đường dẫn", required=True)
    is_write = fields.Boolean(string="Ghi dữ liệu MISA",
                              help="Cần bật 'Cho phép tạo dữ liệu trên MISA' trong Cấu hình.")
    summary = fields.Text(string="Mô tả")
    params_spec = fields.Text(string="Tham số", help="Mỗi dòng: tên | kiểu | x nếu bắt buộc | mô tả")
    payload_example = fields.Text(string="Payload mẫu")
    response_example = fields.Text(string="Response mẫu")
    notes = fields.Text(string="Lưu ý")

    url = fields.Char(string="URL", compute="_compute_guide")
    curl = fields.Text(string="curl", compute="_compute_guide")
    guide_html = fields.Html(string="Hướng dẫn", compute="_compute_guide", sanitize=False)

    @api.depends("name", "route", "is_write", "summary", "params_spec", "payload_example",
                 "response_example", "notes")
    def _compute_guide(self):
        params = self.env["ir.config_parameter"].sudo()
        base_url = (params.get_param("web.base.url") or "").rstrip("/")
        # Người xem được hướng dẫn cũng là người được xem key (cùng quyền Quản lý API MISA CRM).
        api_key = params.get_param(PARAM_KEY)
        qweb = self.env["ir.qweb"]
        for doc in self:
            doc.url = base_url + (doc.route or "")
            doc.curl = build_curl(doc.url, api_key, doc.payload_example)
            doc.guide_html = qweb._render("hlv_misa_crm_connect.api_doc_guide", {
                "doc": doc,
                "url": doc.url,
                "api_key": api_key,
                "params": parse_params(doc.params_spec),
                "payload": pretty_json(doc.payload_example) or "{}",
                "response": pretty_json(doc.response_example),
                "curl": doc.curl,
            })
