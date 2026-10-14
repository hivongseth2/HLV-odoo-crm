# -*- coding: utf-8 -*-
"""Khớp mã NCC ↔ sản phẩm bên mình khi TRÙNG MÃ CHẮC CHẮN — tự gắn, không hỏi ai.

Mỗi NCC đặt mã một kiểu (SATA: NCC ghi "SC03200", bên mình "03200-SATA"): mẫu file của NCC khai tiền tố NCC tự thêm
và "Mã bên mình" ({ma}-SATA…) — import_utils.code_patterns. Chắc chắn = theo mẫu ra ĐÚNG MỘT sản phẩm đang dùng; ra
nhiều sản phẩm (hai hãng cùng số model) thì không gắn, để người chọn.

Chạy ở ba chỗ: đọc file NCC (vendor_import._match), sale / MISA tạo hoặc đổi mã sản phẩm (product_product.py — sản
phẩm thường được tạo SAU khi đã nhập bảng giá), và nút "Khớp lại theo mã" trên mẫu file (sau khi sửa mẫu mã).
"""

import logging

from odoo import api, models

from .import_utils import code_patterns, keys_from_our_code, our_codes

_logger = logging.getLogger(__name__)

# Chuẩn hoá mã trong SQL giống import_utils.normalize_code: chữ hoa, bỏ khoảng trắng và - _ . /
_SQL_NORMALIZED_CODE = "upper(regexp_replace(default_code, '[[:space:]_./-]', '', 'g'))"


class HlvVendorCodeMatch(models.AbstractModel):
    _name = "hlv.vendor.code.match"
    _description = "Khớp mã NCC theo mẫu mã"

    @api.model
    def products_for_keys(self, profile, keys):
        """{khoá mã NCC: sản phẩm} cho các khoá ra đúng một sản phẩm đang dùng theo mẫu mã của profile."""
        patterns = code_patterns(profile.our_code_patterns, profile.brand)
        wanted = {key: our_codes(key, patterns) for key in keys if key}
        by_code = self._products_by_codes({code for codes in wanted.values() for code in codes})
        result = {}
        for key, codes in wanted.items():
            ids = {product_id for code in codes for product_id in by_code.get(code, ())}
            if len(ids) == 1:
                result[key] = self.env["product.product"].browse(ids.pop())
        return result

    def _products_by_codes(self, codes):
        """{mã đã chuẩn hoá: [id sản phẩm]} — so mã đã bỏ dấu cách / gạch như normalize_code, nên phải SQL."""
        if not codes:
            return {}
        self.env["product.product"].flush_model(["default_code", "active"])
        self.env.cr.execute(
            f"SELECT {_SQL_NORMALIZED_CODE}, id FROM product_product "
            f"WHERE active AND default_code IS NOT NULL AND {_SQL_NORMALIZED_CODE} = ANY(%s)", [list(codes)])
        found = {}
        for code, product_id in self.env.cr.fetchall():
            found.setdefault(code, []).append(product_id)
        return found

    @api.model
    def link_unmatched(self, profile):
        """Gắn sản phẩm cho dòng bảng giá / tồn kho chưa khớp của NCC theo mẫu mã. Trả số mã vừa khớp."""
        rows = self._unmatched_rows(profile.partner_id)
        found = self.products_for_keys(profile, set(rows))
        for key, product in found.items():
            self._link(profile.partner_id, key, product, rows[key])
        return len(found)

    @api.model
    def link_products(self, products):
        """Sản phẩm vừa tạo / đổi mã: gắn vào dòng bảng giá / tồn kho chưa khớp của mọi NCC có mẫu mã ra đúng nó."""
        products = products.filtered("default_code")
        if not products:
            return
        for profile in self.env["hlv.vendor.import.profile"].search([]):
            patterns = code_patterns(profile.our_code_patterns, profile.brand)
            keys = {key for product in products for key in keys_from_our_code(product.default_code, patterns)}
            if not keys:
                continue
            rows = self._unmatched_rows(profile.partner_id, keys)
            for key, product in self.products_for_keys(profile, set(rows)).items():
                if product in products:
                    self._link(profile.partner_id, key, product, rows[key])

    def _unmatched_rows(self, partner, keys=None):
        """{khoá mã: (dòng giá, dòng tồn)} chưa gắn sản phẩm của NCC — chỉ các khoá trong keys nếu có."""
        domain = [("partner_id", "=", partner.id), ("product_id", "=", False), ("match_key", "!=", False)]
        if keys is not None:
            domain.append(("match_key", "in", list(keys)))
        prices = self.env["hlv.vendor.price"].search(domain)
        stocks = self.env["hlv.vendor.stock"].search(domain)
        rows = {}
        for index, records in enumerate((prices, stocks)):
            for record in records:
                rows.setdefault(record.match_key, [prices.browse(), stocks.browse()])[index] |= record
        return {key: tuple(pair) for key, pair in rows.items()}

    @api.model
    def link_key(self, partner, key, product):
        """Người xác nhận mã NCC key là product (gợi ý khớp mã): gắn mọi dòng giá / tồn chưa khớp của mã + nhớ mã —
        người quyết thì ghi đè mã đã nhớ."""
        rows = self._unmatched_rows(partner, {key}).get(key) or (self.env["hlv.vendor.price"], self.env["hlv.vendor.stock"])
        self._link(partner, key, product, rows, force=True)

    def _link(self, partner, key, product, rows, force=False):
        """Gắn product cho các dòng của khoá + nhớ mã cho lần nhập sau. Khoá đã có người khớp với sản phẩm khác thì
        giữ theo người (mẫu mã có thể khai chưa đúng), không gắn — trừ khi force (chính người đang xác nhận)."""
        Alias = self.env["hlv.vendor.product.alias"]
        known = Alias.lookup(partner, {key}).get(key)
        if known and known != product and not force:
            return
        prices, stocks = rows
        (prices | stocks).write({"product_id": product.id})
        sample = prices[:1] or stocks[:1] or self.env["hlv.vendor.price"].search(
            [("partner_id", "=", partner.id), ("match_key", "=", key)], limit=1)
        Alias.link(partner, key, product, sample.vendor_code, sample.vendor_name)
        _logger.info("VENDOR_CODE_MATCH NCC %s: mã %s → sản phẩm %s", partner.id, key, product.default_code)
