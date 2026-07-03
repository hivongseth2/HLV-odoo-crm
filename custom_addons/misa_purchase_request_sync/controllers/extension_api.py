# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
RESTful API cho MISA CRM Browser Extension (Chrome MV3).

Endpoints:
    GET  /api/extension/pr/check?name=<name>
        -> {"ok": True, "exists": True/False, "status": "draft", "status_label": "Mới"}

    POST /api/extension/pr/create
        Body JSON:
        {
            "token": "...",
            "PurchaseRequestName": "PR00001",
            "OwnerIDText": "MAI VĂN NAM (MAIVANNAM1)",
            "lines": [
                {"product_code": "SP001", "name": "...", "qty": 10, "uom": "Cái"},
                ...
            ],
            "description": "..."
        }
        -> {"ok": True, "id": 123, "name": "PR00001"}

    POST /api/extension/po/reconcile
        Body JSON:
        {
            "token": "...",
            "date_from": "2026-06-01",
            "date_to": "2026-06-30"
        }
        -> {"ok": True, "data": {...}, "summary": {...}, "reconciled": [...]}

Xác thực: Header `X-MISA-Token: <token>` (hoặc token trong body JSON).
Token so sánh với System Parameter `misa_extension_token` (sudo).
"""

import json
import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _clean_token(token):
    """Loại bỏ zero-width chars để tránh lỗi so sánh."""
    if not token:
        return ""
    return re.sub(r"[​-‍﻿]", "", str(token)).strip()


class MisaExtensionController(http.Controller):
    """Public API endpoints cho MISA CRM Browser Extension."""

    # ============================================================
    # AUTH HELPER
    # ============================================================
    def _authenticate(self, token):
        """
        So sánh token với System Parameter `misa_extension_token`.

        :return: (ok: bool, error_response: dict | None)
        """
        expected = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("misa_extension_token", default="")
        )
        expected = _clean_token(expected)

        if not expected:
            _logger.error(
                "misa_extension_token chưa được cấu hình trong System Parameters."
            )
            return (
                False,
                {
                    "ok": False,
                    "error": "server_misconfigured",
                    "message": "Server chưa cấu hình token xác thực.",
                },
            )

        if _clean_token(token) != expected:
            return (
                False,
                {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."},
            )
        return (True, None)

    def _parse_json_body(self, payload):
        """
        Với type='json' Odoo parse sẵn vào **payload. Nếu rỗng (Postman sai
        Content-Type), tự đọc raw body.
        """
        if payload:
            return dict(payload)
        try:
            body = request.httprequest.get_json(force=False, silent=True)
        except Exception:
            body = None
        if body is None:
            raw = (request.httprequest.data or b"").decode("utf-8", errors="ignore")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {}
        return dict(body or {})

    def _extract_token(self, payload):
        """Lấy token từ body hoặc header X-MISA-Token."""
        raw = payload.get("token") or request.httprequest.headers.get("X-MISA-Token")
        return _clean_token(raw)

    # ============================================================
    # GET /api/extension/pr/check?name=PR00001
    # ============================================================
    @http.route(
        "/api/extension/pr/check",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_check(self, **kwargs):
        """
        Kiểm tra YCMH đã tồn tại trên Odoo hay chưa.

        Query: ?name=PR00001
        Header: X-MISA-Token: <token>

        Response 200 JSON:
            {
                "ok": True,
                "exists": True,
                "id": 5,
                "name": "PR00001",
                "status": "draft",
                "status_label": "Mới"
            }
        """
        # ---- Auth (token có thể nằm ở query string cho GET) ----
        token = _clean_token(kwargs.get("token")) or _clean_token(
            request.httprequest.headers.get("X-MISA-Token")
        )
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        # ---- Business logic ----
        name = (kwargs.get("name") or "").strip()
        if not name:
            return request.make_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "missing_name",
                        "message": "Thiếu tham số 'name' trên query string.",
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        # Dùng admin env để tránh lỗi phân quyền
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env
        pr = env["purchase.request"].sudo().search([("name", "=", name)], limit=1)

        if not pr:
            payload = {"ok": True, "exists": False, "name": name}
        else:
            state_label = (
                dict(pr._fields["state"].selection).get(pr.state, pr.state)
                if pr.state
                else ""
            )
            # Fetch lines and their quantities
            lines_data = []
            for line in pr.line_ids:
                # purchased_qty is usually standard in OCA purchase_request
                # qty_received might not be present, so we compute it from related purchase_lines if available
                qty_received = 0.0
                if hasattr(line, 'purchase_lines'):
                    for pl in line.purchase_lines:
                        if hasattr(pl, 'qty_received'):
                            qty_received += pl.qty_received
                elif hasattr(line, 'purchased_qty'):
                    qty_received = line.purchased_qty # Fallback to purchased_qty if qty_received is not available
                    
                purchase_state = line.purchase_state if hasattr(line, 'purchase_state') else False

                # Prepare supplier name if available
                misa_supplier_id = None
                misa_supplier_name = ""
                if hasattr(line, 'sale_proposed_supplier_id') and line.sale_proposed_supplier_id:
                    misa_supplier_id = line.sale_proposed_supplier_id.id
                    ref = line.sale_proposed_supplier_id.ref
                    misa_supplier_name = (f"[{ref}] " if ref else "") + line.sale_proposed_supplier_id.name

                lines_data.append({
                    "misa_line_id": line.misa_line_id or "",
                    "product_code": line.product_id.default_code if line.product_id else "",
                    "name": line.name,
                    "qty": line.product_qty,
                    "qty_received": qty_received,
                    "purchase_state": purchase_state,
                    # --- MISA Extension Custom Fields ---
                    "sale_proposed_supplier_id": misa_supplier_id,
                    "misa_supplier_id": misa_supplier_id,
                    "misa_supplier_name": misa_supplier_name,
                    "misa_price_before_tax": line.misa_price_before_tax if hasattr(line, 'misa_price_before_tax') else 0.0,
                    "misa_price_after_tax": line.misa_price_after_tax if hasattr(line, 'misa_price_after_tax') else 0.0,
                    "misa_amount": line.misa_amount if hasattr(line, 'misa_amount') else 0.0,
                    "misa_tax_rate": line.misa_tax_rate if hasattr(line, 'misa_tax_rate') else 0.0,
                    "misa_tax_amount": line.misa_tax_amount if hasattr(line, 'misa_tax_amount') else 0.0,
                    "misa_discount_rate": line.misa_discount_rate if hasattr(line, 'misa_discount_rate') else 0.0,
                    "misa_discount_amount": line.misa_discount_amount if hasattr(line, 'misa_discount_amount') else 0.0,
                    "misa_stock_total": line.misa_stock_total if hasattr(line, 'misa_stock_total') else 0.0,
                    "misa_stock_selected": line.misa_stock_selected if hasattr(line, 'misa_stock_selected') else 0.0,
                    "misa_stock_undelivered": line.misa_stock_undelivered if hasattr(line, 'misa_stock_undelivered') else 0.0,
                })

            # Kiểm tra xem YCMH đã có RFQ/PO liên kết chưa
            has_rfq = any(
                line.purchase_lines for line in pr.line_ids
                if hasattr(line, 'purchase_lines') and line.purchase_lines
            )
            can_revoke = (pr.state in ['draft', 'to_approve']) and not has_rfq

            payload = {
                "ok": True,
                "exists": True,
                "id": pr.id,
                "name": pr.name,
                "status": pr.state,
                "status_label": state_label,
                "can_revoke": can_revoke,
                "lines": lines_data,
            }

        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )

    # ============================================================
    # POST /api/extension/pr/revoke
    # ============================================================
    @http.route(
        "/api/extension/pr/revoke",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_revoke(self, **payload):
        """
        Thu hồi (xóa) YCMH trên Odoo.
        """
        def json_response(payload, status=200):
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")]
            )

        payload = self._parse_json_body(payload)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return json_response(err, 401)

        pr_name = (payload.get("PurchaseRequestName") or "").strip()
        if not pr_name:
            return json_response({"ok": False, "error": "missing_name", "message": "Thiếu PurchaseRequestName."}, 400)

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env

        pr = env["purchase.request"].sudo().search([("name", "=", pr_name)], limit=1)
        if not pr:
            return json_response({"ok": False, "error": "not_found", "message": "Không tìm thấy YCMH."}, 404)

        if pr.state not in ['draft', 'to_approve']:
            return json_response({"ok": False, "error": "invalid_state", "message": f"Không thể thu hồi YCMH ở trạng thái {pr.state}."}, 400)

        # Kiểm tra xem YCMH đã có RFQ/PO liên kết chưa
        has_rfq = any(
            line.purchase_lines for line in pr.line_ids
            if hasattr(line, 'purchase_lines') and line.purchase_lines
        )
        if has_rfq:
            return json_response({
                "ok": False,
                "error": "has_rfq",
                "message": "Không thể thu hồi do YCMH đã có RFQ/Đơn mua hàng liên kết."
            }, 400)

        try:
            if pr.state != 'draft':
                pr.button_draft()
            pr.unlink()
            return json_response({"ok": True, "message": "Đã thu hồi YCMH thành công."})
        except Exception as e:
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)

    # ============================================================
    # POST /api/extension/suppliers_and_stock
    # ============================================================
    @http.route(
        "/api/extension/suppliers_and_stock",
        type="http",
        auth="none",
        methods=["GET", "POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_suppliers_and_stock(self, **kwargs):
        """
        Lấy danh sách Nhà cung cấp và Tồn kho sản phẩm để hiển thị trong Extension
        """
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*"), ("Access-Control-Allow-Methods", "GET, POST, OPTIONS")])

        payload = self._parse_json_body(kwargs)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env

        # 1. Lấy danh sách NCC
        domain = [
            ('parent_id', '=', False),
            ('hlv_business_role', 'in', ['supplier', 'vendor'])
        ]
        q = payload.get('q') or kwargs.get('q')
        if q:
            domain.append('|')
            domain.append(('name', 'ilike', q))
            domain.append(('ref', 'ilike', q))

        suppliers = env['res.partner'].sudo().search_read(
            domain,
            ['id', 'name', 'ref']
        )
        
        # 2. Lấy thông tin tồn kho
        stock_info = {}
        product_codes = payload.get('product_codes') or []
        if product_codes:
            products = env['product.product'].sudo().search([('default_code', 'in', product_codes)])
            for p in products:
                stock_info[p.default_code] = p.qty_available

        return request.make_response(
            json.dumps({"ok": True, "data": {"suppliers": suppliers, "stock": stock_info}}),
            headers=[("Content-Type", "application/json")]
        )

    # ============================================================
    # POST /api/extension/pr/create
    # ============================================================
    @http.route(
        "/api/extension/pr/create",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_create(self, **payload):
        """
        Tạo YCMH mới từ payload JSON của MISA CRM.

        Body JSON:
        {
            "token": "...",                        # hoặc header X-MISA-Token
            "PurchaseRequestName": "PR00001",     # mã YCMH từ CRM
            "OwnerIDText": "MAI VĂN NAM (MAIVANNAM1)",
            "description": "YCMH từ CRM MISA",
            "lines": [
                {
                    "product_code": "SP001",      # default_code; optional
                    "name": "Sản phẩm A",
                    "qty": 10.0,
                    "uom": "Cái"                 # optional, mặc định = product.uom_id
                }
            ]
        }
        """
        # ---- Helper: Trả về HTTP Response ----
        def json_response(payload, status=200):
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")]
            )

        payload = self._parse_json_body(payload)
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info("MISA PR Create Payload: %s", payload)

        # ---- Auth ----
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return json_response(err, 401)

        # ---- Validate ----
        pr_name = (payload.get("PurchaseRequestName") or "").strip()
        if not pr_name:
            return json_response({
                "ok": False,
                "error": "missing_purchase_request_name",
                "message": "Thiếu trường 'PurchaseRequestName'.",
            }, 400)

        lines_in = payload.get("lines") or []
        if not isinstance(lines_in, list) or not lines_in:
            return json_response({
                "ok": False,
                "error": "missing_lines",
                "message": "Thiếu danh sách 'lines' (ít nhất 1 dòng sản phẩm).",
            }, 400)

        # ---- Switch sang admin env (an toàn phân quyền) ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return json_response({"ok": False, "error": "admin_not_found", "message": "Không tìm thấy user admin để sudo."}, 500)
        env_admin = request.env(user=admin_user)

        try:
            # --- Resolve user từ OwnerIDText ---
            pr_model = env_admin["purchase.request"]
            user_id, owner_message = pr_model._prepare_misa_user(
                payload.get("OwnerIDText")
            )

            # --- Tìm Đơn bán hàng liên quan ---
            so_name = (payload.get("SaleOrderIDText") or "").strip()
            sale_order_id = False
            if so_name:
                so = env_admin["sale.order"].search([("name", "=", so_name)], limit=1)
                if so:
                    sale_order_id = so.id

            raw_data = payload.get("rawData", {})
            date_start = False
            create_date = False
            date_required = False
            
            from dateutil import parser
            import pytz
            
            if raw_data.get("RequestDate"):
                try:
                    dt = parser.parse(raw_data["RequestDate"])
                    date_start = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
                    
            if raw_data.get("CreatedDate"):
                try:
                    dt = parser.parse(raw_data["CreatedDate"])
                    dt_utc = dt.astimezone(pytz.utc)
                    create_date = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                    
            if raw_data.get("DesiredDeliveryDeadline"):
                try:
                    dt = parser.parse(raw_data["DesiredDeliveryDeadline"])
                    date_required = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # --- Kiểm tra PR đã tồn tại ---
            # Lấy product_model và uom_model sớm để dùng trong resolve line
            line_model = env_admin["purchase.request.line"]
            product_model = env_admin["product.product"]
            uom_model = env_admin["uom.uom"]
            
            pr = pr_model.search([("name", "=", pr_name)], limit=1)
            is_new_pr = False
            existing_lines_by_misa_id = {}  # misa_line_id → record
            
            if pr:
                if pr.state not in ['draft', 'to_approve']:
                    return json_response({
                        "ok": False, 
                        "error": "invalid_state", 
                        "message": f"YCMH {pr_name} đã tồn tại và ở trạng thái {pr.state}, không thể cập nhật."
                    }, 400)
                
                # Build map existing lines by misa_line_id (chỉ những line có misa_line_id)
                for existing_line in pr.line_ids:
                    if existing_line.misa_line_id:
                        existing_lines_by_misa_id[existing_line.misa_line_id] = existing_line
                
                write_vals = {
                    "requested_by": user_id,
                    "description": payload.get("description") or "",
                    "delivery_address": payload.get("DeliveryAddress") or "",
                    "sale_order_id": sale_order_id,
                }
                if date_start:
                    write_vals["date_start"] = date_start
                    
                pr.write(write_vals)
                
                # Cập nhật create_date bằng SQL vì ORM chặn write() lên create_date
                if create_date:
                    env_admin.cr.execute("UPDATE purchase_request SET create_date=%s WHERE id=%s", (create_date, pr.id))
            else:
                # --- Tạo PR ---
                is_new_pr = True
                pr_vals = {
                    "name": pr_name,
                    "requested_by": user_id,
                    "assigned_to": admin_user.id if admin_user else False,
                    "state": "to_approve",
                    "origin": "MISA CRM",
                    "description": payload.get("description") or "",
                    "delivery_address": payload.get("DeliveryAddress") or "",
                    "sale_order_id": sale_order_id,
                }
                if date_start:
                    pr_vals["date_start"] = date_start
                if create_date:
                    pr_vals["create_date"] = create_date
                    
                pr = pr_model.create(pr_vals)

            # ─── Helper: Resolve sản phẩm + UoM từ 1 line dict ───
            def _resolve_product_and_uom(line):
                pcode = (line.get("product_code") or "").strip()
                product = False
                if pcode:
                    product = product_model.search(
                        [("default_code", "=ilike", pcode)], limit=1
                    )
                if not product:
                    pname = (line.get("name") or "").strip()
                    if pname:
                        product = product_model.search(
                            [("name", "=ilike", pname)], limit=1
                        )
                # Fallback 2: Gọi API MISA để tạo sản phẩm nếu chưa có
                if not product and pcode and "odoo.utils" in env_admin:
                    odoo_utils = env_admin["odoo.utils"]
                    try:
                        OdooUtilsClass = type(odoo_utils)
                        if hasattr(OdooUtilsClass, "_get_token_api_crm"):
                            token_api = OdooUtilsClass._get_token_api_crm()
                            product = odoo_utils.get_misa_product(token_api, pcode)
                    except Exception as e:
                        _logger.error("Lỗi khi fetch sản phẩm từ MISA: %s", str(e))

                uom = False
                uom_name = (line.get("uom") or "").strip()
                if product and uom_name:
                    if uom_name.lower() == product.uom_id.name.lower():
                        uom = product.uom_id
                    elif product.uom_po_id and uom_name.lower() == product.uom_po_id.name.lower():
                        uom = product.uom_po_id
                if not uom and uom_name:
                    if product:
                        uom = uom_model.search([("name", "=ilike", uom_name), ("category_id", "=", product.uom_id.category_id.id)], limit=1)
                    if not uom:
                        uom = uom_model.search([("name", "=ilike", uom_name)], limit=1)
                if not uom and product:
                    uom = product.uom_id
                return product, uom

            # ─── Build line_vals từ 1 line dict ───
            def _build_line_vals(line, product, uom):
                vals = {
                    "request_id": pr.id,
                    "name": line.get("name") or (product.display_name if product else ""),
                    "product_id": product.id if product else False,
                    "product_qty": float(line.get("qty") or 0.0),
                    "product_uom_id": uom.id if uom else False,
                    "estimated_cost": 0.0,
                    "misa_line_id": (line.get("misa_line_id") or "").strip() or False,
                    "sale_proposed_supplier_id": int(line.get("misa_supplier_id")) if line.get("misa_supplier_id") else False,
                    "misa_price_before_tax": float(line.get("misa_price_before_tax") or 0.0),
                    "misa_price_after_tax": float(line.get("misa_price_after_tax") or 0.0),
                    "misa_amount": float(line.get("misa_amount") or 0.0),
                    "misa_tax_rate": float(line.get("misa_tax_rate") or 0.0),
                    "misa_tax_amount": float(line.get("misa_tax_amount") or 0.0),
                    "misa_discount_rate": float(line.get("misa_discount_rate") or 0.0),
                    "misa_discount_amount": float(line.get("misa_discount_amount") or 0.0),
                    "misa_stock_total": float(line.get("misa_stock_total") or 0.0),
                    "misa_stock_selected": float(line.get("misa_stock_selected") or 0.0),
                    "misa_stock_undelivered": float(line.get("misa_stock_undelivered") or 0.0),
                }
                if date_required:
                    vals["date_required"] = date_required
                return vals

            # ─── Process từng line ───
            incoming_misa_ids = set()
            lines_created = 0
            lines_updated = 0

            for line in lines_in:
                if not isinstance(line, dict):
                    continue
                misa_id = (line.get("misa_line_id") or "").strip()
                if misa_id:
                    incoming_misa_ids.add(misa_id)

                product, uom = _resolve_product_and_uom(line)

                # --- APPLY UoM CONVERSION ---
                misa_uom_text = (line.get("uom") or "").strip()
                default_uom_name = product.uom_id.name.strip() if product and product.uom_id else ""
                misa_product_id = line.get("misa_product_id")
                
                if misa_product_id and product and misa_uom_text and default_uom_name and misa_uom_text.lower() != default_uom_name.lower():
                    try:
                        headers, _ = env_admin['sale.order']._misa_headers()
                        orig_qty = float(line.get("qty") or 0.0)
                        orig_price_before = float(line.get("misa_price_before_tax") or 0.0)
                        qty_base, price_base, use_default = env_admin['sale.order']._convert_qty_price_to_default_uom(
                            product=product,
                            misa_uom_text=misa_uom_text,
                            qty=orig_qty,
                            price=orig_price_before,
                            misa_product_id=misa_product_id,
                            headers=headers
                        )
                        line["qty"] = qty_base
                        line["misa_price_before_tax"] = price_base
                        
                        orig_price_after = float(line.get("misa_price_after_tax") or 0.0)
                        if orig_price_before:
                            rate_price = price_base / orig_price_before
                            line["misa_price_after_tax"] = orig_price_after * rate_price
                        
                        uom = product.uom_id
                    except Exception as e:
                        _logger.error("Lỗi khi gọi API chuyển đổi ĐVT: %s", str(e))
                # -----------------------------

                line_vals = _build_line_vals(line, product, uom)

                if misa_id and misa_id in existing_lines_by_misa_id:
                    # ── UPDATE existing line ──
                    existing_line = existing_lines_by_misa_id[misa_id]
                    # Bỏ request_id khỏi vals khi write (không cần)
                    write_vals = {k: v for k, v in line_vals.items() if k != "request_id"}
                    existing_line.write(write_vals)
                    lines_updated += 1
                else:
                    # ── CREATE new line (kể cả trường hợp misa_id rỗng hoặc PR mới) ──
                    line_model.create(line_vals)
                    lines_created += 1

            # ── XÓA các line cũ không còn trong MISA (chỉ khi có misa_line_id để so sánh) ──
            if not is_new_pr and incoming_misa_ids:
                stale_lines = pr.line_ids.filtered(
                    lambda l: l.misa_line_id and l.misa_line_id not in incoming_misa_ids
                )
                if stale_lines:
                    stale_lines.unlink()
                    _logger.info(
                        "MISA PR Sync: Deleted %d stale lines from PR %s (IDs: %s)",
                        len(stale_lines), pr.name,
                        ", ".join(stale_lines.mapped("misa_line_id"))
                    )

            # --- Post Chatter nếu là Admin fallback ---
            if owner_message:
                pr.message_post(body=owner_message)
                
            # --- Post thông tin Nhà cung cấp mới vào Chatter (gắn với từng dòng sản phẩm) ---
            new_supplier_lines = [l for l in lines_in if l.get("new_supplier_data")]
            if new_supplier_lines:
                from markupsafe import Markup
                msg_body = "<p><b>[MISA Extension] Thêm Nhà cung cấp mới:</b></p><ul>"
                for sl in new_supplier_lines:
                    ns = sl.get("new_supplier_data", {})
                    ns_name = ns.get("name", "")
                    ns_address = ns.get("address", "")
                    ns_phone = ns.get("phone", "")
                    ns_vat = ns.get("vat", "")
                    ns_note = ns.get("note", "")
                    product_name = sl.get("name") or sl.get("product_code") or "Không xác định"
                    
                    msg_body += f"<li><b>Sản phẩm:</b> {product_name}<br/><b>Tên NCC:</b> {ns_name}"
                    if ns_address:
                        msg_body += f"<br/><b>Địa chỉ:</b> {ns_address}"
                    if ns_phone:
                        msg_body += f"<br/><b>SĐT:</b> {ns_phone}"
                    if ns_vat:
                        msg_body += f"<br/><b>Mã số thuế:</b> {ns_vat}"
                    if ns_note:
                        msg_body += f"<br/><b>Ghi chú:</b> {ns_note}"
                    msg_body += "</li><br/>"
                msg_body += "</ul>"
                pr.message_post(body=Markup(msg_body))

            return json_response({
                "ok": True,
                "id": pr.id,
                "name": pr.name,
                "state": pr.state,
                "lines_created": len(pr.line_ids),
                "owner_warning": owner_message or None,
            })

        except Exception as e:
            _logger.exception("Extension API /pr/create exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)

    # ============================================================
    # PO RECONCILE - HELPERS
    # ============================================================

    @staticmethod
    def _classify_po_status(po_data, amis_po, amis_lines, odoo_lines_detail):
        """
        Phân loại trạng thái đối chiếu PO dựa trên dữ liệu Odoo và AMIS.
        
        Trả về: (status, severity, root_cause, suggested_action, differences)
        """
        differences = []
        
        # Trường hợp 1: Không tìm thấy trên AMIS
        if not amis_po:
            return (
                "missing_in_misa",
                "critical",
                "workflow_missing",
                "Đơn hàng chưa được đồng bộ sang MISA. Kiểm tra workflow AMIS Mua hàng, đồng bộ thủ công hoặc tạo lại đơn trên MISA",
                []
            )

        # Trường hợp 2: Có trên AMIS, so sánh chi tiết
        # CHỈ so sánh tổng tiền SAU KHI check từng dòng, để tránh False Positive do
        # MISA trả về total_amount = tổng chưa thuế, Odoo amount_total = tổng đã gồm thuế.
        # Việc so sánh này chỉ có ý nghĩa khi không có lệch line nào.
        odoo_total = po_data.get("amount_total", 0.0)
        odoo_untaxed = po_data.get("amount_untaxed", odoo_total)
        amis_total = float(amis_po.get("total_amount") or 0.0)

        # So sánh từng dòng sản phẩm — aggregate by code
        # Odoo: aggregate qty_received (số lượng đã nhận thực tế, KHÔNG phải product_qty đặt hàng)
        odoo_prod_map = {}  # code -> {"qty": float, "price_unit": float, "display": str, "name": str}
        for oline in odoo_lines_detail:
            code = oline["code"]
            if code not in odoo_prod_map:
                odoo_prod_map[code] = {
                    "qty": 0.0,
                    "price_unit": oline.get("price_unit", 0.0),
                    "price_tax": 0.0,
                    "display": oline["display"],
                    "name": oline["name"],
                }
            odoo_prod_map[code]["qty"] += oline.get("qty_received", oline.get("qty", 0.0))
            odoo_prod_map[code]["price_tax"] += oline.get("price_tax", 0.0)

        # AMIS: aggregate quantity_receipt
        amis_prod_map = {}  # code -> {"qty": float, "price_unit": float, "name": str}
        for aline in amis_lines:
            orig_code = aline.get("inventory_item_code", "unknown_code").strip()
            code = orig_code.lower()
            a_qty = float(aline.get("quantity_receipt", 0))
            a_price = float(aline.get("unit_price", 0) or 0)
            a_tax = float(aline.get("vat_amount", aline.get("tax_amount", 0)) or 0)
            a_name = aline.get("inventory_item_name", "")
            if code not in amis_prod_map:
                amis_prod_map[code] = {"qty": 0.0, "price_unit": a_price, "price_tax": 0.0, "name": a_name, "orig_code": orig_code}
            amis_prod_map[code]["qty"] += a_qty
            amis_prod_map[code]["price_tax"] += a_tax

        all_codes = set(list(odoo_prod_map.keys()) + list(amis_prod_map.keys()))
        
        has_qty_diff = False
        has_price_diff = False
        has_missing_in_amis = False
        has_missing_in_odoo = False
        has_total_diff = False
        has_tax_diff = False
        has_vat_diff = False
        
        if abs(odoo_untaxed - amis_total) >= 1.0:
            has_total_diff = True
        elif abs(odoo_total - amis_total) >= 1.0:
            # Chỉ lệch do thuế - đánh dấu info, không warning
            has_tax_diff = True
            differences.append({
                "type": "tax_diff",
                "product_code": "__total__",
                "product_name": "Thuế GTGT",
                "field": "amount_tax",
                "odoo_value": odoo_total - odoo_untaxed,
                "misa_value": 0,
                "severity": "info"
            })

        for code in all_codes:
            o_item = odoo_prod_map.get(code)
            a_item = amis_prod_map.get(code)
            
            if o_item:
                display_code = o_item["display"]
                prod_name = o_item["name"]
            elif a_item:
                display_code = f"[{a_item.get('orig_code', code)}] {a_item.get('name', '')}"
                prod_name = a_item.get("name", "")
            else:
                display_code = code
                prod_name = ""

            if o_item and not a_item:
                # Sản phẩm chỉ có trên Odoo
                has_missing_in_amis = True
                differences.append({
                    "type": "missing_in_amis",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "qty",
                    "odoo_value": o_item["qty"],
                    "misa_value": 0,
                    "severity": "critical"
                })
            elif a_item and not o_item:
                # Sản phẩm chỉ có trên AMIS
                has_missing_in_odoo = True
                differences.append({
                    "type": "missing_in_odoo",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "qty",
                    "odoo_value": 0,
                    "misa_value": a_item["qty"],
                    "severity": "critical"
                })
            else:
                # Cả 2 đều có, so sánh số lượng đã nhập kho
                o_qty = o_item["qty"]
                a_qty = a_item["qty"]
                if abs(o_qty - a_qty) > 0.01:
                    has_qty_diff = True
                    differences.append({
                        "type": "qty_mismatch",
                        "product_code": code,
                        "product_name": prod_name,
                        "field": "qty_received",
                        "odoo_value": o_qty,
                        "misa_value": a_qty,
                        "severity": "warning"
                    })
                
                # So sánh đơn giá
                o_price = o_item.get("price_unit", 0.0)
                a_price = a_item.get("price_unit", 0.0)
                if o_price > 0 and a_price > 0 and abs(o_price - a_price) > 100:
                    has_price_diff = True
                    differences.append({
                        "type": "price_mismatch",
                        "product_code": code,
                        "product_name": prod_name,
                        "field": "price_unit",
                        "odoo_value": o_price,
                        "misa_value": a_price,
                        "severity": "warning"
                    })
                    
                # So sánh Thuế %
                o_vat = float(o_item.get("vat_rate", 0.0))
                a_vat = float(a_item.get("vat_rate", 0.0))
                if abs(o_vat - a_vat) > 0.01:
                    has_vat_diff = True
                    differences.append({
                        "type": "tax_diff",
                        "product_code": code,
                        "product_name": prod_name,
                        "field": "vat_rate",
                        "odoo_value": o_vat,
                        "misa_value": a_vat,
                        "severity": "warning"
                    })

        # Xác định status tổng thể
        if not differences:
            return ("matched", "info", None, None, [])
        
        # Xác định root_cause
        if has_missing_in_amis:
            root_cause = "workflow_missing"
            suggested = "Đơn hàng chưa được đồng bộ sang MISA. Kiểm tra workflow AMIS Mua hàng"
        elif has_missing_in_odoo:
            root_cause = "workflow_missing"
            suggested = "Sản phẩm tồn tại trên MISA nhưng chưa có trên Odoo. Kiểm tra app auto đồng bộ"
        elif has_qty_diff and has_price_diff:
            root_cause = "manual_edit"
            suggested = "Cả số lượng và đơn giá đều lệch. Kiểm tra chứng từ gốc và đối chiếu với nhà cung cấp"
        elif has_qty_diff:
            root_cause = "partial_receipt"
            suggested = "Số lượng nhập kho không khớp. Kiểm tra phiếu nhập kho thực tế, đối chiếu với chứng từ gốc"
        elif has_price_diff:
            root_cause = "manual_edit"
            suggested = "Đơn giá giữa Odoo và MISA không khớp. Kiểm tra biên bản thỏa thuận giá"
        elif has_total_diff:
            root_cause = "tax_fee_diff"
            suggested = "Lệch tổng tiền do Thuế, Phí hoặc làm tròn. Kiểm tra chi phí phát sinh"
        else:
            root_cause = "unknown"
            suggested = "Có sai lệch không xác định. Kiểm tra thủ công"

        # Xác định severity tổng thể
        severities = [d["severity"] for d in differences]
        if "critical" in severities:
            overall_severity = "critical"
        elif "warning" in severities:
            overall_severity = "warning"
        else:
            overall_severity = "info"

        # Xác định status tổng thể
        if has_missing_in_amis or has_missing_in_odoo:
            status = "missing_in_misa" if has_missing_in_amis else "missing_in_odoo"
        elif has_qty_diff and has_price_diff:
            status = "qty_price_mismatch"
        elif has_qty_diff:
            status = "qty_mismatch"
        elif has_price_diff:
            status = "price_mismatch"
        elif has_vat_diff or has_total_diff:
            status = "tax_diff"
        else:
            status = "diff"

        return (status, overall_severity, root_cause, suggested, differences)

    def _get_odoo_line_details(self, po):
        """Trích xuất chi tiết dòng sản phẩm từ PO Odoo, bao gồm receipt history."""
        lines = []
        for oline in po.order_line:
            if oline.display_type:
                continue
            orig_code = (oline.product_id.default_code or "").strip()
            prod_name = (oline.product_id.name or "").strip()
            code = orig_code.lower()
            if not code:
                code = "unknown_code"
                orig_code = "Unknown"
            
            # Lấy lịch sử nhập kho
            receipt_history = []
            for pick in po.picking_ids.filtered(lambda p: p.state == 'done'):
                for move in pick.move_ids.filtered(lambda m: m.product_id == oline.product_id):
                    receipt_history.append({
                        "picking": pick.name,
                        "date": pick.date_done.strftime("%Y-%m-%d") if pick.date_done else "",
                        "qty": move.product_uom_qty
                    })
            
            display = f"[{orig_code}] {prod_name}" if orig_code != "Unknown" else "Unknown Code"
            display = display.replace("'", "`")
            
            vat_rate = oline.taxes_id[0].amount if oline.taxes_id else 0.0
            
            lines.append({
                "code": code,
                "orig_code": orig_code,
                "name": prod_name,
                "display": display,
                "qty": oline.product_qty,
                "qty_received": oline.qty_received,
                "price_unit": oline.price_unit,
                "price_subtotal": oline.price_subtotal,
                "price_tax": oline.price_tax,
                "vat_rate": vat_rate,
                "receipt_history": receipt_history
            })
        return lines

    def _detect_duplicate_po(self, po_name, all_po_names):
        """
        Phát hiện PO Odoo có khả năng bị trùng/ghép với PO MISA.
        VD: DMH123 và DMH123-1 cùng mapping với 1 PO MISA.
        """
        # Tìm các PO khác có cùng prefix
        base_name = po_name
        # Loại bỏ hậu tố như -1, -2, _copy, v.v.
        import re as _re
        m = _re.match(r"^(.*?)(?:[-_]\d+|_copy\d*)$", po_name)
        if m:
            base_name = m.group(1)
        
        duplicates = []
        for other in all_po_names:
            if other == po_name:
                continue
            if other.startswith(base_name) or base_name.startswith(other):
                duplicates.append(other)
        return duplicates

    # ============================================================
    # POST /api/extension/po/reconcile
    # ============================================================
    @http.route(
        "/api/extension/po/reconcile",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_po_reconcile(self, **kwargs):
        """
        Đối chiếu Đơn mua hàng (PO) dựa trên các Đơn ĐÃ NHẬP KHO trên Odoo.
        
        Response bao gồm cả format cũ (matched/diff/odoo_only) để giữ backward compatibility
        và format mới (reconciled/summary) với thông tin chi tiết.
        """
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*")])

        payload = self._parse_json_body(kwargs)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)

        def json_response(data, status=200):
            return request.make_response(
                json.dumps(data),
                headers=[
                    ("Content-Type", "application/json"),
                    ("Access-Control-Allow-Origin", "*"),
                ],
                status=status,
            )

        if not ok:
            return json_response(err, 401)

        date_from_str = payload.get("date_from")
        date_to_str = payload.get("date_to")
        if not date_from_str or not date_to_str:
            return json_response({"ok": False, "error": "missing_date", "message": "Missing date_from or date_to"}, 400)

        try:
            from datetime import datetime
            import concurrent.futures
            
            env_admin = request.env(su=True)
            misa_utils = env_admin['misa.api.utils']
            misa_config = env_admin['misa.config']
            access_token = misa_utils._get_misa_token()
            headers = misa_config.get_default_headers(access_token)
            
            date_from_utc = datetime.strptime(date_from_str, "%Y-%m-%d").strftime('%Y-%m-%d 00:00:00')
            date_to_utc = datetime.strptime(date_to_str, "%Y-%m-%d").strftime('%Y-%m-%d 23:59:59')
            
            # Lấy các phiếu nhập kho đã hoàn thành
            pickings = env_admin['stock.picking'].search([
                ('date_done', '>=', date_from_utc),
                ('date_done', '<=', date_to_utc),
                ('state', '=', 'done'),
                ('picking_type_id.code', '=', 'incoming'),
                ('purchase_id', '!=', False)
            ])
            
            # Lấy các Đơn mua hàng liên quan
            odoo_pos = pickings.mapped('purchase_id')
            
            if not odoo_pos:
                return json_response({
                    "ok": True,
                    "data": {
                        "matched": [], "diff": [], "odoo_only": [], "total_odoo": 0
                    },
                    "summary": {
                        "total_odoo": 0,
                        "total_misa": 0,
                        "by_status": {},
                        "by_severity": {}
                    },
                    "reconciled": []
                })
                
            amis_dict = {}
            # Lấy list các mã PO cần tìm (bao gồm name và origin)
            search_codes = set()
            for po in odoo_pos:
                if po.name:
                    search_codes.add(po.name.strip())
                if po.origin:
                    for org in po.origin.split(','):
                        if org.strip():
                            search_codes.add(org.strip())

            def _search_po_in_misa_by_code(po_name):
                """
                Tìm kiếm Đơn mua hàng (PO) trong MISA AMIS theo mã đơn.
                Sử dụng customFilter với property=4008 (refno) để tìm chính xác,
                không phụ thuộc vào khoảng thời gian (dùng date range rộng để tránh timeout).
                """
                _logger.info("🔍 _search_po_in_misa_by_code: searching for PO '%s' in MISA", po_name)
                try:
                    from datetime import datetime, timezone
                    
                    custom_filter = [{
                        "property": 4008,
                        "value": po_name,
                        "operator": 1,
                        "operand": 1,
                        "data_type": 1
                    }]

                    amis_payload = {
                        "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
                        "filter": [
                            {
                                "property": 3972,
                                "value": "2015-01-01T00:00:00.00Z",
                                "operator": 10,
                                "operand": 1,
                                "data_type": 3
                            },
                            {
                                "property": 3972,
                                "value": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                                "operator": 12,
                                "operand": 1,
                                "data_type": 3
                            }
                        ],
                        "customFilter": custom_filter,
                        "pageIndex": 1,
                        "pageSize": 100,
                        "useSp": False,
                        "view": 2,
                        "summaryColumns": [5039, 5104, 247],
                        "loadMode": 2
                    }

                    local_headers = dict(headers)
                    _logger.info("🔍 Sending request to MISA API for PO '%s'", po_name)
                    response = misa_utils._fetch_with_retry(
                        "https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2",
                        local_headers, amis_payload
                    )
                    _logger.info("🔍 MISA API response status for '%s': %s", po_name, response.status_code)

                    if response.status_code == 200:
                        resp_json = response.json()
                        _logger.info("🔍 MISA API response for '%s': Success=%s, Code=%s", 
                                     po_name, resp_json.get("Success"), resp_json.get("Code"))
                        
                        data_obj = resp_json.get("Data")
                        if isinstance(data_obj, str):
                            import json as json_lib
                            try:
                                data_obj = json_lib.loads(data_obj)
                            except:
                                data_obj = {}
                        if not data_obj:
                            data_obj = {}
                        
                        page_data = data_obj.get("PageData", [])
                        total = data_obj.get("Total", "N/A")
                        _logger.info("🔍 MISA API for '%s': PageData count=%s, Total=%s", 
                                     po_name, len(page_data), total)
                        
                        if page_data:
                            # Ưu tiên tìm bản ghi có refno khớp chính xác
                            for apo in page_data:
                                refno = apo.get("refno")
                                _logger.info("🔍 Checking refno='%s' against po_name='%s'", refno, po_name)
                                if refno and refno.strip() == po_name.strip():
                                    _logger.info("✅ Tìm thấy PO %s trong MISA (refid: %s)", po_name, apo.get("refid"))
                                    return po_name, apo
                            # Nếu không có refno khớp chính xác, trả về bản ghi đầu tiên
                            if page_data:
                                _logger.warning("⚠️ Không tìm thấy refno khớp chính xác cho '%s', dùng kết quả đầu tiên (refno='%s')", 
                                                po_name, page_data[0].get("refno"))
                                return po_name, page_data[0]
                        else:
                            _logger.warning("⚠️ MISA API trả về PageData rỗng cho PO '%s' (Total=%s, TableEmpty=%s)", 
                                            po_name, total, data_obj.get("TableEmpty"))
                    else:
                        # Log chi tiết response khi không phải 200
                        try:
                            error_text = response.text[:500]
                        except Exception:
                            error_text = "Không thể đọc response text"
                        _logger.warning("⚠️ MISA API trả về status %s cho PO '%s': %s", 
                                        response.status_code, po_name, error_text)

                    _logger.warning("⚠️ Không tìm thấy PO %s trong MISA", po_name)
                except Exception as e:
                    _logger.warning("_search_po_in_misa_by_code exception for %s: %s", po_name, e)
                    import traceback
                    _logger.warning("Traceback: %s", traceback.format_exc())
                return po_name, None

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(_search_po_in_misa_by_code, code): code for code in search_codes}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        po_name, apo = future.result()
                        if apo:
                            # Chuẩn hóa key: strip whitespace để tránh lỗi lookup
                            amis_dict[po_name.strip()] = apo
                    except Exception as e:
                        _logger.warning("Future exception: %s", e)
            
            _logger.info("🔍 amis_dict keys after search: %s", list(amis_dict.keys()))
            _logger.info("🔍 amis_dict count: %s POs found in MISA", len(amis_dict))
            
            # ============================================================
            # BUILD RECONCILED DATA (NEW FORMAT)
            # ============================================================
            reconciled = []
            matched_old = []
            diff_old = []
            odoo_only_old = []
            
            # Collect all PO names for duplicate detection
            all_po_names = [po.name for po in odoo_pos]

            for po in odoo_pos:
                po_name = po.name
                po_origin = (po.origin or "").strip()
                
                _logger.info("🔍 Processing PO '%s' (origin='%s')", po_name, po_origin)
                
                # Lấy chi tiết dòng Odoo
                odoo_lines_detail = self._get_odoo_line_details(po)
                
                # Tìm trên AMIS - dùng key đã strip
                amis_po = amis_dict.get(po_name.strip())
                _logger.info("🔍 Lookup amis_dict with stripped po_name='%s': found=%s", po_name.strip(), bool(amis_po))
                if not amis_po and po_origin:
                    for org in po_origin.split(','):
                        org = org.strip()
                        if org and org in amis_dict:
                            amis_po = amis_dict[org]
                            _logger.info("🔍 Fallback lookup with origin='%s': found=%s", org, bool(amis_po))
                            break
                
                # Khởi tạo reconciled item
                reconciled_item = {
                    "po_name": po_name,
                    "po_origin": po_origin,
                    "partner": po.partner_id.name if po.partner_id else "",
                    "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
                    "odoo": {
                        "partner": po.partner_id.name if po.partner_id else "",
                        "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
                        "amount_total": po.amount_total,
                        "lines": odoo_lines_detail
                    },
                    "amis": None,
                    "differences": [],
                    "duplicate_warning": None
                }
                
                # Phát hiện duplicate PO
                dup_po_names = self._detect_duplicate_po(po_name, all_po_names)
                if dup_po_names:
                    reconciled_item["duplicate_warning"] = {
                        "message": f"Odoo có nhiều PO có cùng mã gốc: {', '.join([po_name] + dup_po_names)}. Kiểm tra khả năng sửa mã đơn.",
                        "related_pos": dup_po_names
                    }
                
                if not amis_po:
                    # Odoo only
                    status, severity, root_cause, suggested, diffs = self._classify_po_status(
                        {"amount_total": po.amount_total}, None, [], odoo_lines_detail
                    )
                    reconciled_item["status"] = status
                    reconciled_item["severity"] = severity
                    reconciled_item["root_cause"] = root_cause
                    reconciled_item["suggested_action"] = suggested
                    reconciled_item["differences"] = diffs
                    
                    odoo_only_old.append(po_name)
                else:
                    # Có trên AMIS, lấy chi tiết dòng qua API detail_full (1 call duy nhất)
                    refid = amis_po.get("refid")
                    amis_total = float(amis_po.get("total_amount") or 0.0)
                    amis_total_oc = float(amis_po.get("total_amount_oc", amis_total))
                    amis_total_vat = float(amis_po.get("total_vat_amount_oc", 0))
                    
                    # Gọi detail_full: 1 call thay vì loop paginated get_paging_detail
                    amis_lines = []
                    amis_header = {}
                    try:
                        import base64
                        import json as _json
                        import requests
                        # Template từ MISA: base64 encoded JSON với Key = refid
                        detail_full_payload = [{
                            "Type": "pu_order",
                            "Key": refid,
                            "RefType": 301,
                            "RefTypeCategory": 301,
                            "View": "view_pu_order",
                            "Details": [
                                {"Type": "pu_order_detail", "Alias": "detail", "View": "view_pu_order_detail"},
                                {"Type": "wesign_document", "Alias": "wesign_document", "ForeignKey": "refid", "Mode": "View"}
                            ]
                        }]
                        req_base64 = base64.b64encode(
                            _json.dumps(detail_full_payload, separators=(',', ':')).encode('utf-8')
                        ).decode('utf-8')
                        detail_url = f"https://actapp.misa.vn/g2/api/pu/v1/pu_order/detail_full?req={req_base64}"
                        
                        detail_res = requests.get(detail_url, headers=headers, timeout=30)
                        
                        if detail_res.status_code == 200:
                            dt_json = detail_res.json()
                            d_obj = dt_json.get("Data", {}) if isinstance(dt_json, dict) else {}
                            if isinstance(d_obj, str):
                                try:
                                    d_obj = _json.loads(d_obj)
                                except Exception:
                                    d_obj = {}
                            if not isinstance(d_obj, dict):
                                d_obj = {}
                            
                            # Parse header
                            pu_orders = d_obj.get("pu_order", [])
                            if pu_orders:
                                amis_header = pu_orders[0] if isinstance(pu_orders, list) else pu_orders
                            # Parse detail lines
                            amis_lines = d_obj.get("pu_order_detail", [])
                            if not isinstance(amis_lines, list):
                                amis_lines = []
                    except Exception as e:
                        _logger.warning("detail_full exception for %s: %s", po_name, e)
                    
                    # Build AMIS lines detail (phong phú hơn từ detail_full)
                    amis_lines_detail = []
                    for aline in amis_lines:
                        if not isinstance(aline, dict):
                            continue
                        orig_code = (aline.get("inventory_item_code") or "").strip()
                        prod_name = (aline.get("description") or aline.get("inventory_item_name") or "").strip()
                        code = orig_code.lower()
                        amis_lines_detail.append({
                            "code": code,
                            "orig_code": orig_code,
                            "name": prod_name,
                            "display": f"[{orig_code}] {prod_name}" if orig_code else "Unknown Code",
                            "qty": float(aline.get("quantity") or 0),
                            "qty_receipt": float(aline.get("quantity_receipt") or 0),
                            "price_unit": float(aline.get("unit_price") or aline.get("main_unit_price") or 0),
                            "amount": float(aline.get("amount") or aline.get("amount_oc") or 0),
                            "price_tax": float(aline.get("vat_amount") or aline.get("vat_amount_oc") or 0),
                            "vat_rate": float(aline.get("vat_rate") or 0),
                            "discount_rate": float(aline.get("discount_rate") or 0),
                            "discount_amount": float(aline.get("discount_amount") or aline.get("discount_amount_oc") or 0),
                        })
                    
                    reconciled_item["amis"] = {
                        "partner": amis_po.get("account_object_name", ""),
                        "refid": refid,
                        "refno": amis_po.get("refno", ""),
                        "amount_total": amis_total,
                        "lines": amis_lines_detail
                    }
                    
                    # Phân loại
                    status, severity, root_cause, suggested, diffs = self._classify_po_status(
                        {"amount_total": po.amount_total}, amis_po, amis_lines, odoo_lines_detail
                    )
                    reconciled_item["status"] = status
                    reconciled_item["severity"] = severity
                    reconciled_item["root_cause"] = root_cause
                    reconciled_item["suggested_action"] = suggested
                    reconciled_item["differences"] = diffs
                    
                    if status == "matched":
                        matched_old.append(po_name)
                    else:
                        # Build reason string for backward compatibility
                        reason_parts = []
                        for d in diffs:
                            if d["type"] == "price_mismatch" and d["product_code"] == "__total__":
                                reason_parts.append(f"Tổng tiền: Odoo={d['odoo_value']:,.0f} != AMIS={d['misa_value']:,.0f}")
                            elif d["type"] == "qty_mismatch":
                                reason_parts.append(f"Mã '{d['product_name']}': Odoo {d['odoo_value']} != AMIS {d['misa_value']}")
                            elif d["type"] == "missing_in_amis":
                                reason_parts.append(f"Mã '{d['product_name']}': Odoo có {d['odoo_value']} (AMIS thiếu)")
                            elif d["type"] == "missing_in_odoo":
                                reason_parts.append(f"Mã '{d['product_name']}': Odoo thiếu (AMIS có {d['misa_value']})")
                            elif d["type"] == "price_mismatch":
                                reason_parts.append(f"Mã '{d['product_name']}': ĐG Odoo {d['odoo_value']:,.0f} != AMIS {d['misa_value']:,.0f}")
                        
                        diff_old.append({
                            "po_name": po_name,
                            "reason": " | ".join(reason_parts)
                        })
                
                reconciled.append(reconciled_item)
            
            # ============================================================
            # BUILD SUMMARY
            # ============================================================
            by_status = {}
            by_severity = {}
            for item in reconciled:
                s = item["status"]
                by_status[s] = by_status.get(s, 0) + 1
                
                sev = item["severity"]
                if sev:
                    by_severity[sev] = by_severity.get(sev, 0) + 1
            
            summary = {
                "total_odoo": len(odoo_pos),
                "total_misa": len(amis_dict),
                "by_status": by_status,
                "by_severity": by_severity
            }
            
            # ============================================================
            # BUILD RESPONSE (OLD FORMAT + NEW FORMAT)
            # ============================================================
            return json_response({
                "ok": True,
                # Old format (backward compatible)
                "data": {
                    "matched": matched_old,
                    "diff": diff_old,
                    "odoo_only": odoo_only_old,
                    "total_odoo": len(odoo_pos)
                },
                # New format
                "summary": summary,
                "reconciled": reconciled
            })

        except Exception as e:
            _logger.exception("Extension API /po/reconcile exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)    # ============================================================
    # POST /api/extension/po/reconcile_only
    # ============================================================
    @http.route(
        "/api/extension/po/reconcile_only",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_po_reconcile_only(self, **kwargs):
        """
        Đối chiếu Đơn mua hàng (PO) dựa trên NGÀY LẬP ĐƠN (với cross-check).
        Tìm ra các PO bị thiếu ở MISA hoặc Odoo thực sự (bằng cách search ngược không giới hạn ngày).
        """
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*")])

        payload = self._parse_json_body(kwargs)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)

        def json_response(data, status=200):
            return request.make_response(
                json.dumps(data),
                headers=[
                    ("Content-Type", "application/json"),
                    ("Access-Control-Allow-Origin", "*"),
                ],
                status=status,
            )

        if not ok:
            return json_response(err, 401)

        date_from_str = payload.get("date_from")
        date_to_str = payload.get("date_to")
        if not date_from_str or not date_to_str:
            return json_response({"ok": False, "error": "missing_date", "message": "Missing date_from or date_to"}, 400)

        try:
            from datetime import datetime, timezone
            import concurrent.futures
            
            env_admin = request.env(su=True)
            misa_utils = env_admin['misa.api.utils']
            misa_config = env_admin['misa.config']
            access_token = misa_utils._get_misa_token()
            headers = misa_config.get_default_headers(access_token)
            
            date_from_dt = datetime.strptime(date_from_str, "%Y-%m-%d")
            date_to_dt = datetime.strptime(date_to_str, "%Y-%m-%d")
            
            date_from_utc = date_from_dt.strftime('%Y-%m-%d 00:00:00')
            date_to_utc = date_to_dt.strftime('%Y-%m-%d 23:59:59')
            
            date_from_iso = date_from_dt.strftime('%Y-%m-%dT00:00:00.00Z')
            date_to_iso = date_to_dt.strftime('%Y-%m-%dT23:59:59.00Z')
            
            # Lấy Odoo POs created/approved in date range
            odoo_pos = env_admin['purchase.order'].search([
                ('date_approve', '>=', date_from_utc),
                ('date_approve', '<=', date_to_utc),
                ('state', 'in', ['purchase', 'done'])
            ])
            odoo_pos_list = list(odoo_pos)
            
            # Tìm kiếm ALL POs trong MISA AMIS theo Date
            _logger.info("🔍 Fetching ALL POs from MISA between %s and %s", date_from_iso, date_to_iso)
            amis_dict = {}
            amis_all_list = []
            
            for page in range(1, 10):
                amis_payload = {
                    "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
                    "filter": [
                        {
                            "property": 3972,
                            "value": date_from_iso,
                            "operator": 10,
                            "operand": 1,
                            "data_type": 3
                        },
                        {
                            "property": 3972,
                            "value": date_to_iso,
                            "operator": 12,
                            "operand": 1,
                            "data_type": 3
                        }
                    ],
                    "pageIndex": page,
                    "pageSize": 500,
                    "useSp": False,
                    "view": 2,
                    "summaryColumns": [5039, 5104, 247],
                    "loadMode": 2
                }

                local_headers = dict(headers)
                response = misa_utils._fetch_with_retry(
                    "https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2",
                    local_headers, amis_payload
                )

                if response.status_code == 200:
                    resp_json = response.json()
                    data_obj = resp_json.get("Data")
                    if isinstance(data_obj, str):
                        import json as json_lib
                        try: data_obj = json_lib.loads(data_obj)
                        except: data_obj = {}
                    if not data_obj: break
                    
                    page_data = data_obj.get("PageData", [])
                    if not page_data: break
                        
                    for apo in page_data:
                        refno = apo.get("refno")
                        if refno:
                            amis_dict[refno.strip()] = apo
                            amis_all_list.append(apo)
                else:
                    break
            
            # CROSS-CHECK: Search Odoo POs that are missing in amis_dict
            def _search_po_in_misa_by_code(po_name):
                try:
                    custom_filter = [{
                        "property": 4008,
                        "value": po_name,
                        "operator": 1,
                        "operand": 1,
                        "data_type": 1
                    }]
                    payload2 = {
                        "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
                        "filter": [
                            {"property": 3972, "value": "2015-01-01T00:00:00.00Z", "operator": 10, "operand": 1, "data_type": 3},
                            {"property": 3972, "value": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), "operator": 12, "operand": 1, "data_type": 3}
                        ],
                        "customFilter": custom_filter,
                        "pageIndex": 1,
                        "pageSize": 100,
                        "useSp": False,
                        "view": 2,
                        "summaryColumns": [5039, 5104, 247],
                        "loadMode": 2
                    }
                    res2 = misa_utils._fetch_with_retry("https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2", dict(headers), payload2)
                    if res2.status_code == 200:
                        d2 = res2.json().get("Data", {})
                        if isinstance(d2, str):
                            import json as json_lib
                            try: d2 = json_lib.loads(d2)
                            except: d2 = {}
                        p2 = d2.get("PageData", []) if isinstance(d2, dict) else []
                        for a2 in p2:
                            r2 = a2.get("refno")
                            if r2 and r2.strip() == po_name.strip():
                                return po_name, a2
                        if p2: return po_name, p2[0]
                except Exception as e:
                    _logger.warning("_search_po_in_misa_by_code ex for %s: %s", po_name, e)
                return po_name, None

            missing_in_misa_names = []
            for po in odoo_pos_list:
                if po.name.strip() not in amis_dict:
                    missing_in_misa_names.append(po.name.strip())
                    
            if missing_in_misa_names:
                _logger.info("🔍 CROSS-CHECK: %d Odoo POs missing in MISA date range. Searching exact matches...", len(missing_in_misa_names))
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(_search_po_in_misa_by_code, name): name for name in missing_in_misa_names}
                    for future in concurrent.futures.as_completed(futures):
                        po_name, apo = future.result()
                        if apo:
                            _logger.info("✅ CROSS-CHECK: Found PO %s in MISA!", po_name)
                            amis_dict[po_name.strip()] = apo
                            amis_all_list.append(apo)
                            
            # CROSS-CHECK: Search MISA POs that are missing in odoo_pos_list
            odoo_po_names_lower = {po.name.strip().lower() for po in odoo_pos_list}
            missing_in_odoo_refnos = []
            for apo in amis_all_list:
                refno = apo.get("refno", "").strip()
                if refno and refno.lower() not in odoo_po_names_lower:
                    missing_in_odoo_refnos.append(refno)
                    
            if missing_in_odoo_refnos:
                _logger.info("🔍 CROSS-CHECK: %d MISA POs missing in Odoo date range. Searching exact matches...", len(missing_in_odoo_refnos))
                found_in_odoo = env_admin['purchase.order'].search([
                    ('name', 'in', missing_in_odoo_refnos),
                    ('state', 'in', ['purchase', 'done'])
                ])
                for po in found_in_odoo:
                    if po.name.strip().lower() not in odoo_po_names_lower:
                        _logger.info("✅ CROSS-CHECK: Found PO %s in Odoo!", po.name)
                        odoo_pos_list.append(po)
                        odoo_po_names_lower.add(po.name.strip().lower())

            # ============================================================
            # BUILD RECONCILED DATA
            # ============================================================
            reconciled = []
            matched_old = []
            diff_old = []
            odoo_only_old = []
            
            processed_misa_refnos = set()
            all_po_names = [po.name for po in odoo_pos_list]

            for po in odoo_pos_list:
                po_name = po.name
                po_origin = (po.origin or "").strip()
                
                odoo_lines_detail = self._get_odoo_line_details(po)
                
                amis_po = amis_dict.get(po_name.strip())
                if amis_po:
                    processed_misa_refnos.add(po_name.strip())
                if not amis_po and po_origin:
                    for org in po_origin.split(','):
                        org = org.strip()
                        if org and org in amis_dict:
                            amis_po = amis_dict[org]
                            processed_misa_refnos.add(org)
                            break
                
                reconciled_item = {
                    "po_name": po_name,
                    "po_origin": po_origin,
                    "partner": po.partner_id.name if po.partner_id else "",
                    "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
                    "odoo": {
                        "partner": po.partner_id.name if po.partner_id else "",
                        "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
                        "amount_total": po.amount_total,
                        "lines": odoo_lines_detail
                    },
                    "amis": None,
                    "differences": [],
                    "duplicate_warning": None
                }
                
                dup_po_names = self._detect_duplicate_po(po_name, all_po_names)
                if dup_po_names:
                    reconciled_item["duplicate_warning"] = {
                        "message": f"Odoo có nhiều PO cùng mã gốc: {', '.join([po_name] + dup_po_names)}.",
                        "related_pos": dup_po_names
                    }
                
                if not amis_po:
                    status, severity, root_cause, suggested, diffs = self._classify_po_status(
                        {"amount_total": po.amount_total}, None, [], odoo_lines_detail
                    )
                    reconciled_item["status"] = "missing_in_misa"
                    reconciled_item["severity"] = "critical"
                    reconciled_item["root_cause"] = "odoo_only"
                    reconciled_item["suggested_action"] = "Tạo ĐMH trên AMIS"
                    reconciled_item["differences"] = [{"type": "system", "desc": "Đơn không tồn tại trên MISA"}]
                    
                    odoo_only_old.append(po_name)
                else:
                    refid = amis_po.get("refid")
                    amis_total = float(amis_po.get("total_amount") or 0.0)
                    amis_total_oc = float(amis_po.get("total_amount_oc", amis_total))
                    
                    amis_lines = []
                    amis_header = {}
                    try:
                        import base64
                        import json as _json
                        import requests
                        detail_full_payload = [{
                            "Type": "pu_order",
                            "Key": refid,
                            "RefType": 301,
                            "RefTypeCategory": 301,
                            "View": "view_pu_order",
                            "Details": [
                                {"Type": "pu_order_detail", "Alias": "detail", "View": "view_pu_order_detail"}
                            ]
                        }]
                        req_base64 = base64.b64encode(
                            _json.dumps(detail_full_payload, separators=(',', ':')).encode('utf-8')
                        ).decode('utf-8')
                        detail_url = f"https://actapp.misa.vn/g2/api/pu/v1/pu_order/detail_full?req={req_base64}"
                        detail_res = requests.get(detail_url, headers=headers, timeout=30)
                        
                        if detail_res.status_code == 200:
                            dt_json = detail_res.json()
                            d_obj = dt_json.get("Data", {}) if isinstance(dt_json, dict) else {}
                            if isinstance(d_obj, str):
                                try: d_obj = _json.loads(d_obj)
                                except Exception: d_obj = {}
                            if isinstance(d_obj, dict):
                                pu_orders = d_obj.get("pu_order", [])
                                if pu_orders:
                                    amis_header = pu_orders[0] if isinstance(pu_orders, list) else pu_orders
                                amis_lines = d_obj.get("pu_order_detail", [])
                    except Exception as e:
                        _logger.warning("detail_full exception for %s: %s", po_name, e)
                    
                    # V>i "?`i chiu ?MH", chA1ng ta ch% so sAnh s` lng `t hAng (ordered qty)
                    # nAn ta ghi `A? qty_received bng qty ` hAm _classify_po_status so sAnh chA-nh xAc.
                    for ol in odoo_lines_detail:
                        ol["qty_received"] = ol.get("qty", 0.0)

                    amis_lines_detail = []
                    for aline in amis_lines:
                        if not isinstance(aline, dict): continue
                        
                        # Ghi `A? quantity_receipt bng quantity ` _classify_po_status so sAnh s` lng `t hAng
                        aline["quantity_receipt"] = aline.get("quantity", 0.0)
                        
                        orig_code = (aline.get("inventory_item_code") or "").strip()
                        prod_name = (aline.get("description") or aline.get("inventory_item_name") or "").strip()
                        code = orig_code.lower()
                        amis_lines_detail.append({
                            "code": code,
                            "orig_code": orig_code,
                            "name": prod_name,
                            "display": f"[{orig_code}] {prod_name}" if orig_code else "Unknown Code",
                            "qty": float(aline.get("quantity") or 0),
                            "qty_receipt": float(aline.get("quantity") or 0),
                            "price_unit": float(aline.get("unit_price") or aline.get("main_unit_price") or 0),
                            "amount": float(aline.get("amount") or aline.get("amount_oc") or 0),
                            "price_tax": float(aline.get("vat_amount") or aline.get("vat_amount_oc") or 0),
                            "vat_rate": float(aline.get("vat_rate") or 0)
                        })
                    
                    reconciled_item["amis"] = {
                        "partner": amis_header.get("account_object_name") or amis_po.get("account_object_name") or "",
                        "date_order": amis_po.get("refdate", "")[:10],
                        "amount_total": amis_total_oc,
                        "lines": amis_lines_detail
                    }
                    
                    status, severity, root_cause, suggested, diffs = self._classify_po_status(
                        reconciled_item["odoo"], amis_po, amis_lines, odoo_lines_detail
                    )
                    reconciled_item["status"] = status
                    reconciled_item["severity"] = severity
                    reconciled_item["root_cause"] = root_cause
                    reconciled_item["suggested_action"] = suggested
                    reconciled_item["differences"] = diffs
                    
                    if status == "matched":
                        matched_old.append(po_name)
                    else:
                        diff_old.append(po_name)
                
                reconciled.append(reconciled_item)

            # ============================================================
            # MISA ONLY
            # ============================================================
            for apo in amis_all_list:
                refno = apo.get("refno", "").strip()
                if refno not in processed_misa_refnos:
                    # MISA Only item
                    reconciled_item = {
                        "po_name": refno,
                        "po_origin": "",
                        "partner": apo.get("account_object_name") or "",
                        "date_order": apo.get("refdate", "")[:10],
                        "odoo": None,
                        "amis": {
                            "partner": apo.get("account_object_name") or "",
                            "date_order": apo.get("refdate", "")[:10],
                            "amount_total": float(apo.get("total_amount_oc", apo.get("total_amount") or 0)),
                            "lines": []
                        },
                        "status": "missing_in_odoo",
                        "severity": "critical",
                        "root_cause": "misa_only",
                        "suggested_action": "Tạo PO trên Odoo",
                        "differences": [{"type": "system", "desc": "Đơn có trên MISA nhưng không có trên Odoo"}],
                        "duplicate_warning": None
                    }
                    reconciled.append(reconciled_item)

            reconciled.sort(key=lambda x: (x.get("status", ""), x.get("po_name", "")))

            by_status = {}
            by_severity = {}
            for item in reconciled:
                s = item["status"]
                by_status[s] = by_status.get(s, 0) + 1
                sev = item["severity"]
                if sev:
                    by_severity[sev] = by_severity.get(sev, 0) + 1
            
            summary = {
                "total_odoo": len(odoo_pos_list),
                "total_misa": len(amis_dict),
                "by_status": by_status,
                "by_severity": by_severity
            }
            
            return json_response({
                "ok": True,
                "data": {
                    "matched": matched_old,
                    "diff": diff_old,
                    "odoo_only": odoo_only_old,
                    "total_odoo": len(odoo_pos_list)
                },
                "summary": summary,
                "reconciled": reconciled
            })

        except Exception as e:
            _logger.exception("Extension API /po/reconcile_only exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)

