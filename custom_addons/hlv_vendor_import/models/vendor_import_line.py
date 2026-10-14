# -*- coding: utf-8 -*-
"""Một dòng hàng trong file NCC: ứng viên dò được, kết luận của AI, và quyết định của người bên mình."""

from odoo import api, fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_line import VAT_SELECTION
from odoo.exceptions import UserError
from odoo.osv import expression

from ..services.review_payload import VERDICTS
from .import_utils import rank_candidates, search_terms

# Dò rộng rồi xếp hạng: lấy dư so với số ứng viên gửi AI.
SEARCH_LIMIT = 40


class HlvVendorImportLine(models.Model):
    _name = "hlv.vendor.import.line"
    _description = "Dòng file NCC"
    _order = "import_id, row_no"

    import_id = fields.Many2one("hlv.vendor.import", required=True, ondelete="cascade", index=True)
    row_no = fields.Integer("Dòng Excel")
    vendor_code = fields.Char("Mã NCC")
    code_key = fields.Char("Khoá mã", index=True)
    vendor_name = fields.Char("Tên theo NCC")
    name_alt = fields.Char("Tên phụ")
    uom_name = fields.Char("ĐVT NCC")
    stock = fields.Json("Tồn theo kho")
    stock_display = fields.Char("Tồn")
    stock_total = fields.Float("Tổng tồn", digits="Product Unit of Measure")
    price = fields.Float("Giá chưa VAT", digits=(16, 2))
    price_incl = fields.Float("Giá sau VAT", digits=(16, 2))
    vat = fields.Selection(VAT_SELECTION, "VAT")

    candidate_ids = fields.Many2many("product.product", "hlv_vendor_import_line_candidate_rel", "line_id",
                                     "product_id", "Ứng viên")
    ai_state = fields.Selection([("pending", "Chờ AI"), ("done", "AI đã duyệt"), ("skipped", "Không cần AI")],
                                "AI", default="skipped", required=True)
    ai_verdict = fields.Selection(VERDICTS, "AI kết luận")
    ai_product_id = fields.Many2one("product.product", "AI chọn")
    ai_reason = fields.Char("Lý do")

    product_id = fields.Many2one("product.product", "Sản phẩm bên mình")
    decision = fields.Selection([("pending", "Chưa xác nhận"), ("confirmed", "Đã xác nhận"),
                                 ("no_product", "Không có bên mình")], "Xác nhận", default="pending", required=True)
    match_source = fields.Selection([("alias", "Mã đã nhớ"), ("ai", "AI"), ("manual", "Người chọn")], "Khớp theo")

    def write(self, vals):
        # Ghi product_id mà không kèm decision = người dùng chọn tay trên danh sách → coi như xác nhận luôn.
        # Mọi chỗ code tự ghi product_id (AI, mã đã nhớ) đều ghi kèm decision nên không lọt vào đây.
        if "product_id" in vals and "decision" not in vals:
            for line in self:
                picked = dict(vals, decision="confirmed" if vals["product_id"] else "no_product")
                if vals["product_id"]:
                    picked["match_source"] = "ai" if vals["product_id"] == line.ai_product_id.id else "manual"
                super(HlvVendorImportLine, line).write(picked)
            return True
        return super().write(vals)

    def find_candidates(self, prefixes, brand):
        """Sản phẩm bên mình gần mã / tên của dòng này (đã xếp hạng, tối đa import_utils.CANDIDATE_LIMIT)."""
        self.ensure_one()
        terms = search_terms(self.vendor_code, self.vendor_name, prefixes)
        if not terms:
            return self.env["product.product"]
        domain = expression.OR([["|", ("default_code", "ilike", term), ("name", "ilike", term)] for term in terms])
        found = self.env["product.product"].search_read(domain, ["id", "default_code", "name"], limit=SEARCH_LIMIT)
        ranked = rank_candidates([{"id": p["id"], "code": p["default_code"] or "", "name": p["name"]} for p in found],
                                 self.code_key or "", brand)
        return self.env["product.product"].browse([candidate["id"] for candidate in ranked])

    @api.model
    def review_rows(self, lines):
        """Dữ liệu lô dòng gửi AI (khoá "row" = id dòng), đúng dạng review_payload.review_message cần."""
        return [{
            "row": line.id,
            "code": line.vendor_code or "",
            "name": line.vendor_name or "",
            "name_alt": line.name_alt or "",
            "uom": line.uom_name or "",
            "candidates": [{"id": product.id, "code": product.default_code or "", "name": product.name,
                            "uom": product.uom_id.name} for product in line.candidate_ids],
        } for line in lines]

    def action_confirm(self):
        for line in self:
            product = line.product_id or line.ai_product_id
            if not product:
                raise UserError("Dòng %s chưa có sản phẩm: chọn sản phẩm hoặc bấm \"Không có\"." % line.row_no)
            line.write({"product_id": product.id, "decision": "confirmed",
                        "match_source": line.match_source or ("ai" if product == line.ai_product_id else "manual")})
        return True

    def action_no_product(self):
        self.write({"product_id": False, "decision": "no_product", "match_source": False})
        return True

    def action_reset(self):
        self.write({"decision": "pending"})
        return True
