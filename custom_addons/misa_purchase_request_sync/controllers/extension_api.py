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

                lines_data.append({
                    "product_code": line.product_id.default_code if line.product_id else "",
                    "name": line.name,
                    "qty": line.product_qty,
                    "qty_received": qty_received,
                })

            can_revoke = pr.state in ['draft', 'to_approve']

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

        try:
            if pr.state != 'draft':
                pr.button_draft()
            pr.unlink()
            return json_response({"ok": True, "message": "Đã thu hồi YCMH thành công."})
        except Exception as e:
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)

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
            pr = pr_model.search([("name", "=", pr_name)], limit=1)
            if pr:
                if pr.state not in ['draft', 'to_approve']:
                    return json_response({
                        "ok": False, 
                        "error": "invalid_state", 
                        "message": f"YCMH {pr_name} đã tồn tại và ở trạng thái {pr.state}, không thể cập nhật."
                    }, 400)
                # Xóa lines cũ để tạo lại
                pr.line_ids.unlink()
                
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

            # --- Tạo lines ---
            line_model = env_admin["purchase.request.line"]
            product_model = env_admin["product.product"]
            uom_model = env_admin["uom.uom"]

            for idx, line in enumerate(lines_in, start=1):
                if not isinstance(line, dict):
                    continue

                product = False
                pcode = (line.get("product_code") or "").strip()
                if pcode:
                    product = product_model.search(
                        [("default_code", "=ilike", pcode)], limit=1
                    )
                if not product:
                    # Fallback: tìm theo tên
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
                            token = OdooUtilsClass._get_token_api_crm()
                            product = odoo_utils.get_misa_product(token, pcode)
                    except Exception as e:
                        _logger.error("Lỗi khi fetch sản phẩm từ MISA: %s", str(e))

                uom = False
                uom_name = (line.get("uom") or "").strip()
                
                # Ưu tiên sử dụng UoM của sản phẩm nếu trùng tên (tránh lỗi khác Category)
                if product and uom_name:
                    if uom_name.lower() == product.uom_id.name.lower():
                        uom = product.uom_id
                    elif product.uom_po_id and uom_name.lower() == product.uom_po_id.name.lower():
                        uom = product.uom_po_id
                        
                if not uom and uom_name:
                    # Nếu có product, thử tìm UoM cùng tên và cùng Category với product trước
                    if product:
                        uom = uom_model.search([("name", "=ilike", uom_name), ("category_id", "=", product.uom_id.category_id.id)], limit=1)
                    # Nếu vẫn không thấy, tìm tự do
                    if not uom:
                        uom = uom_model.search([("name", "=ilike", uom_name)], limit=1)
                        
                if not uom and product:
                    uom = product.uom_id

                estimated_cost = 0.0
                if product:
                    supplier_info = env_admin['product.supplierinfo'].search([
                        ('product_tmpl_id', '=', product.product_tmpl_id.id)
                    ], limit=1, order='sequence, min_qty desc, price')
                    if supplier_info:
                        estimated_cost = supplier_info.price
                    else:
                        last_po_line = env_admin['purchase.order.line'].search([
                            ('product_id', '=', product.id),
                            ('state', 'in', ['purchase', 'done'])
                        ], limit=1, order='create_date desc')
                        if last_po_line:
                            estimated_cost = last_po_line.price_unit
                        else:
                            estimated_cost = product.standard_price

                line_vals = {
                    "request_id": pr.id,
                    "name": line.get("name") or (product.display_name if product else ""),
                    "product_id": product.id if product else False,
                    "product_qty": float(line.get("qty") or 0.0),
                    "product_uom_id": uom.id if uom else False,
                    "estimated_cost": estimated_cost,
                }
                if date_required:
                    line_vals["date_required"] = date_required
                    
                line_model.create(line_vals)

            # --- Post Chatter nếu là Admin fallback ---
            if owner_message:
                pr.message_post(body=owner_message)

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
