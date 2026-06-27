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
                    
                purchase_state = line.purchase_state if hasattr(line, 'purchase_state') else False

                lines_data.append({
                    "product_code": line.product_id.default_code if line.product_id else "",
                    "name": line.name,
                    "qty": line.product_qty,
                    "qty_received": qty_received,
                    "purchase_state": purchase_state,
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
                    }
                })
                
            from datetime import timedelta
            min_order_date = min(odoo_pos.mapped('date_order'))
            max_order_date = max(odoo_pos.mapped('date_order'))
            
            # Fetch AMIS POs created around Odoo PO creation dates
            misa_date_from_utc = min_order_date - timedelta(days=5)
            misa_date_to_utc = max_order_date + timedelta(days=2)
            
            amis_payload = {
                "filter": [
                    {
                        "property": 3972,
                        "value": misa_date_from_utc.isoformat() + "Z",
                        "operator": 10,
                        "operand": 1,
                        "data_type": 3
                    },
                    {
                        "property": 3972,
                        "value": misa_date_to_utc.isoformat() + "Z",
                        "operator": 12,
                        "operand": 1,
                        "data_type": 3
                    }
                ],
                "loadMode": 2, "pageIndex": 1, "pageSize": 1000, 
                "useSp": False, "view": 2, "summaryColumns": []
            }
            
            response = misa_utils._fetch_with_retry("https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2", headers, amis_payload)
            amis_dict = {}
            if response.status_code == 200:
                resp_json = response.json()
                data_obj = resp_json.get("Data")
                if isinstance(data_obj, str):
                    import json as json_lib
                    try: data_obj = json_lib.loads(data_obj)
                    except: data_obj = {}
                if not data_obj: data_obj = {}
                for apo in data_obj.get("PageData", []):
                    refno = apo.get("refno")
                    if refno:
                        amis_dict[refno] = apo
            
            matched = []
            diff = []
            odoo_only = []

            # Trích xuất dữ liệu từ Odoo ra dạng dict (chỉ chạy trên main thread để tránh lỗi cursor)
            odoo_data_list = []
            for po in odoo_pos:
                odoo_prod_qty = {}
                for oline in po.order_line:
                    code = (oline.product_id.default_code or "").strip().lower()
                    if not code:
                        code = "unknown_code"
                    qty = oline.qty_received
                    odoo_prod_qty[code] = odoo_prod_qty.get(code, 0.0) + qty
                    
                odoo_data_list.append({
                    "name": po.name,
                    "origin": po.origin or "",
                    "amount_total": po.amount_total,
                    "prod_qty": odoo_prod_qty
                })

            import requests
            def _reconcile_po_data(po_data):
                po_name = po_data["name"]
                po_origin = po_data["origin"]
                
                # Tìm trên AMIS
                amis_po = amis_dict.get(po_name)
                if not amis_po and po_origin:
                    amis_po = amis_dict.get(po_origin)
                    
                if not amis_po:
                    return {"status": "odoo_only", "po_name": po_name}
                    
                refid = amis_po.get("refid")
                amis_total = float(amis_po.get("total_amount") or 0.0)
                odoo_total = po_data["amount_total"]
                
                # Lấy chi tiết dòng của AMIS PO
                detail_page_index = 1
                amis_lines = []
                while True:
                    detail_payload = {
                        "columns": [2157, 1355, 2161, 4670, 1127, 5683, 5274, 3870, 3895, 5279, 308, 5364, 5350, 3404, 2358],
                        "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                        "filter": [{"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}],
                        "pageIndex": detail_page_index,
                        "pageSize": 50,
                        "useSp": False,
                        "view": 92,
                        "summaryColumns": [3488, 3870, 3895, 3896, 308, 5350],
                        "loadMode": 2
                    }
                    try:
                        detail_res = requests.post("https://actapp.misa.vn/g1/api/pu/v1/pu_order/get_paging_detail", headers=headers, json=detail_payload, timeout=30)
                        if detail_res.status_code != 200:
                            break
                        det_json = detail_res.json()
                    except Exception:
                        break
                        
                    d_obj = det_json.get("Data")
                    if isinstance(d_obj, str):
                        import json as json_lib
                        try: d_obj = json_lib.loads(d_obj)
                        except: d_obj = {}
                    if not d_obj: d_obj = {}
                    page_lines = d_obj.get("PageData", [])
                    if not page_lines:
                        break
                    amis_lines.extend(page_lines)
                    detail_page_index += 1
                    
                amis_prod_qty = {}
                for aline in amis_lines:
                    code = aline.get("inventory_item_code", "unknown_code").strip().lower()
                    qty = float(aline.get("quantity_receipt", 0))
                    amis_prod_qty[code] = amis_prod_qty.get(code, 0.0) + qty
                    
                odoo_prod_qty = po_data["prod_qty"]
                    
                line_diffs = []
                for code, o_qty in odoo_prod_qty.items():
                    a_qty = amis_prod_qty.get(code, 0.0)
                    if abs(o_qty - a_qty) > 0.01:
                        line_diffs.append(f"Mã '{code}': Odoo {o_qty} != AMIS {a_qty} (Debug: lines={len(amis_lines)})")
                for code, a_qty in amis_prod_qty.items():
                    if code not in odoo_prod_qty:
                        line_diffs.append(f"Mã '{code}': Odoo thiếu (AMIS có {a_qty}) (Debug: lines={len(amis_lines)})")
                        
                amt_diff = ""
                if abs(odoo_total - amis_total) >= 1.0:
                    amt_diff = f"Tổng tiền: Odoo={odoo_total:,.0f} != AMIS={amis_total:,.0f}"
                    
                if not line_diffs and not amt_diff:
                    return {"status": "matched", "po_name": po_name}
                else:
                    reasons = []
                    if amt_diff: reasons.append(amt_diff)
                    reasons.extend(line_diffs)
                    return {"status": "diff", "po_name": po_name, "reason": " | ".join(reasons)}

            # Thực thi đa luồng (max 4 luồng để tránh quá tải)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(_reconcile_po_data, odoo_data_list))
                
            for res in results:
                if res["status"] == "matched":
                    matched.append(res["po_name"])
                elif res["status"] == "diff":
                    diff.append({"po_name": res["po_name"], "reason": res["reason"]})
                else:
                    odoo_only.append(res["po_name"])

            return json_response({
                "ok": True,
                "data": {
                    "matched": matched,
                    "diff": diff,
                    "odoo_only": odoo_only,
                    "total_odoo": len(odoo_pos)
                }
            })

        except Exception as e:
            _logger.exception("Extension API /po/reconcile exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)
