# -*- coding: utf-8 -*-
import html
import logging

from odoo import fields, http
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloProductAPI(ZaloBaseAPI, http.Controller):
    """API Sản phẩm (product.product variant) cho Zalo Mini App"""

    def _get_product_images(self, product):
        """Thu thập danh sách tất cả URL ảnh của sản phẩm (ảnh chính + ảnh phụ)."""
        images = []
        tmpl = product.product_tmpl_id
        p_wdate = product.write_date or product.create_date

        # 1. Ảnh chính (Variant hoặc Template)
        if product.image_1920:
            images.append(self._get_image_url("product.product", product.id, "image_1920", write_date=p_wdate))
        elif tmpl and tmpl.image_1920:
            images.append(self._get_image_url("product.template", tmpl.id, "image_1920", write_date=tmpl.write_date or tmpl.create_date))

        # 2. Ảnh bổ sung của Variant (Odoo standard: product_variant_image_ids)
        try:
            if hasattr(product, "product_variant_image_ids"):
                for img in product.product_variant_image_ids:
                    if img.image_1920:
                        url = self._get_image_url("product.image", img.id, "image_1920", write_date=img.write_date or img.create_date)
                        if url not in images:
                            images.append(url)
        except Exception:
            pass

        # 3. Ảnh bổ sung của Template (Odoo standard website/e-commerce: product_template_image_ids)
        try:
            if tmpl and hasattr(tmpl, "product_template_image_ids"):
                for img in tmpl.product_template_image_ids:
                    if img.image_1920:
                        url = self._get_image_url("product.image", img.id, "image_1920", write_date=img.write_date or img.create_date)
                        if url not in images:
                            images.append(url)
        except Exception:
            pass

        # 4. Ảnh phụ từ các trường image_1, image_2, image_3, image_4, image_5 (module product_multi_images)
        if tmpl:
            for img_field in ["image_1", "image_2", "image_3", "image_4", "image_5"]:
                try:
                    if hasattr(tmpl, img_field) and getattr(tmpl, img_field):
                        url = self._get_image_url("product.template", tmpl.id, img_field, write_date=tmpl.write_date or tmpl.create_date)
                        if url not in images:
                            images.append(url)
                except Exception:
                    pass

        # 5. Ảnh bổ sung từ custom model quan hệ (product_multi_images)
        try:
            if tmpl and hasattr(tmpl, "product_multi_images"):
                for img in tmpl.product_multi_images:
                    if img.image_1920:
                        url = self._get_image_url("product.multi.image", img.id, "image_1920", write_date=img.write_date or img.create_date)
                        if url not in images:
                            images.append(url)
        except Exception:
            pass

        # 6. Fallback nếu chưa có ảnh nào: lấy image_128
        if not images and product.image_128:
            images.append(self._get_image_url("product.product", product.id, "image_128", write_date=p_wdate))

        return images


    def _build_product_data(self, product, batch_prices=None, batch_sales_counts=None):
        """Build standard product response dict from a product.product record.
        
        :param product: product.product record
        :param batch_prices: dict {product_id: promotional_price} từ batch query pricelist
                             Nếu None, sẽ query riêng lẻ (fallback cũ)
        :param batch_sales_counts: dict {product_id: sales_count} từ batch query sale.order.line
                                   Nếu None, sales_count = 0
        """
        attributes = []
        if hasattr(product, "product_template_attribute_value_ids"):
            for ptav in product.product_template_attribute_value_ids:
                attr = ptav.attribute_id
                val = ptav.product_attribute_value_id
                attributes.append({
                    "id": val.id,
                    "name": attr.name,
                    "value": val.name,
                })

        category = None
        category_ids = []
        categories = []

        # 1. Lấy từ x_zalo_categ_ids (Danh mục Zalo)
        if product.x_zalo_categ_ids:
            for cat in product.x_zalo_categ_ids:
                if cat.id not in category_ids:
                    category_ids.append(cat.id)
                    categories.append({"id": cat.id, "name": cat.name})

        # 2. Lấy bổ sung từ pos_categ_ids (Danh mục POS) nếu có
        if hasattr(product, "pos_categ_ids") and product.pos_categ_ids:
            for cat in product.pos_categ_ids:
                if cat.id not in category_ids:
                    category_ids.append(cat.id)
                    categories.append({"id": cat.id, "name": cat.name})

        # 3. Fallback sang product.categ_id (Danh mục nội bộ Odoo) nếu chưa có
        if not category_ids and product.categ_id:
            category_ids.append(product.categ_id.id)
            categories.append({"id": product.categ_id.id, "name": product.categ_id.name})

        category = categories[0] if categories else None

        # Lấy promotional price từ batch_prices dict nếu có
        promotional_price = None
        if batch_prices and isinstance(batch_prices, dict):
            promo = batch_prices.get(product.id)
            if promo and promo != product.x_zalo_price:
                promotional_price = promo
        else:
            # Fallback: query riêng lẻ (giữ compatible với product_detail)
            try:
                pricelist = request.env["product.pricelist"].sudo().search([
                    ("active", "=", True),
                ], limit=1, order="id")
                if pricelist:
                    promo = pricelist._get_product_price(product, quantity=1.0)
                    if promo and promo != product.x_zalo_price:
                        promotional_price = promo
            except Exception:
                pass

        img_url = None
        if product.image_128:
            img_url = self._get_image_url("product.product", product.id, "image_128", write_date=product.write_date or product.create_date)


        # Sales count từ đơn hàng Zalo Mini App
        sales_count = 0
        if batch_sales_counts and isinstance(batch_sales_counts, dict):
            sales_count = batch_sales_counts.get(product.id, 0)
        else:
            try:
                counts = self._get_batch_sales_counts([product])
                sales_count = counts.get(product.id, 0)
            except Exception:
                sales_count = 0

        create_date = fields.Datetime.to_string(product.create_date) if product.create_date else None

        # Thu thập thông tin Thương hiệu (Brand) từ các trường thương hiệu Odoo
        brand_name = ""
        for b_field in ["brand_id", "product_brand_id", "x_brand_id", "x_brand", "brand", "brand_name"]:
            try:
                if hasattr(product, b_field) and getattr(product, b_field):
                    val = getattr(product, b_field)
                    brand_name = val.name if hasattr(val, "name") else str(val)
                    break
                elif product.product_tmpl_id and hasattr(product.product_tmpl_id, b_field) and getattr(product.product_tmpl_id, b_field):
                    val = getattr(product.product_tmpl_id, b_field)
                    brand_name = val.name if hasattr(val, "name") else str(val)
                    break
            except Exception:
                pass

        # Lấy nội dung bài viết HTML / Rich Text trong mục PRODUCT INFORMATION của Odoo
        product_info_html = ""
        for html_field in ["website_description", "description", "x_product_information", "x_description", "description_sale"]:
            try:
                if hasattr(product, html_field) and getattr(product, html_field):
                    val = getattr(product, html_field)
                    if val:
                        product_info_html = str(val)
                        break
                elif product.product_tmpl_id and hasattr(product.product_tmpl_id, html_field) and getattr(product.product_tmpl_id, html_field):
                    val = getattr(product.product_tmpl_id, html_field)
                    if val:
                        product_info_html = str(val)
                        break
            except Exception:
                pass

        if product_info_html:
            product_info_html = html.unescape(product_info_html)

        return {
            "id": product.id,
            "template_id": product.product_tmpl_id.id,
            "name": product.display_name,
            "template_name": product.product_tmpl_id.name,
            "brand": brand_name,
            "default_code": product.default_code,
            "barcode": product.barcode,
            "x_zalo_price": product.x_zalo_price or 0.0,
            "list_price": product.list_price,
            "promotional_price": promotional_price,
            "free_qty": product.free_qty or 0.0,
            "uom": product.uom_id.name if product.uom_id else "",
            "weight": product.weight or 0.0,
            "sales_count": sales_count,
            "create_date": create_date,
            "category": category,
            "category_ids": category_ids,
            "categories": categories,
            "attributes": attributes,
            "image_url": img_url,
            "images": self._get_product_images(product),
            "product_info_html": product_info_html,
            "description": product.description_sale or "",
            "description_html": product.description or "",
        }

    def _get_batch_prices(self, products):
        """Batch query pricelist prices cho tất cả products.
        Trả về dict {product_id: promotional_price} hoặc None nếu không có pricelist."""
        try:
            pricelist = request.env["product.pricelist"].sudo().search([
                ("active", "=", True),
            ], limit=1, order="id")
            if not pricelist:
                return None

            batch_prices = {}
            for p in products:
                try:
                    promo = pricelist._get_product_price(p, quantity=1.0)
                    if promo:
                        batch_prices[p.id] = promo
                except Exception:
                    pass
            return batch_prices if batch_prices else None
        except Exception as e:
            _logger.warning("Batch price error: %s", e)
            return None

    def _get_batch_sales_counts(self, products):
        """Batch query số lượng đã bán cho tất cả products từ các đơn hàng không bị hủy.
        Trả về dict {product_id: sales_count} hoặc {} nếu không có data."""
        try:
            if hasattr(products, "ids"):
                product_ids = products.ids
            elif isinstance(products, (list, tuple)):
                product_ids = [p.id if hasattr(p, "id") else p for p in products if p]
            else:
                product_ids = []

            if not product_ids:
                return {}

            batch_counts = {}
            lines = request.env["sale.order.line"].sudo().search([
                ("product_id", "in", product_ids),
                ("order_id.state", "!=", "cancel"),
            ])
            for line in lines:
                pid = line.product_id.id
                if pid:
                    batch_counts[pid] = batch_counts.get(pid, 0) + int(line.product_uom_qty)

            for p in products:
                pid = p.id if hasattr(p, "id") else p
                if pid not in batch_counts or batch_counts[pid] == 0:
                    if hasattr(p, "sales_count") and p.sales_count:
                        batch_counts[pid] = int(p.sales_count)

            return batch_counts
        except Exception as e:
            _logger.warning("Batch sales count error: %s", e)
            return {}

    # =========================================================================
    # POST /api/v1/zalo/products/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/list",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def product_list(self, **params):
        """Danh sách sản phẩm (variant) với sort/filter/query.
        Body: {"limit":10, "offset":0, "query":"áo", "sort":"name", "category_id":0,
               "min_price":10000, "max_price":500000, "in_stock":true}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            try:
                limit, offset = self._parse_limit_offset(body, default_limit=20, max_limit=100)
            except ValueError as e:
                return self._response_error("INVALID_INPUT", str(e))

            query = (body.get("query") or "").strip()
            sort = (body.get("sort") or "name").strip()
            category_id = self._parse_int(body.get("category_id"), 0)
            min_price = self._parse_float(body.get("min_price"), 0.0)
            max_price = self._parse_float(body.get("max_price"), 0.0)
            in_stock = body.get("in_stock", False)
            # Convert boolean: accept both bool and string
            if isinstance(in_stock, str):
                in_stock = in_stock.lower() in ("true", "1", "yes")
            in_stock = bool(in_stock)

            domain = [
                ("x_active_zalo", "=", True),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]

            if category_id:
                cat_ids = request.env["pos.category"].sudo().search([("id", "child_of", category_id)]).ids
                if hasattr(request.env["product.product"], "pos_categ_ids"):
                    domain += [
                        "|",
                        ("x_zalo_categ_ids", "in", cat_ids),
                        ("pos_categ_ids", "in", cat_ids),
                    ]
                else:
                    domain.append(("x_zalo_categ_ids", "in", cat_ids))

            # Lọc theo khoảng giá
            if min_price > 0:
                domain.append(("x_zalo_price", ">=", min_price))
            if max_price > 0:
                domain.append(("x_zalo_price", "<=", max_price))

            # Lọc theo tồn kho
            if in_stock:
                domain.append(("free_qty", ">", 0.0))

            if query:
                domain += [
                    "|",
                    ("name", "ilike", query),
                    "|",
                    ("default_code", "ilike", query),
                    ("barcode", "ilike", query),
                ]

            sort_map = {
                "name": "name",
                "-name": "name desc",
                "x_zalo_price": "x_zalo_price",
                "-x_zalo_price": "x_zalo_price desc",
                "create_date": "create_date",
                "-create_date": "create_date desc",
                "list_price": "list_price",
                "-list_price": "list_price desc",
            }
            order = sort_map.get(sort, "name")

            products = request.env["product.product"].sudo().search(
                domain, limit=limit, offset=offset, order=order
            )
            total = request.env["product.product"].sudo().search_count(domain)

            # Batch query pricelist & sales counts 1 lần cho tất cả products
            batch_prices = self._get_batch_prices(products)
            batch_sales_counts = self._get_batch_sales_counts(products)
            data = [
                self._build_product_data(p, batch_prices=batch_prices, batch_sales_counts=batch_sales_counts)
                for p in products
            ]

            return self._response_success_cached({
                "total": total,
                "limit": limit,
                "offset": offset,
                "products": data,
            }, max_age=120)  # cache 2 phút
        except Exception as e:
            _logger.exception("product_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/products/detail
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/detail",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def product_detail(self, **params):
        """Chi tiết sản phẩm (variant).
        Body: {"product_id": 1}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            product_id = self._parse_int(body.get("product_id"), 0)
            if not product_id:
                return self._response_error("INVALID_INPUT", "Thiếu product_id")

            product = request.env["product.product"].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            if not product.x_active_zalo:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            # product_detail dùng fallback single query (batch_prices=None)
            data = self._build_product_data(product, batch_prices=None)

            data["description_full"] = product.description or ""
            data["standard_price"] = product.standard_price
            data["volume"] = product.volume or 0.0

            return self._response_success_cached(data, max_age=120)
        except Exception as e:
            _logger.exception("product_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/products/update-price
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/update-price",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def product_update_price(self, **params):
        """Cập nhật giá sản phẩm (x_zalo_price, list_price, standard_price).
        Auth: Bearer token required.
        Body: {
            "product_id": 42,           # hoặc "template_id": 10
            "x_zalo_price": 25000000,   # optional
            "list_price": 26000000,     # optional
            "standard_price": 20000000  # optional
        }"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            auth_res = self._auth_required()
            if isinstance(auth_res, Response):
                return auth_res

            body = self._request_json()
            product_id = self._parse_int(body.get("product_id"), 0)
            template_id = self._parse_int(body.get("template_id"), 0)

            if product_id:
                product = request.env["product.product"].sudo().browse(product_id)
            elif template_id:
                tmpl = request.env["product.template"].sudo().browse(template_id)
                product = tmpl.product_variant_id if tmpl.exists() else request.env["product.product"]
            else:
                return self._response_error("INVALID_INPUT", "Thiếu product_id hoặc template_id")

            if not product.exists() or not product.active:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại hoặc đã bị vô hiệu hóa", 404)

            vals = {}
            if "x_zalo_price" in body:
                x_zalo_price = self._parse_float(body.get("x_zalo_price"), -1.0)
                if x_zalo_price < 0:
                    return self._response_error("INVALID_INPUT", "x_zalo_price không được nhỏ hơn 0")
                vals["x_zalo_price"] = x_zalo_price

            if "list_price" in body:
                list_price = self._parse_float(body.get("list_price"), -1.0)
                if list_price < 0:
                    return self._response_error("INVALID_INPUT", "list_price không được nhỏ hơn 0")
                vals["list_price"] = list_price

            if "standard_price" in body:
                standard_price = self._parse_float(body.get("standard_price"), -1.0)
                if standard_price < 0:
                    return self._response_error("INVALID_INPUT", "standard_price không được nhỏ hơn 0")
                vals["standard_price"] = standard_price

            if not vals:
                return self._response_error(
                    "INVALID_INPUT",
                    "Cần truyền ít nhất một trường giá để cập nhật (x_zalo_price, list_price, standard_price)"
                )

            product.sudo().write(vals)

            return self._response_success({
                "id": product.id,
                "template_id": product.product_tmpl_id.id,
                "name": product.display_name,
                "default_code": product.default_code,
                "x_zalo_price": product.x_zalo_price or 0.0,
                "list_price": product.list_price or 0.0,
                "standard_price": product.standard_price or 0.0,
                "message": "Cập nhật giá sản phẩm thành công",
            })
        except Exception as e:
            _logger.exception("product_update_price error")
            return self._response_error("SERVER_ERROR", str(e), 500)