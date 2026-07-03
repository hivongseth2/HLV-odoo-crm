# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
from datetime import timedelta, timezone
from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request, Response


_logger = logging.getLogger(__name__)


class ZaloMiniAppAPI(http.Controller):
    """Zalo Mini App API endpoints described in docs/api.md.

    This controller intentionally focuses on practical interoperability with
    existing Odoo data models so Mini App can call directly.
    """

    # ----------------------------
    # Helpers
    # ----------------------------

    @staticmethod
    def _response_success(data=None, status=200):
        payload = {"success": True, "data": data or {}}
        return Response(json.dumps(payload, default=str), status=status, content_type="application/json")

    @staticmethod
    def _response_error(code, message, status=400):
        payload = {
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
        return Response(json.dumps(payload, default=str), status=status, content_type="application/json")

    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _parse_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _parse_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

    @staticmethod
    def _normalize_vn_phone(phone):
        if not phone:
            return ""
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) == 11 and digits.startswith("84"):
            digits = "0" + digits[2:]
        elif len(digits) == 12 and digits.startswith("084"):
            digits = "0" + digits[3:]
        return digits

    @staticmethod
    def _mask_phone(phone):
        normalized = ZaloMiniAppAPI._normalize_vn_phone(phone)
        return "***%s" % normalized[-3:] if normalized else ""

    @staticmethod
    def _vn_datetime(value):
        if not value:
            return None
        dt = fields.Datetime.to_datetime(value)
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=7))).replace(microsecond=0).isoformat()

    @staticmethod
    def _img_url(model, rec_id, field_name="image_1920"):
        if not rec_id:
            return ""
        return "/web/image/%s/%s/%s" % (model, rec_id, field_name)

    @staticmethod
    def _api_image_url(product_id, field_name):
        return "/api/v1/products/%s/image/%s" % (product_id, field_name)

    @staticmethod
    def _partner_image_url(partner_id):
        return "/api/v1/loyalty/partners/%s/image" % partner_id

    @staticmethod
    def _product_images(product):
        """Return all product images: original Odoo image + multi-images"""
        images = []
        
        # Add original Odoo image (image_1920) as base image
        if "image_1920" in product._fields and getattr(product, "image_1920", None):
            images.append(ZaloMiniAppAPI._api_image_url(product.id, "image_1920"))
        
        # Add multi-images (image_1 through image_5)
        image_fields = ["image_1", "image_2", "image_3", "image_4", "image_5"]
        for field_name in image_fields:
            if field_name in product._fields and getattr(product, field_name, None):
                images.append(ZaloMiniAppAPI._api_image_url(product.id, field_name))
        
        return images

    @staticmethod
    def _guess_image_mimetype(raw_bytes):
        if raw_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if raw_bytes.startswith(b"GIF87a") or raw_bytes.startswith(b"GIF89a"):
            return "image/gif"
        if raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _studio_price(product):
        value = getattr(product, "x_studio_gia_san_tmdt", None)
        return float(value or 0.0)

    @staticmethod
    def _studio_original_price(product):
        value = getattr(product, "x_studio_ga_hng_nim_yt", None)
        return float(value or 0.0)

    @staticmethod
    def _record_brief(record):
        return {
            "id": record.id,
            "name": record.display_name if hasattr(record, "display_name") else record.name,
        }

    @staticmethod
    def _many2many_brief(records):
        return [ZaloMiniAppAPI._record_brief(record) for record in records]

    @staticmethod
    def _free_stock_qty(product):
        variants = product.product_variant_ids or product.product_variant_id
        variant_ids = variants.ids if hasattr(variants, "ids") else [variants.id]
        if not variant_ids:
            return 0.0

        quant_model = request.env["stock.quant"].sudo()
        stock_location_ids = request.env["stock.location"].sudo().search([
            ("usage", "=", "internal"),
        ]).ids
        if not stock_location_ids:
            return 0.0

        grouped = quant_model.read_group(
            [
                ("product_id", "in", variant_ids),
                ("location_id", "in", stock_location_ids),
            ],
            ["quantity:sum", "reserved_quantity:sum"],
            ["product_id"],
            lazy=False,
        )
        total_free = 0.0
        for row in grouped:
            total_qty = float(row.get("quantity_sum") or row.get("quantity") or 0.0)
            reserved_qty = float(row.get("reserved_quantity_sum") or row.get("reserved_quantity") or 0.0)
            total_free += max(total_qty - reserved_qty, 0.0)
        return total_free

    @staticmethod
    def _partner_tier_dict(tier):
        if not tier:
            return None
        return {
            "id": tier.id,
            "name": tier.name,
            "min_points": tier.min_points,
            "max_points": tier.max_points or None,
            "color": tier.color,
            "icon": tier.icon,
            "description": tier.description or "",
            "badge_color": tier.badge_color,
            "image_url": tier.image_url,
            "benefits": [{"id": b.id, "name": b.name, "icon": b.icon or ""} for b in tier.benefit_ids],
        }

    def _partner_from_param(self, params=None):
        params = params or {}
        partner_id = params.get("partner_id") or request.httprequest.args.get("partner_id")
        phone = params.get("phone") or request.httprequest.args.get("phone")
        path = request.httprequest.path
        if not partner_id or not phone:
            _logger.warning(
                "Zalo MiniApp partner guard failed: missing partner_id/phone path=%s has_partner_id=%s has_phone=%s",
                path,
                bool(partner_id),
                bool(phone),
            )
            return None

        try:
            partner = request.env["res.partner"].sudo().browse(int(partner_id))
        except Exception:
            _logger.warning(
                "Zalo MiniApp partner guard failed: invalid partner_id=%s phone=%s path=%s",
                partner_id,
                self._mask_phone(phone),
                path,
            )
            return None
        if not partner.exists():
            _logger.warning(
                "Zalo MiniApp partner guard failed: partner not found partner_id=%s phone=%s path=%s",
                partner_id,
                self._mask_phone(phone),
                path,
            )
            return None

        root = partner._get_loyalty_root()
        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            _logger.warning(
                "Zalo MiniApp partner guard failed: invalid phone partner_id=%s phone=%s path=%s",
                partner_id,
                self._mask_phone(phone),
                path,
            )
            return None

        accounts = request.env["hlv.loyalty.portal.account"].sudo().search([
            ("portal_phone", "=", normalized),
            ("active", "=", True),
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == root.id)[:1]
        if not account:
            _logger.warning(
                "Zalo MiniApp partner guard failed: portal account mismatch partner_id=%s root_id=%s phone=%s path=%s",
                partner_id,
                root.id,
                self._mask_phone(phone),
                path,
            )
            return None
        return root

    def _partner_from_phone(self, phone):
        normalized = self._normalize_vn_phone(phone)
        if not normalized:
            return None

        account = request.env["hlv.loyalty.portal.account"].sudo().search([
            ("portal_phone", "=", normalized),
            ("active", "=", True),
        ], order="id desc", limit=1)
        if account:
            return account.partner_id._get_loyalty_root()
        return None

    @staticmethod
    def _session_default_address_key(partner_id):
        return "zalo_default_address_%s" % partner_id

    def _get_default_address_id(self, partner):
        key = self._session_default_address_key(partner.id)
        value = request.session.get(key)
        try:
            return int(value) if value else 0
        except Exception:
            return 0

    def _set_default_address_id(self, partner, address_id):
        key = self._session_default_address_key(partner.id)
        request.session[key] = int(address_id) if address_id else 0

    @staticmethod
    def _voucher_to_dict(voucher):
        return {
            "id": voucher.id,
            "code": voucher.code,
            "state": voucher.state,
            "reward_type": voucher.reward_type,
            "discount_type": voucher.discount_type,
            "discount_value": voucher.discount_value,
            "max_discount_amount": voucher.max_discount_amount,
            "gift_product_id": voucher.gift_product_id.id if voucher.gift_product_id else None,
            "gift_product_name": voucher.gift_product_id.display_name if voucher.gift_product_id else "",
            "gift_qty": voucher.gift_qty,
            "min_order_amount": voucher.min_order_amount,
            "apply_on": voucher.apply_on,
            "date_issued": ZaloMiniAppAPI._vn_datetime(voucher.date_issued),
            "date_expiry": ZaloMiniAppAPI._vn_datetime(voucher.date_expiry),
            "package_name": voucher.package_id.name if voucher.package_id else "",
        }

    @staticmethod
    def _order_line_to_dict(line):
        return {
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.display_name,
            "product_image": ZaloMiniAppAPI._img_url("product.product", line.product_id.id),
            "quantity": line.product_uom_qty,
            "price_unit": line.price_unit,
            "price_subtotal": line.price_subtotal,
        }

    @staticmethod
    def _order_to_dict(order, include_shipping=True):
        ship_partner = order.partner_shipping_id or order.partner_id
        return {
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "date_order": ZaloMiniAppAPI._vn_datetime(order.date_order),
            "amount_total": order.amount_total,
            "amount_tax": order.amount_tax,
            "voucher_code": order.loyalty_voucher_code or None,
            "items": [ZaloMiniAppAPI._order_line_to_dict(line) for line in order.order_line.filtered(lambda l: not l.display_type)],
            "shipping_address": {
                "name": ship_partner.name,
                "phone": ship_partner.phone or ship_partner.mobile or "",
                "street": ship_partner.street or "",
                "ward": ship_partner.street2 or "",
                "district": "",
                "city": ship_partner.city or "",
            } if include_shipping else None,
        }

    def _get_cart_order(self, partner, create_if_missing=False):
        order_model = request.env["sale.order"].sudo()
        domain = [
            ("partner_id", "child_of", partner.id),
            ("state", "=", "draft"),
        ]
        cart = order_model.search(domain, order="write_date desc, id desc", limit=1)
        if cart or not create_if_missing:
            return cart

        shipping = partner
        default_address_id = self._get_default_address_id(partner)
        if default_address_id:
            shipping_candidate = request.env["res.partner"].sudo().browse(default_address_id)
            if shipping_candidate.exists() and shipping_candidate.parent_id.id == partner.id:
                shipping = shipping_candidate

        return order_model.create({
            "partner_id": partner.id,
            "partner_invoice_id": partner.id,
            "partner_shipping_id": shipping.id,
            "note": "",
        })

    def _upsert_cart_line(self, cart, product, quantity):
        line = cart.order_line.filtered(lambda l: not l.display_type and l.product_id.id == product.id)[:1]
        price = getattr(product.product_tmpl_id, "x_studio_gia_san_tmdt", None)
        if not price:
            price = product.list_price
        if line:
            line.write({"product_uom_qty": quantity, "price_unit": price})
            return line
        return request.env["sale.order.line"].sudo().create({
            "order_id": cart.id,
            "product_id": product.id,
            "product_uom_qty": quantity,
            "price_unit": price,
            "name": product.display_name,
        })

    @staticmethod
    def _history_to_dict(history):
        return {
            "id": history.id,
            "date": ZaloMiniAppAPI._vn_datetime(history.date),
            "point_amount": history.point_amount,
            "transaction_type": history.transaction_type,
            "description": history.description or "",
        }

    # ----------------------------
    # 1. Auth
    # ----------------------------

    @http.route("/api/v1/auth/zalo", type="http", auth="public", methods=["POST"], csrf=False)
    def auth_zalo(self, **kwargs):
        payload = self._request_json()
        access_token = (payload.get("access_token") or "").strip()
        user_id = (payload.get("user_id") or "").strip()
        phone = payload.get("phone") or ""
        if not access_token or not user_id:
            _logger.warning(
                "Zalo MiniApp auth failed: missing access_token/user_id has_access_token=%s has_user_id=%s phone=%s",
                bool(access_token),
                bool(user_id),
                self._mask_phone(phone),
            )
            return self._response_error("INVALID_INPUT", "access_token and user_id are required", status=400)
        if not phone:
            _logger.warning("Zalo MiniApp auth failed: missing phone has_user_id=%s", bool(user_id))
            return self._response_error("INVALID_INPUT", "phone is required", status=400)

        normalized_phone = self._normalize_vn_phone(phone)
        partner_model = request.env["res.partner"].sudo()
        partner = self._partner_from_phone(phone)
        if not partner:
            _logger.warning("Zalo MiniApp auth failed: partner not found phone=%s", self._mask_phone(phone))
            return self._response_error("PARTNER_NOT_FOUND", "No active loyalty portal account found for phone", status=404)

        root = partner._get_loyalty_root()
        bind_vals = {}
        clear_vals = {}
        binding_domain = [
            ("id", "!=", root.id),
            ("ref", "=", user_id),
        ]
        if "zalo_user_id" in partner_model._fields:
            bind_vals["zalo_user_id"] = user_id
            clear_vals["zalo_user_id"] = False
            binding_domain = [
                ("id", "!=", root.id),
                "|",
                ("zalo_user_id", "=", user_id),
                ("ref", "=", user_id),
            ]
        elif "x_zalo_user_id" in partner_model._fields:
            bind_vals["x_zalo_user_id"] = user_id
            clear_vals["x_zalo_user_id"] = False
            binding_domain = [
                ("id", "!=", root.id),
                "|",
                ("x_zalo_user_id", "=", user_id),
                ("ref", "=", user_id),
            ]
        else:
            bind_vals["ref"] = user_id
        clear_vals["ref"] = False
        if bind_vals:
            partner_model.search(binding_domain).write(clear_vals)
            root.write(bind_vals)
        _logger.info("Zalo MiniApp auth success: partner_id=%s phone=%s", root.id, self._mask_phone(phone))

        loyalty_root = root._get_loyalty_root()

        api_key = request.env["ir.config_parameter"].sudo().get_param("hlv_loyalty.zalo_api_key", "")

        return self._response_success({
            "api_key": api_key or None,
            "partner_id": root.id,
            "name": root.name,
            "phone": normalized_phone,
            "email": root.email or "",
            "avatar": self._img_url("res.partner", root.id),
            "loyalty_points": loyalty_root.loyalty_total_points,
            "exchange_points": loyalty_root.loyalty_exchange_points,
            "pending_reward_points": loyalty_root.loyalty_reward_pending_points,
            "exchange_points_available": loyalty_root.loyalty_exchange_available_points,
            "tier": loyalty_root.loyalty_tier_id.name if loyalty_root.loyalty_tier_id else None,
        })

    @http.route("/api/v1/account", type="http", auth="public", methods=["GET"], csrf=False)
    def account(self, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        loyalty_root = partner._get_loyalty_root()
        addresses = request.env["res.partner"].sudo().search([
            ("parent_id", "=", partner.id),
            ("type", "=", "delivery"),
        ])
        cart = self._get_cart_order(partner, create_if_missing=False)
        return self._response_success({
            "account": {
                "id": partner.id,
                "name": partner.name,
                "phone": partner.phone or partner.mobile or "",
                "email": partner.email or "",
                "avatar": self._partner_image_url(partner),
                "loyalty_points": getattr(loyalty_root, "loyalty_total_points", 0),
                "exchange_points": loyalty_root.loyalty_exchange_points,
                "pending_reward_points": loyalty_root.loyalty_reward_pending_points,
                "exchange_points_available": loyalty_root.loyalty_exchange_available_points,
                "tier": loyalty_root.loyalty_tier_id.name if loyalty_root.loyalty_tier_id else None,
                "tier_image_url": loyalty_root.loyalty_tier_id.image_url if loyalty_root.loyalty_tier_id else "",
                "default_address_id": self._get_default_address_id(partner),
                "address_count": len(addresses),
                "cart_id": cart.id if cart else None,
                "cart_item_count": len(cart.order_line.filtered(lambda l: not l.display_type)) if cart else 0,
            }
        })

    # ----------------------------
    # 2. Products/Categories/Banners
    # ----------------------------

    @http.route("/api/v1/categories", type="http", auth="public", methods=["GET"], csrf=False)
    def list_categories(self, **kwargs):
        parent_id = kwargs.get("parent_id")
        if "product.public.category" in request.env:
            model = request.env["product.public.category"].sudo()
            domain = [("parent_id", "=", int(parent_id))] if parent_id else [("parent_id", "=", False)]
            categories = model.search(domain, order="name asc")
            data = [{
                "id": c.id,
                "name": c.name,
                "image_url": self._img_url("product.public.category", c.id),
                "parent_id": c.parent_id.id if c.parent_id else None,
                "child_count": len(c.child_id),
            } for c in categories]
            return self._response_success({"categories": data})

        model = request.env["product.category"].sudo()
        domain = [("parent_id", "=", int(parent_id))] if parent_id else [("parent_id", "=", False)]
        categories = model.search(domain, order="name asc")
        data = [{
            "id": c.id,
            "name": c.name,
            "image_url": "",
            "parent_id": c.parent_id.id if c.parent_id else None,
            "child_count": len(c.child_id),
        } for c in categories]
        return self._response_success({"categories": data})

    @http.route("/api/v1/products", type="http", auth="public", methods=["GET"], csrf=False)
    def list_products(self, **kwargs):
        page = max(self._parse_int(kwargs.get("page"), 1), 1)
        limit = max(self._parse_int(kwargs.get("limit"), 20), 1)
        offset = (page - 1) * limit

        domain = [("sale_ok", "=", True), ("active", "=", True)]
        search = (kwargs.get("search") or "").strip()
        if search:
            domain.append(("name", "ilike", search))

        category_id = kwargs.get("category_id")
        if category_id:
            domain.append(("categ_id", "=", int(category_id)))

        featured = self._parse_bool(kwargs.get("featured"), False)
        if featured and "website_published" in request.env["product.template"]._fields:
            domain.append(("website_published", "=", True))

        sort_map = {
            "price_asc": "x_studio_gia_san_tmdt asc, id desc" if "x_studio_gia_san_tmdt" in request.env["product.template"]._fields else "list_price asc, id desc",
            "price_desc": "x_studio_gia_san_tmdt desc, id desc" if "x_studio_gia_san_tmdt" in request.env["product.template"]._fields else "list_price desc, id desc",
            "newest": "create_date desc, id desc",
            "best_seller": "sales_count desc, id desc" if "sales_count" in request.env["product.template"]._fields else "id desc",
        }
        order = sort_map.get(kwargs.get("sort"), "id desc")

        model = request.env["product.template"].sudo()
        total = model.search_count(domain)
        products = model.search(domain, offset=offset, limit=limit, order=order)

        def _discount_percent(p):
            price = self._studio_price(p)
            original = self._studio_original_price(p)
            if not original or original < price:
                original = price
            if original and original > price:
                return int(round((original - price) * 100.0 / original, 0))
            return 0

        data = []
        for p in products:
            price = self._studio_price(p)
            original_price = self._studio_original_price(p)
            if not original_price or original_price < price:
                original_price = price
            images = self._product_images(p)
            stock_qty = self._free_stock_qty(p)
            product_tags = self._many2many_brief(p.product_tag_ids) if "product_tag_ids" in p._fields else []
            website_categories = self._many2many_brief(p.public_categ_ids) if "public_categ_ids" in p._fields else []
            data.append({
                "id": p.id,
                "name": p.name,
                "price": price,
                "original_price": original_price,
                "discount_percent": _discount_percent(p),
                "image_url": images[0] if images else "",
                "images": images,
                "sold_count": getattr(p, "sales_count", 0),
                "free_shipping": False,
                "voucher_label": None,
                "gifts": [],
                "stock_available": bool(stock_qty > 0),
                "stock_available_qty": stock_qty,
                "sales_description": p.description_sale or "",
                "tags": product_tags,
                "categories": website_categories,
            })

        return self._response_success({
            "products": data,
            "total": total,
            "page": page,
            "limit": limit,
        })

    @http.route("/api/v1/products/<int:product_id>", type="http", auth="public", methods=["GET"], csrf=False)
    def product_detail(self, product_id, **kwargs):
        product = request.env["product.template"].sudo().browse(product_id)
        if not product.exists():
            return self._response_error("NOT_FOUND", "Product not found", status=404)

        specs = []
        if "attribute_line_ids" in product._fields:
            for line in product.attribute_line_ids:
                specs.append({
                    "name": line.attribute_id.name,
                    "value": ", ".join(line.value_ids.mapped("name")),
                })

        imgs = self._product_images(product)
        price = self._studio_price(product)
        original_price = self._studio_original_price(product)
        if not original_price or original_price < price:
            original_price = price
        discount_percent = int(round((original_price - price) * 100.0 / original_price, 0)) if original_price else 0
        stock_qty = self._free_stock_qty(product)
        product_tags = self._many2many_brief(product.product_tag_ids) if "product_tag_ids" in product._fields else []
        website_categories = self._many2many_brief(product.public_categ_ids) if "public_categ_ids" in product._fields else []

        return self._response_success({
            "product": {
                "id": product.id,
                "name": product.name,
                "price": price,
                "original_price": original_price,
                "discount_percent": discount_percent,
                "image_url": imgs[0] if imgs else self._img_url("product.template", product.id),
                "images": imgs,
                "sold_count": getattr(product, "sales_count", 0),
                "free_shipping": False,
                "voucher_label": None,
                "gifts": [],
                "description": product.description_sale or product.description or "",
                "sales_description": product.description_sale or "",
                "specifications": specs,
                "category_id": product.categ_id.id if product.categ_id else None,
                "category_name": product.categ_id.name if product.categ_id else "",
                "stock_available": bool(stock_qty > 0),
                "stock_available_qty": stock_qty,
                "rating": 0,
                "review_count": 0,
                "tags": product_tags,
                "categories": website_categories,
            }
        })

    @http.route("/api/v1/products/<int:product_id>/image/<string:field_name>", type="http", auth="public", methods=["GET"], csrf=False)
    def product_image(self, product_id, field_name, **kwargs):
        allowed_fields = {"image_1920", "image_1", "image_2", "image_3", "image_4", "image_5"}
        if field_name not in allowed_fields:
            return self._response_error("INVALID_IMAGE_FIELD", "Unsupported image field", status=400)

        product = request.env["product.template"].sudo().browse(product_id)
        if not product.exists() or field_name not in product._fields:
            return self._response_error("NOT_FOUND", "Product or image field not found", status=404)

        encoded = getattr(product, field_name)
        if not encoded and field_name != "image_1920":
            encoded = product.image_1920

        if not encoded:
            return self._response_error("IMAGE_NOT_FOUND", "Image is empty", status=404)

        try:
            raw = base64.b64decode(encoded)
        except Exception:
            return self._response_error("IMAGE_DECODE_ERROR", "Unable to decode image", status=500)

        return Response(raw, status=200, content_type=self._guess_image_mimetype(raw))

    @http.route("/api/v1/banners", type="http", auth="public", methods=["GET"], csrf=False)
    def banners(self, **kwargs):
        # Keep a stable contract for Mini App; integrate with a custom banner model later.
        return self._response_success({"banners": []})

    @http.route("/api/v1/cart", type="http", auth="public", methods=["GET"], csrf=False)
    def cart_get(self, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        cart = self._get_cart_order(partner, create_if_missing=False)
        if not cart:
            return self._response_success({
                "cart": {
                    "id": None,
                    "name": None,
                    "state": "draft",
                    "amount_total": 0,
                    "amount_tax": 0,
                    "items": [],
                    "item_count": 0,
                    "shipping_address": None,
                    "voucher_code": None,
                }
            })

        items = [self._order_line_to_dict(line) for line in cart.order_line.filtered(lambda l: not l.display_type)]
        payload = self._order_to_dict(cart)
        payload["item_count"] = len(items)
        payload["state"] = "draft"
        return self._response_success({"cart": payload})

    @http.route("/api/v1/cart/items", type="http", auth="public", methods=["POST"], csrf=False)
    def cart_add_item(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        product_id = self._parse_int(payload.get("product_id"), 0)
        quantity = self._parse_float(payload.get("quantity"), 0)
        if product_id <= 0 or quantity <= 0:
            return self._response_error("INVALID_INPUT", "product_id and quantity are required", status=400)

        product = request.env["product.product"].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return self._response_error("INVALID_PRODUCT", "Product not found", status=404)

        cart = self._get_cart_order(partner, create_if_missing=True)
        line = self._upsert_cart_line(cart, product, quantity)
        return self._response_success({
            "cart": self._order_to_dict(cart),
            "line": self._order_line_to_dict(line),
        }, status=201)

    @http.route("/api/v1/cart/items/<int:line_id>", type="http", auth="public", methods=["PUT"], csrf=False)
    def cart_update_item(self, line_id, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        cart = self._get_cart_order(partner, create_if_missing=False)
        if not cart:
            return self._response_error("NOT_FOUND", "Cart not found", status=404)

        line = cart.order_line.filtered(lambda l: not l.display_type and l.id == line_id)[:1]
        if not line:
            return self._response_error("NOT_FOUND", "Cart item not found", status=404)

        quantity = self._parse_float(payload.get("quantity"), 0)
        if quantity <= 0:
            line.unlink()
        else:
            line.write({"product_uom_qty": quantity})
        return self._response_success({"cart": self._order_to_dict(cart)})

    @http.route("/api/v1/cart/items/<int:line_id>", type="http", auth="public", methods=["DELETE"], csrf=False)
    def cart_delete_item(self, line_id, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        cart = self._get_cart_order(partner, create_if_missing=False)
        if not cart:
            return self._response_error("NOT_FOUND", "Cart not found", status=404)

        line = cart.order_line.filtered(lambda l: not l.display_type and l.id == line_id)[:1]
        if not line:
            return self._response_error("NOT_FOUND", "Cart item not found", status=404)
        line.unlink()
        return self._response_success({"cart": self._order_to_dict(cart)})

    @http.route("/api/v1/cart/clear", type="http", auth="public", methods=["POST"], csrf=False)
    def cart_clear(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        cart = self._get_cart_order(partner, create_if_missing=False)
        if not cart:
            return self._response_success({"cart": {"id": None, "items": [], "amount_total": 0, "amount_tax": 0}})

        cart.order_line.filtered(lambda l: not l.display_type).unlink()
        return self._response_success({"cart": self._order_to_dict(cart)})

    @http.route("/api/v1/cart/checkout", type="http", auth="public", methods=["POST"], csrf=False)
    def cart_checkout(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        cart = self._get_cart_order(partner, create_if_missing=False)
        if not cart or not cart.order_line.filtered(lambda l: not l.display_type):
            return self._response_error("EMPTY_CART", "Cart is empty", status=400)

        cart.note = payload.get("note") or cart.note or ""
        voucher_code = (payload.get("voucher_code") or cart.loyalty_voucher_code or "").strip()
        if voucher_code:
            cart.loyalty_voucher_code = voucher_code

        address_id = payload.get("address_id")
        if address_id:
            shipping = request.env["res.partner"].sudo().browse(int(address_id))
            if not shipping.exists() or shipping.parent_id.id != partner.id:
                return self._response_error("INVALID_ADDRESS", "Address not found", status=400)
            cart.partner_shipping_id = shipping.id

        return self._response_success({
            "cart": self._order_to_dict(cart),
            "message": "Cart is ready for order submission",
        })

    # ----------------------------
    # 4. Orders
    # ----------------------------

    @http.route("/api/v1/orders", type="http", auth="public", methods=["GET"], csrf=False)
    def list_orders(self, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        page = max(self._parse_int(kwargs.get("page"), 1), 1)
        limit = max(self._parse_int(kwargs.get("limit"), 20), 1)
        offset = (page - 1) * limit

        domain = [("partner_id", "child_of", partner.id)]
        state = (kwargs.get("state") or "").strip()
        if state:
            state_map = {
                "pending": "draft",
                "shipping": "sale",
                "done": "done",
                "cancelled": "cancel",
            }
            mapped_state = state_map.get(state)
            if mapped_state:
                domain.append(("state", "=", mapped_state))

        model = request.env["sale.order"].sudo()
        total = model.search_count(domain)
        orders = model.search(domain, offset=offset, limit=limit, order="create_date desc")

        order_items = []
        for order in orders:
            items = []
            for line in order.order_line.filtered(lambda l: not l.display_type):
                items.append({
                    "id": line.id,
                    "product_name": line.product_id.display_name,
                    "product_image": self._img_url("product.product", line.product_id.id),
                    "quantity": line.product_uom_qty,
                    "price_unit": line.price_unit,
                    "price_subtotal": line.price_subtotal,
                })
            order_items.append({
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "date_order": self._vn_datetime(order.date_order),
                "amount_total": order.amount_total,
                "items": items,
            })

        return self._response_success({
            "orders": order_items,
            "total": total,
            "page": page,
            "limit": limit,
        })

    @http.route("/api/v1/orders/<int:order_id>", type="http", auth="public", methods=["GET"], csrf=False)
    def order_detail(self, order_id, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        order = request.env["sale.order"].sudo().browse(order_id)
        if not order.exists() or order.partner_id.commercial_partner_id.id != partner.id:
            return self._response_error("NOT_FOUND", "Order not found", status=404)

        ship_partner = order.partner_shipping_id or order.partner_id
        items = []
        for line in order.order_line.filtered(lambda l: not l.display_type):
            items.append({
                "id": line.id,
                "product_id": line.product_id.id,
                "product_name": line.product_id.display_name,
                "product_image": self._img_url("product.product", line.product_id.id),
                "quantity": line.product_uom_qty,
                "price_unit": line.price_unit,
                "price_subtotal": line.price_subtotal,
            })

        return self._response_success({
            "order": {
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "date_order": self._vn_datetime(order.date_order),
                "amount_total": order.amount_total,
                "amount_tax": order.amount_tax,
                "shipping_fee": 0,
                "discount_amount": 0,
                "voucher_code": order.loyalty_voucher_code or None,
                "shipping_address": {
                    "name": ship_partner.name,
                    "phone": ship_partner.phone or ship_partner.mobile or "",
                    "street": ship_partner.street or "",
                    "ward": ship_partner.street2 or "",
                    "district": "",
                    "city": ship_partner.city or "",
                },
                "items": items,
                "tracking_number": None,
                "tracking_url": None,
            }
        })

    @http.route("/api/v1/orders", type="http", auth="public", methods=["POST"], csrf=False)
    def create_order(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            return self._response_error("INVALID_INPUT", "items is required", status=400)

        shipping = partner
        address_id = payload.get("address_id")
        if address_id:
            shipping = request.env["res.partner"].sudo().browse(int(address_id))
            if not shipping.exists():
                return self._response_error("INVALID_ADDRESS", "Address not found", status=400)

        lines = []
        for item in items:
            product_id = self._parse_int(item.get("product_id"))
            qty = self._parse_float(item.get("quantity"), 0)
            if product_id <= 0 or qty <= 0:
                return self._response_error("INVALID_INPUT", "Each item must have product_id and quantity > 0", status=400)
            product = request.env["product.product"].sudo().browse(product_id)
            if not product.exists() or not product.sale_ok:
                return self._response_error("INVALID_PRODUCT", "Product %s is invalid" % product_id, status=400)
            product_price = getattr(product.product_tmpl_id, "x_studio_gia_san_tmdt", None)
            if not product_price:
                product_price = product.list_price
            lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": qty,
                "price_unit": product_price,
                "name": product.display_name,
            }))

        order = request.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "partner_invoice_id": partner.id,
            "partner_shipping_id": shipping.id,
            "note": payload.get("note") or "",
            "order_line": lines,
        })

        if payload.get("voucher_code"):
            order.loyalty_voucher_code = payload.get("voucher_code")

        items_data = [{
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.display_name,
            "quantity": line.product_uom_qty,
            "price_unit": line.price_unit,
            "price_subtotal": line.price_subtotal,
        } for line in order.order_line.filtered(lambda l: not l.display_type)]

        return self._response_success({
            "order": {
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "date_order": self._vn_datetime(order.date_order),
                "amount_total": order.amount_total,
                "items": items_data,
            }
        }, status=201)

    # ----------------------------
    # 5. Addresses
    # ----------------------------

    @http.route("/api/v1/addresses", type="http", auth="public", methods=["GET"], csrf=False)
    def list_addresses(self, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        addresses = request.env["res.partner"].sudo().search([
            ("parent_id", "=", partner.id),
            ("type", "=", "delivery"),
        ], order="id desc")

        default_address_id = self._get_default_address_id(partner)
        data = []
        for addr in addresses:
            data.append({
                "id": addr.id,
                "name": addr.name,
                "phone": addr.phone or addr.mobile or "",
                "street": addr.street or "",
                "ward": addr.street2 or "",
                "district": "",
                "city": addr.city or "",
                "is_default": bool(default_address_id == addr.id),
            })
        return self._response_success({"addresses": data})

    @http.route("/api/v1/addresses", type="http", auth="public", methods=["POST"], csrf=False)
    def create_address(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        required_fields = ["name", "phone", "street", "ward", "city"]
        missing = [f for f in required_fields if not (payload.get(f) or "").strip()]
        if missing:
            return self._response_error("INVALID_INPUT", "Missing fields: %s" % ", ".join(missing), status=400)

        addr = request.env["res.partner"].sudo().create({
            "name": payload.get("name"),
            "parent_id": partner.id,
            "type": "delivery",
            "phone": payload.get("phone"),
            "street": payload.get("street"),
            "street2": payload.get("ward") or "",
            "city": payload.get("city"),
            "customer_rank": 1,
        })

        if self._parse_bool(payload.get("is_default"), False):
            self._set_default_address_id(partner, addr.id)

        return self._response_success({
            "address": {
                "id": addr.id,
                "name": addr.name,
                "phone": addr.phone or addr.mobile or "",
                "street": addr.street or "",
                "ward": addr.street2 or "",
                "district": payload.get("district") or "",
                "city": addr.city or "",
                "is_default": self._parse_bool(payload.get("is_default"), False),
            }
        }, status=201)

    @http.route("/api/v1/addresses/<int:address_id>", type="http", auth="public", methods=["PUT"], csrf=False)
    def update_address(self, address_id, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        addr = request.env["res.partner"].sudo().browse(address_id)
        if not addr.exists() or addr.parent_id.id != partner.id:
            return self._response_error("NOT_FOUND", "Address not found", status=404)

        write_vals = {}
        field_map = {
            "name": "name",
            "phone": "phone",
            "street": "street",
            "ward": "street2",
            "city": "city",
        }
        for source, target in field_map.items():
            if source in payload:
                write_vals[target] = payload.get(source)
        if write_vals:
            addr.write(write_vals)

        if "is_default" in payload and self._parse_bool(payload.get("is_default"), False):
            self._set_default_address_id(partner, addr.id)

        return self._response_success({
            "address": {
                "id": addr.id,
                "name": addr.name,
                "phone": addr.phone or addr.mobile or "",
                "street": addr.street or "",
                "ward": addr.street2 or "",
                "district": payload.get("district") or "",
                "city": addr.city or "",
                "is_default": bool(self._get_default_address_id(partner) == addr.id),
            }
        })

    @http.route("/api/v1/addresses/<int:address_id>", type="http", auth="public", methods=["DELETE"], csrf=False)
    def delete_address(self, address_id, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        addr = request.env["res.partner"].sudo().browse(address_id)
        if not addr.exists() or addr.parent_id.id != partner.id:
            return self._response_error("NOT_FOUND", "Address not found", status=404)

        if self._get_default_address_id(partner) == addr.id:
            self._set_default_address_id(partner, 0)
        addr.unlink()
        return self._response_success({"deleted": True})

    # ----------------------------
    # 6. Loyalty extras not yet exported by current controllers
    # ----------------------------

    @http.route("/api/v1/loyalty/voucher-packages", type="http", auth="public", methods=["GET"], csrf=False)
    def loyalty_voucher_packages(self, **kwargs):
        packages = request.env["hlv.loyalty.voucher.package"].sudo().search([
            ("active", "=", True),
        ], order="points_required asc")
        return self._response_success({
            "packages": [{
                "id": p.id,
                "name": p.name,
                "points_required": p.points_required,
                "discount_type": p.discount_type,
                "discount_value": p.discount_value,
                "max_discount_amount": p.max_discount_amount,
                "validity_days": p._get_validity_days(),
                "apply_on": p.apply_on,
                "min_order_amount": p.min_order_amount,
                "reward_type": p.reward_type,
                "gift_product_name": p.gift_product_id.name if p.gift_product_id else '',
                "gift_qty": p.gift_qty,
            } for p in packages]
        })

    @http.route("/api/v1/loyalty/redeem", type="http", auth="public", methods=["POST"], csrf=False)
    def loyalty_redeem(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)
        root = partner._get_loyalty_root()

        package_id = self._parse_int(payload.get("package_id"), 0)
        if package_id <= 0:
            return self._response_error("INVALID_INPUT", "package_id is required", status=400)

        package = request.env["hlv.loyalty.voucher.package"].sudo().browse(package_id)
        if not package.exists() or not package.active:
            return self._response_error("INVALID_PACKAGE", "Voucher package not found or inactive", status=404)

        available_points = root.loyalty_exchange_available_points
        if available_points < package.points_required:
            return self._response_error(
                "INSUFFICIENT_POINTS",
                "Ban can %s diem, hien con %s diem kha dung. Dang treo %s diem."
                % (package.points_required, available_points, root.loyalty_reward_pending_points),
                status=400,
            )

        validity_days = package._get_validity_days()
        date_expiry = fields.Datetime.now() + timedelta(days=validity_days)

        voucher = request.env["hlv.loyalty.voucher"].sudo().create({
            "partner_id": root.id,
            "package_id": package.id,
            "date_expiry": date_expiry,
        })

        request.env["hlv.loyalty.history"].sudo().create({
            "partner_id": root.id,
            "point_amount": -package.points_required,
            "point_type": "exchange",
            "transaction_type": "redeem",
            "state": "confirmed",
            "description": "Redeem voucher [%s] - %s" % (package.name, voucher.code),
            "voucher_id": voucher.id,
            "company_id": request.env.company.id,
        })
        root.invalidate_recordset([
            "loyalty_exchange_points",
            "loyalty_reward_pending_points",
            "loyalty_exchange_available_points",
        ])

        return self._response_success({
            "voucher": self._voucher_to_dict(voucher),
            "remaining_points": root.loyalty_exchange_points,
            "pending_reward_points": root.loyalty_reward_pending_points,
            "exchange_points_available": root.loyalty_exchange_available_points,
        }, status=201)

    @http.route("/api/v1/loyalty/redeem/requests", type="http", auth="public", methods=["GET"], csrf=False)
    def loyalty_redeem_requests(self, **kwargs):
        partner = self._partner_from_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)
        root = partner._get_loyalty_root()
        limit = min(max(self._parse_int(kwargs.get("limit") or request.httprequest.args.get("limit"), 50), 1), 100)

        requests = request.env["hlv.loyalty.reward.request"].sudo().search([
            ("partner_id", "in", root._get_loyalty_family_partner_ids()),
        ], order="date_request desc, id desc", limit=limit)

        data = []
        for req in requests:
            data.append({
                "id": req.id,
                "name": req.name,
                "request_type": req.request_type,
                "points_required": req.points_required,
                "cash_value": req.cash_value,
                "package_id": req.package_id.id if req.package_id else None,
                "package_name": req.package_id.name if req.package_id else "",
                "bank_name": req.bank_name or "",
                "account_number": req.account_number or "",
                "account_name": req.account_name or "",
                "state": req.state,
                "date_request": self._vn_datetime(req.date_request),
                "date_done": self._vn_datetime(req.date_done),
                "customer_note": req.customer_note or "",
                "voucher_id": req.voucher_id.id if req.voucher_id else None,
                "voucher_code": req.voucher_id.code if req.voucher_id else "",
            })
        return self._response_success({
            "requests": data,
            "exchange_points": root.loyalty_exchange_points,
            "pending_reward_points": root.loyalty_reward_pending_points,
            "exchange_points_available": root.loyalty_exchange_available_points,
        })

    @http.route("/api/v1/loyalty/redeem/requests/<int:request_id>/cancel", type="http", auth="public", methods=["POST"], csrf=False)
    def loyalty_cancel_redeem_request(self, request_id=None, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)
        root = partner._get_loyalty_root()

        request_id = request_id or self._parse_int(payload.get("request_id"), 0)
        if request_id <= 0:
            return self._response_error("INVALID_INPUT", "request_id is required", status=400)

        req = request.env["hlv.loyalty.reward.request"].sudo().browse(request_id)
        if not req.exists() or req.partner_id.id not in root._get_loyalty_family_partner_ids():
            return self._response_error("REQUEST_NOT_FOUND", "Reward request not found", status=404)
        if req.state != "pending":
            return self._response_error("REQUEST_NOT_PENDING", "Only pending reward requests can be cancelled", status=400)

        try:
            req.action_cancel()
        except UserError as exc:
            return self._response_error("CANCEL_FAILED", str(exc), status=400)

        return self._response_success({
            "request": {
                "id": req.id,
                "name": req.name,
                "state": req.state,
                "points_required": req.points_required,
            },
            "exchange_points": root.loyalty_exchange_points,
            "pending_reward_points": root.loyalty_reward_pending_points,
            "exchange_points_available": root.loyalty_exchange_available_points,
            "message": "Reward request cancelled",
        })

    @http.route("/api/v1/account/change-password", type="http", auth="public", methods=["POST"], csrf=False, cors="*")
    def api_change_password(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        phone = self._normalize_vn_phone(payload.get('phone') or '')
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', phone),
            ('active', '=', True)
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == partner.id)[:1]
        if not account:
            return self._response_error("NOT_FOUND", "No active portal account found.", status=404)

        old_password = (payload.get('old_password') or '').strip()
        new_password = (payload.get('new_password') or '').strip()
        confirm_password = (payload.get('confirm_password') or '').strip()

        if not old_password or not new_password or not confirm_password:
            return self._response_error("INVALID_INPUT", "Vui lòng điền đầy đủ thông tin.", status=400)

        if not account._verify_password(old_password, account.password_hash):
            return self._response_error("INVALID_OLD_PASSWORD", "Mật khẩu hiện tại không đúng.", status=400)

        if new_password != confirm_password:
            return self._response_error("PASSWORD_MISMATCH", "Mật khẩu mới và xác nhận không khớp.", status=400)

        if len(new_password) < 6:
            return self._response_error("PASSWORD_TOO_SHORT", "Mật khẩu mới phải có ít nhất 6 ký tự.", status=400)

        try:
            account.set_password(new_password)
        except Exception as e:
            return self._response_error("SAVE_ERROR", str(e), status=500)

        return self._response_success({"message": "Đổi mật khẩu thành công."})

    @http.route("/api/v1/account/change-phone", type="http", auth="public", methods=["POST"], csrf=False, cors="*")
    def api_change_phone(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing or invalid partner_id/phone. Call /auth/zalo and pass returned partner_id with the same phone.", status=401)

        phone = self._normalize_vn_phone(payload.get('phone') or '')
        accounts = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('portal_phone', '=', phone),
            ('active', '=', True)
        ])
        account = accounts.filtered(lambda acc: acc.partner_id._get_loyalty_root().id == partner.id)[:1]
        if not account:
            return self._response_error("NOT_FOUND", "No active portal account found.", status=404)

        new_phone = (payload.get('new_phone') or '').strip()
        if not new_phone:
            return self._response_error("INVALID_INPUT", "Số điện thoại không được để trống.", status=400)

        import re
        if not re.match(r'^[\d\s\-\+]{7,15}$', new_phone):
            return self._response_error("INVALID_INPUT", "Số điện thoại không hợp lệ.", status=400)

        new_phone_normalized = self._normalize_vn_phone(new_phone)
        if not new_phone_normalized:
            return self._response_error("INVALID_INPUT", "Số điện thoại không hợp lệ.", status=400)

        duplicate = request.env['hlv.loyalty.portal.account'].sudo().search([
            ('id', '!=', account.id),
            ('portal_phone', '=', new_phone_normalized),
            ('active', '=', True),
        ], limit=1)
        if duplicate:
            return self._response_error("PHONE_IN_USE", "Số điện thoại đã được dùng cho tài khoản loyalty khác.", status=409)

        try:
            account.write({'portal_phone': new_phone_normalized})
        except Exception as e:
            return self._response_error("SAVE_ERROR", str(e), status=500)

        return self._response_success({
            "message": "Đổi số điện thoại đăng ký thành công.",
            "partner_id": partner.id,
            "phone": new_phone_normalized,
        })
