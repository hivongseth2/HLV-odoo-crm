# -*- coding: utf-8 -*-
import json
from datetime import timedelta
from odoo import fields, http
from odoo.http import request, Response


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
    def _img_url(model, rec_id, field_name="image_1920"):
        if not rec_id:
            return ""
        return "/web/image/%s/%s/%s" % (model, rec_id, field_name)

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

    def _partner_from_session_or_param(self, params=None):
        params = params or {}
        partner = None
        session_partner_id = request.session.get("zalo_partner_id")
        if session_partner_id:
            partner = request.env["res.partner"].sudo().browse(int(session_partner_id))
            if partner.exists():
                return partner.commercial_partner_id or partner

        partner_id = params.get("partner_id") or request.httprequest.args.get("partner_id")
        if partner_id:
            partner = request.env["res.partner"].sudo().browse(int(partner_id))
            if partner.exists():
                return partner.commercial_partner_id or partner
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
            "discount_type": voucher.discount_type,
            "discount_value": voucher.discount_value,
            "max_discount_amount": voucher.max_discount_amount,
            "min_order_amount": voucher.min_order_amount,
            "apply_on": voucher.apply_on,
            "date_issued": voucher.date_issued.isoformat() if voucher.date_issued else None,
            "date_expiry": voucher.date_expiry.isoformat() if voucher.date_expiry else None,
            "package_name": voucher.package_id.name if voucher.package_id else "",
        }

    @staticmethod
    def _history_to_dict(history):
        return {
            "id": history.id,
            "date": history.date.isoformat() if history.date else None,
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
        if not access_token or not user_id:
            return self._response_error("INVALID_INPUT", "access_token and user_id are required", status=400)

        partner_model = request.env["res.partner"].sudo()
        domain = [("ref", "=", user_id)]
        # Support optional custom fields if they exist in the DB.
        if "zalo_user_id" in partner_model._fields:
            domain = ["|", ("zalo_user_id", "=", user_id), ("ref", "=", user_id)]
        elif "x_zalo_user_id" in partner_model._fields:
            domain = ["|", ("x_zalo_user_id", "=", user_id), ("ref", "=", user_id)]

        partner = partner_model.search(domain, limit=1)
        if not partner:
            create_vals = {
                "name": "Zalo User %s" % user_id,
                "ref": user_id,
                "customer_rank": 1,
            }
            if "zalo_user_id" in partner_model._fields:
                create_vals["zalo_user_id"] = user_id
            if "x_zalo_user_id" in partner_model._fields:
                create_vals["x_zalo_user_id"] = user_id
            partner = partner_model.create(create_vals)

        root = partner.commercial_partner_id or partner
        request.session["zalo_partner_id"] = root.id

        api_key = request.env["ir.config_parameter"].sudo().get_param("hlv_loyalty.zalo_api_key", "")

        return self._response_success({
            "api_key": api_key or None,
            "partner_id": root.id,
            "name": root.name,
            "phone": root.phone or root.mobile or "",
            "email": root.email or "",
            "avatar": self._img_url("res.partner", root.id),
            "loyalty_points": root.loyalty_total_points,
            "tier": root.loyalty_tier_id.name if root.loyalty_tier_id else None,
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
            "price_asc": "list_price asc, id desc",
            "price_desc": "list_price desc, id desc",
            "newest": "create_date desc, id desc",
            "best_seller": "sales_count desc, id desc" if "sales_count" in request.env["product.template"]._fields else "id desc",
        }
        order = sort_map.get(kwargs.get("sort"), "id desc")

        model = request.env["product.template"].sudo()
        total = model.search_count(domain)
        products = model.search(domain, offset=offset, limit=limit, order=order)

        def _original_price(p):
            compare_price = getattr(p, "compare_list_price", 0) or 0
            return compare_price if compare_price and compare_price >= p.list_price else p.list_price

        def _discount_percent(p):
            original = _original_price(p)
            if original and original > p.list_price:
                return int(round((original - p.list_price) * 100.0 / original, 0))
            return 0

        data = []
        for p in products:
            price = p.list_price
            original_price = _original_price(p)
            data.append({
                "id": p.id,
                "name": p.name,
                "price": price,
                "original_price": original_price,
                "discount_percent": _discount_percent(p),
                "image_url": self._img_url("product.template", p.id),
                "sold_count": getattr(p, "sales_count", 0),
                "free_shipping": False,
                "voucher_label": None,
                "gifts": [],
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

        imgs = [self._img_url("product.template", product.id)]
        price = product.list_price
        compare_price = getattr(product, "compare_list_price", 0) or 0
        original_price = compare_price if compare_price and compare_price >= price else price
        discount_percent = int(round((original_price - price) * 100.0 / original_price, 0)) if original_price else 0

        return self._response_success({
            "product": {
                "id": product.id,
                "name": product.name,
                "price": price,
                "original_price": original_price,
                "discount_percent": discount_percent,
                "image_url": self._img_url("product.template", product.id),
                "images": imgs,
                "sold_count": getattr(product, "sales_count", 0),
                "free_shipping": False,
                "voucher_label": None,
                "gifts": [],
                "description": product.description_sale or product.description or "",
                "specifications": specs,
                "category_id": product.categ_id.id if product.categ_id else None,
                "category_name": product.categ_id.name if product.categ_id else "",
                "stock_available": bool(product.qty_available > 0),
                "rating": 0,
                "review_count": 0,
            }
        })

    @http.route("/api/v1/banners", type="http", auth="public", methods=["GET"], csrf=False)
    def banners(self, **kwargs):
        # Keep a stable contract for Mini App; integrate with a custom banner model later.
        return self._response_success({"banners": []})

    # ----------------------------
    # 4. Orders
    # ----------------------------

    @http.route("/api/v1/orders", type="http", auth="public", methods=["GET"], csrf=False)
    def list_orders(self, **kwargs):
        partner = self._partner_from_session_or_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
                "date_order": order.date_order.isoformat() if order.date_order else None,
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
        partner = self._partner_from_session_or_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
                "date_order": order.date_order.isoformat() if order.date_order else None,
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
        partner = self._partner_from_session_or_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
            lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": qty,
                "price_unit": product.list_price,
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
                "date_order": order.date_order.isoformat() if order.date_order else None,
                "amount_total": order.amount_total,
                "items": items_data,
            }
        }, status=201)

    # ----------------------------
    # 5. Addresses
    # ----------------------------

    @http.route("/api/v1/addresses", type="http", auth="public", methods=["GET"], csrf=False)
    def list_addresses(self, **kwargs):
        partner = self._partner_from_session_or_param(kwargs)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
        partner = self._partner_from_session_or_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
        partner = self._partner_from_session_or_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
        partner = self._partner_from_session_or_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

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
            } for p in packages]
        })

    @http.route("/api/v1/loyalty/redeem", type="http", auth="public", methods=["POST"], csrf=False)
    def loyalty_redeem(self, **kwargs):
        payload = self._request_json()
        partner = self._partner_from_session_or_param(payload)
        if not partner:
            return self._response_error("UNAUTHORIZED", "Missing partner context. Call /auth/zalo first.", status=401)

        package_id = self._parse_int(payload.get("package_id"), 0)
        if package_id <= 0:
            return self._response_error("INVALID_INPUT", "package_id is required", status=400)

        package = request.env["hlv.loyalty.voucher.package"].sudo().browse(package_id)
        if not package.exists() or not package.active:
            return self._response_error("INVALID_PACKAGE", "Voucher package not found or inactive", status=404)

        if partner.loyalty_total_points < package.points_required:
            return self._response_error(
                "INSUFFICIENT_POINTS",
                "Ban can %s diem, hien co %s diem" % (package.points_required, partner.loyalty_total_points),
                status=400,
            )

        validity_days = package._get_validity_days()
        date_expiry = fields.Datetime.now() + timedelta(days=validity_days)

        voucher = request.env["hlv.loyalty.voucher"].sudo().create({
            "partner_id": partner.id,
            "package_id": package.id,
            "date_expiry": date_expiry,
        })

        request.env["hlv.loyalty.history"].sudo().create({
            "partner_id": partner.id,
            "point_amount": -package.points_required,
            "transaction_type": "redeem",
            "description": "Redeem voucher [%s] - %s" % (package.name, voucher.code),
            "voucher_id": voucher.id,
            "company_id": request.env.company.id,
        })

        return self._response_success({
            "voucher": self._voucher_to_dict(voucher),
            "remaining_points": partner.loyalty_total_points,
        }, status=201)
