# -*- coding: utf-8 -*-
"""Cron: sản phẩm đang được hỏi giá với NCC mà bảng giá NCC chưa gắn sản phẩm đó → dò các mã NCC chưa khớp gần mã / tên,
Claude duyệt (cùng prompt với lúc nhập file — review_payload), ra gợi ý chờ sale / quản lý xác nhận
(vendor_code_suggestion.py). Trùng mã chắc chắn đã tự gắn trước đó (vendor_code_match.py) nên không tới đây.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.osv import expression

from odoo.addons.hlv_product_agent.services.claude_client import load_anthropic, make_client

from ..services.review_payload import BATCH_SIZE, VERDICT_MATCH, VERDICT_PROBABLE
from .import_utils import search_terms
from .vendor_import_ai import REQUEST_TIMEOUT_SECONDS, ReviewFailed

_logger = logging.getLogger(__name__)

# Báo giá còn hỏi: đã gửi / đã báo, tạo trong chừng này ngày.
QUOTE_WINDOW_DAYS = 14
# Số mã NCC ứng viên tối đa cho một sản phẩm.
CANDIDATE_ROWS = 6


class HlvVendorCodeSuggest(models.AbstractModel):
    _name = "hlv.vendor.code.suggest"
    _description = "AI gợi ý khớp mã NCC cho sản phẩm đang hỏi giá"

    @api.model
    def _cron_suggest(self):
        config = self.env["hlv.vendor.import.ai"].config()
        anthropic = load_anthropic()
        if not config["api_key"] or not anthropic:
            return
        client = make_client(anthropic, config["api_key"], timeout=REQUEST_TIMEOUT_SECONDS)
        for partner, lines in self._lines_to_check().items():
            try:
                self._suggest_for(anthropic, client, config["model"], partner, lines)
                self.env.cr.commit()  # mỗi NCC một lần: NCC sau lỗi không mất gợi ý của NCC trước
            except ReviewFailed as failure:
                self.env.cr.rollback()
                _logger.warning("VENDOR_CODE_SUGGEST NCC %s: %s", partner.id, failure)
            except Exception:  # noqa: BLE001 — một NCC lỗi không chặn các NCC khác
                self.env.cr.rollback()
                _logger.exception("VENDOR_CODE_SUGGEST lỗi ở NCC %s", partner.id)

    def _lines_to_check(self):
        """{NCC: dòng báo giá} — sản phẩm đang hỏi, NCC có bảng giá còn mã chưa khớp, chưa có giá đang hiệu lực cho sản
        phẩm, và chưa từng gợi ý (kể cả đã bỏ / AI không thấy) cho cặp NCC × sản phẩm."""
        Price = self.env["hlv.vendor.price"]
        partners = self.env["res.partner"].union(*(
            partner for (partner,) in Price._read_group([("product_id", "=", False)], ["partner_id"])))
        if not partners:
            return {}
        quotes = self.env["hlv.vendor.quote"].search([
            ("state", "in", ("sent", "quoted")), ("partner_id.commercial_partner_id", "in", partners.ids),
            ("create_date", ">=", fields.Datetime.now() - timedelta(days=QUOTE_WINDOW_DAYS)),
        ])
        asked = {(s.partner_id.id, s.product_id.id) for s in self.env["hlv.vendor.code.suggestion"].search(
            [("partner_id", "in", partners.ids)])}
        result = {}
        for quote in quotes:
            partner = quote.partner_id.commercial_partner_id
            today = quote._vendor_today()
            for line in quote._vendor_lines().filtered("product_id"):
                key = (partner.id, line.product_id.id)
                if key in asked or Price.current_price(partner, line.product_id, today):
                    continue
                asked.add(key)
                result.setdefault(partner, self.env["hlv.vendor.quote.line"])
                result[partner] |= line
        return result

    def _suggest_for(self, anthropic, client, model, partner, lines):
        """Dò mã NCC ứng viên cho từng sản phẩm, Claude duyệt theo lô, ghi gợi ý. Sản phẩm không có ứng viên / AI không
        thấy khớp → ghi "none" để lần sau khỏi dò lại."""
        Suggestion = self.env["hlv.vendor.code.suggestion"]
        profile = self.env["hlv.vendor.import.profile"].search([("partner_id", "=", partner.id)], limit=1)
        rows, quote_of = {}, {}
        for line in lines:
            quote_of[line.product_id] = line.quote_id
            for price in self._candidate_rows(partner, line.product_id):
                row = rows.setdefault(price.id, {
                    "row": price.id, "code": price.vendor_code or "", "name": price.vendor_name or "", "name_alt": "",
                    "uom": price.uom_name or "", "candidates": []})
                row["candidates"].append({"id": line.product_id.id, "code": line.product_id.default_code or "",
                                          "name": line.product_id.name, "uom": line.product_id.uom_id.name})
        found = {}
        batch = list(rows.values())
        for start in range(0, len(batch), BATCH_SIZE):
            chunk = batch[start:start + BATCH_SIZE]
            _stop, results = self.env["hlv.vendor.import.ai"]._ask_review(
                anthropic, client, model, partner.display_name, profile.brand, chunk, "gợi ý khớp mã")
            if results is None:
                raise ReviewFailed("Claude không trả lời trọn vẹn.")
            for price_id, result in results.items():
                if result["verdict"] in (VERDICT_MATCH, VERDICT_PROBABLE) and result["product_id"]:
                    found.setdefault(result["product_id"], []).append((price_id, result))
        for product, quote in quote_of.items():
            hits = found.get(product.id)
            if not hits:
                Suggestion.create({"partner_id": partner.id, "product_id": product.id, "quote_id": quote.id,
                                   "state": "none"})
                continue
            Suggestion.create([{"partner_id": partner.id, "product_id": product.id, "quote_id": quote.id,
                                "price_id": price_id, "verdict": result["verdict"], "reason": result["reason"]}
                               for price_id, result in hits])

    def _candidate_rows(self, partner, product):
        """Dòng bảng giá chưa khớp của NCC gần mã / tên sản phẩm (dò rộng — AI loại cặp sai)."""
        terms = search_terms(product.default_code, product.name, [])
        if not terms:
            return self.env["hlv.vendor.price"]
        domain = expression.OR([["|", ("vendor_code", "ilike", term), ("vendor_name", "ilike", term)] for term in terms])
        prices = self.env["hlv.vendor.price"].search(
            [("partner_id", "=", partner.id), ("product_id", "=", False)] + domain, order="date_from desc, id desc")
        # Một mã NCC có nhiều đời giá: chỉ đưa dòng mới nhất của mỗi mã.
        latest = {}
        for price in prices:
            latest.setdefault(price.match_key, price)
        return self.env["hlv.vendor.price"].union(*list(latest.values())[:CANDIDATE_ROWS])
