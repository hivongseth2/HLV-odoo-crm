# -*- coding: utf-8 -*-
"""Trang /hoi-gia-ncc/tra-gia: sale gõ mã sản phẩm, xem mọi giá đã mua / NCC từng báo theo
từng NCC (services/price_lookup.py). Cùng quyền vào trang với /hoi-gia-ncc, không theo mã sale."""

import json

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.vendor_quote_access import SALE_PAGE_ROUTE
from ..services.asset_version import asset_version
from ..services.price_lookup import product_prices
from .sale_page_common import API, SalePageMixin, to_int

LOOKUP_ROUTE = f"{SALE_PAGE_ROUTE}/tra-gia"


class SalePriceLookup(SalePageMixin, http.Controller):

    @http.route(LOOKUP_ROUTE, type="http", auth="user", methods=["GET"])
    def price_lookup_page(self, p=None, **kw):
        return request.render("hlv_vendor_quotation.sale_price_lookup", {
            "asset_version": asset_version(),
            "allowed": self._allowed(),
            "initial_product_id": to_int(p),
            "sale_names": json.dumps(request.env["hlv.vendor.sale.contact"]._name_map()),
        })

    @http.route(f"{API}/product_prices", type="json", auth="user", methods=["POST"])
    def api_product_prices(self, product_id=None, **kw):
        self._check()
        product = request.env["product.product"].sudo().browse(to_int(product_id)).exists()
        if not product:
            raise UserError("Không tìm thấy sản phẩm.")
        return product_prices(request.env, product)
