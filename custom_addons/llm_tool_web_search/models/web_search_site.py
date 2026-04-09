from odoo import api, fields, models


class WebSearchSite(models.Model):
    _name = "llm.web.search.site"
    _description = "Website được phép tìm kiếm"
    _order = "sequence, name"

    name = fields.Char(string="Tên website", required=True)
    url = fields.Char(string="URL gốc", required=True, help="VD: https://www.ketnoitieudung.vn")
    description = fields.Text(string="Mô tả", help="Mô tả ngắn về nội dung website để AI hiểu ngữ cảnh")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ("url_unique", "UNIQUE(url)", "URL website đã tồn tại!"),
    ]

    @api.model
    def _get_domain_from_url(self, url):
        """Trích xuất domain từ URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or parsed.path
