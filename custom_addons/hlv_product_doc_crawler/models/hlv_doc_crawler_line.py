from odoo import fields, models


class HlvDocCrawlerLine(models.Model):
    _name = "hlv.doc.crawler.line"
    _description = "Log Crawler từng sản phẩm"
    _order = "run_date desc, id desc"
    _rec_name = "sku"

    crawler_id = fields.Many2one(
        "hlv.doc.crawler", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.template", string="Sản phẩm", readonly=True
    )
    sku = fields.Char(string="Mã SP (SKU)", readonly=True)
    status = fields.Selection(
        [
            ("pending", "Chờ"),
            ("found", "Tìm thấy"),
            ("not_found", "Không tìm thấy"),
            ("error", "Lỗi"),
        ],
        default="pending",
        string="Kết quả",
        readonly=True,
    )
    wc_url = fields.Char(string="URL sản phẩm", readonly=True)
    match_score = fields.Float(
        string="Độ tương đồng",
        readonly=True,
        digits=(4, 2),
        help="Điểm tương đồng MecSu (1.0 = khớp SKU chính xác, 0.65+ = chấp nhận được)",
    )
    error_msg = fields.Text(string="Chi tiết lỗi", readonly=True)
    document_id = fields.Many2one(
        "ir.attachment", string="File tài liệu", readonly=True
    )
    resource_id = fields.Many2one(
        "llm.resource", string="RAG Resource", readonly=True
    )
    run_date = fields.Datetime(string="Thời gian", readonly=True)
