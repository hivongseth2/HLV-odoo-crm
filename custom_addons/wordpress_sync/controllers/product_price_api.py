# -*- coding: utf-8 -*-
import json
import logging
import re
from hmac import compare_digest

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class WordPressProductPriceAPI(http.Controller):
    PRICE_FIELDS = {
        "list_price",
        "x_studio_ga_hng_nim_yt",
        "x_studio_ga_web",
        "x_studio_gia_san_tmdt",
        "x_studio_gi_bn_thng_mi",
        "x_wp_combo_price",
    }

    PRICE_ALIASES = {
        "sale_price": "list_price",
        "price_sale": "list_price",
        "price_listed": "x_studio_ga_hng_nim_yt",
        "listed_price": "x_studio_ga_hng_nim_yt",
        "price_web": "x_studio_ga_web",
        "web_price": "x_studio_ga_web",
        "price_tmdt": "x_studio_gia_san_tmdt",
        "floor_ecommerce_price": "x_studio_gia_san_tmdt",
        "price_commercial": "x_studio_gi_bn_thng_mi",
        "commercial_price": "x_studio_gi_bn_thng_mi",
        "combo_price": "x_wp_combo_price",
        "wp_combo_price": "x_wp_combo_price",
    }

    TOKEN_PARAM = "wordpress_sync.price_update_api_token"

    @http.route(
        "/api/wordpress_sync/product/prices",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def update_product_prices(self, **kwargs):
        if request.httprequest.method == "OPTIONS":
            return self._json_response({"ok": True})

        payload = self._request_payload(kwargs)
        token_error = self._validate_token(payload)
        if token_error:
            return self._json_response(token_error, status=401)

        items = self._payload_items(payload)
        if not items:
            return self._json_response(
                {"ok": False, "error": "missing_products", "message": "Missing product data."},
                status=400,
            )

        Product = request.env["product.template"].sudo()
        results = []

        for item in items:
            result = self._update_one(Product, item)
            results.append(result)

        has_error = any(not result.get("ok") for result in results)
        status = 207 if has_error and len(results) > 1 else (400 if has_error else 200)
        return self._json_response(
            {
                "ok": not has_error,
                "count": len(results),
                "updated_count": sum(1 for result in results if result.get("updated")),
                "results": results,
            },
            status=status,
        )

    def _update_one(self, Product, item):
        product, error = self._find_product(Product, item)
        if error:
            return error

        vals, invalid = self._price_vals(Product, item)
        if invalid:
            return self._item_error(product, invalid["error"], invalid["message"])

        if not vals:
            return self._item_error(product, "missing_price_fields", "No supported price fields found.")

        changed_vals = {
            field: value
            for field, value in vals.items()
            if self._normalize_existing(product[field]) != value
        }

        if changed_vals:
            before = {field: product[field] for field in changed_vals}
            try:
                product.write(changed_vals)
            except Exception as exc:
                _logger.exception("WordPress price API failed for product %s", product.id)
                return self._item_error(product, "write_failed", str(exc))
        else:
            before = {}

        queue = request.env["wordpress.sync.queue"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("sync_type", "=", "price"),
                ("status", "in", ["pending", "failed"]),
            ],
            order="write_date desc, create_date desc",
            limit=1,
        )
        config = product._get_wordpress_config()

        return {
            "ok": True,
            "updated": bool(changed_vals),
            "product_id": product.id,
            "name": product.display_name,
            "sku": product.default_code or "",
            "changed_fields": list(changed_vals.keys()),
            "before": before,
            "after": {field: product[field] for field in vals},
            "auto_sync_price": bool(config and config.auto_sync_price),
            "queued": bool(queue),
            "queue_id": queue.id or False,
            "queue_status": queue.status or False,
        }

    def _find_product(self, Product, item):
        product_id = item.get("product_id") or item.get("template_id") or item.get("odoo_id") or item.get("id")
        if product_id:
            try:
                product = Product.browse(int(product_id))
            except (TypeError, ValueError):
                return None, self._item_error(None, "invalid_product_id", "Invalid product_id.")
            if product.exists():
                return product, None
            return None, self._item_error(None, "product_not_found", "Product ID not found.")

        sku = (item.get("sku") or item.get("default_code") or "").strip()
        if sku:
            found = Product.search([("default_code", "=", sku)], limit=2)
            if not found:
                variants = request.env["product.product"].sudo().search([("default_code", "=", sku)], limit=2)
                found = variants.mapped("product_tmpl_id")
            return self._single_match(found, "sku", sku)

        barcode = (item.get("barcode") or "").strip()
        if barcode:
            found = Product.browse()
            if "barcode" in Product._fields:
                found = Product.search([("barcode", "=", barcode)], limit=2)
            if not found:
                variants = request.env["product.product"].sudo().search([("barcode", "=", barcode)], limit=2)
                found = variants.mapped("product_tmpl_id")
            return self._single_match(found, "barcode", barcode)

        return None, self._item_error(None, "missing_product_key", "Missing product_id, sku, default_code, or barcode.")

    def _single_match(self, records, key_name, key_value):
        if len(records) == 1:
            return records[0], None
        if not records:
            return None, self._item_error(None, "product_not_found", "Product not found.", {key_name: key_value})
        return None, self._item_error(None, "ambiguous_product", "More than one product matched.", {key_name: key_value})

    def _price_vals(self, Product, item):
        raw_values = {}
        prices = item.get("prices")
        if isinstance(prices, dict):
            raw_values.update(prices)

        for key, value in item.items():
            target = self.PRICE_ALIASES.get(key, key)
            if target in self.PRICE_FIELDS:
                raw_values[target] = value

        vals = {}
        supported_fields = self.PRICE_FIELDS.intersection(Product._fields)
        for field, value in raw_values.items():
            target = self.PRICE_ALIASES.get(field, field)
            if target not in supported_fields:
                continue
            parsed, error = self._parse_price(value)
            if error:
                return {}, {
                    "error": "invalid_price",
                    "message": f"Invalid value for {target}: {value!r}",
                }
            vals[target] = parsed
        return vals, None

    def _parse_price(self, value):
        if isinstance(value, bool) or value is None:
            return None, True
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            cleaned = re.sub(r"[^\d,.\-]", "", value.strip())
            if not cleaned:
                return None, True
            if "," in cleaned and "." in cleaned:
                if cleaned.rfind(",") > cleaned.rfind("."):
                    cleaned = cleaned.replace(".", "").replace(",", ".")
                else:
                    cleaned = cleaned.replace(",", "")
            elif "," in cleaned:
                left, right = cleaned.rsplit(",", 1)
                cleaned = left + right if len(right) == 3 else left + "." + right
            elif "." in cleaned:
                left, right = cleaned.rsplit(".", 1)
                cleaned = left + right if len(right) == 3 else cleaned
            try:
                number = float(cleaned)
            except ValueError:
                return None, True
        else:
            return None, True

        if number < 0:
            return None, True
        return number, None

    def _normalize_existing(self, value):
        if value is False or value is None:
            return 0.0
        return float(value)

    def _payload_items(self, payload):
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        products = payload.get("products") or payload.get("items")
        if isinstance(products, list):
            return [item for item in products if isinstance(item, dict)]
        return [payload]

    def _request_payload(self, kwargs):
        payload = dict(kwargs or {})
        raw = request.httprequest.get_data(cache=False, as_text=True) or ""
        if raw:
            try:
                parsed = json.loads(raw)
                return parsed
            except Exception:
                _logger.debug("WordPress price API received non-JSON body: %s", raw[:200])
        return payload

    def _validate_token(self, payload):
        expected = self._clean_token(
            request.env["ir.config_parameter"].sudo().get_param(self.TOKEN_PARAM) or ""
        )
        if not expected:
            return {
                "ok": False,
                "error": "api_token_not_configured",
                "message": f"Missing Odoo system parameter {self.TOKEN_PARAM}.",
            }

        token = ""
        if isinstance(payload, dict):
            token = payload.get("token") or ""
        token = (
            token
            or request.httprequest.headers.get("X-WordPress-Sync-Token")
            or request.httprequest.headers.get("X-API-Key")
            or self._bearer_token()
        )

        if not compare_digest(self._clean_token(token), expected):
            return {"ok": False, "error": "invalid_token", "message": "Invalid token."}
        return None

    def _bearer_token(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:]
        return ""

    def _clean_token(self, token):
        return re.sub(r"[\u200B-\u200D\uFEFF]", "", (token or "").strip())

    def _item_error(self, product, error, message, extra=None):
        data = {
            "ok": False,
            "updated": False,
            "error": error,
            "message": message,
        }
        if product:
            data.update(
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "sku": product.default_code or "",
                }
            )
        if extra:
            data.update(extra)
        return data

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False, default=str),
            status=status,
            content_type="application/json; charset=utf-8",
            headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "POST, OPTIONS"),
                (
                    "Access-Control-Allow-Headers",
                    "Content-Type, Authorization, X-WordPress-Sync-Token, X-API-Key",
                ),
            ],
        )
