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

from odoo import fields, http
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
            queue = env["misa.sync.queue"].sudo().search([
                ('name', '=', name),
                ('sync_type', '=', 'pr'),
                ('state', 'in', ['draft', 'processing'])
            ], limit=1)
            
            if queue:
                payload = {
                    "ok": True,
                    "exists": True,
                    "name": name,
                    "status": "queued",
                    "status_label": "Đang chờ đồng bộ...",
                    "can_revoke": False
                }
            else:
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
    # GET /api/extension/so/check?name=SO00001
    # ============================================================
    @http.route(
        "/api/extension/so/check",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_extension_so_check(self, **kwargs):
        """
        Kiểm tra Đơn bán hàng đã tồn tại trên Odoo hay chưa.
        """
        token = _clean_token(kwargs.get("token")) or _clean_token(
            request.httprequest.headers.get("X-MISA-Token")
        )
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        name = (kwargs.get("name") or "").strip()
        misa_id = (kwargs.get("misa_id") or "").strip()
        
        if not name and not misa_id:
            return request.make_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "missing_params",
                        "message": "Thiếu tham số 'name' hoặc 'misa_id'.",
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env
        
        # 1. Kiểm tra trong hàng chờ đồng bộ (misa.sync.queue) trước
        search_queue_domain = [
            ('sync_type', '=', 'so'),
            ('state', 'in', ['draft', 'processing'])
        ]
        if misa_id and name:
            search_queue_domain.extend(['|', ('name', '=', misa_id), ('name', '=', name)])
        elif misa_id:
            search_queue_domain.append(('name', '=', misa_id))
        else:
            search_queue_domain.append(('name', '=', name))

        queue = env["misa.sync.queue"].sudo().search(search_queue_domain, limit=1)
        if queue:
            payload = {
                "ok": True,
                "exists": True,
                "status": "queued",
                "status_label": "Đang chờ đồng bộ...",
                "can_revoke": False
            }
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")]
            )

        # 2. Kiểm tra Đơn bán hàng trên Odoo
        domain = []
        if misa_id:
            domain = [("misa_id", "=", misa_id)]
        else:
            domain = [("name", "=", name)]
            
        so = env["sale.order"].sudo().search(domain, limit=1)

        if not so:
            payload = {"ok": True, "exists": False}
        else:
            state_label = (
                dict(so._fields["state"].selection).get(so.state, so.state)
                if so.state
                else ""
            )
            lines_data = []
            for line in so.order_line:
                if line.display_type:
                    continue
                lines_data.append({
                    "misa_line_id": line.misa_crm_line_id if hasattr(line, 'misa_crm_line_id') and line.misa_crm_line_id else "",
                    "product_code": line.product_id.default_code if line.product_id else "",
                    "name": line.name or "",
                    "qty": line.product_uom_qty,
                    "price": line.price_unit,
                    "discount": line.discount,
                    "tax_percentages": sorted(line.tax_id.mapped('amount')),
                    "uom": line.product_uom.name or "",
                    "qty_delivered": line.qty_delivered if hasattr(line, 'qty_delivered') else 0.0,
                })

            # Nếu đơn đã hủy trên Odoo, hiển thị Đã hủy và cho phép đồng bộ lại
            if so.state == 'cancel':
                payload = {
                    "ok": True,
                    "exists": True,
                    "id": so.id,
                    "name": so.name,
                    "status": "cancel",
                    "status_label": "Đã hủy",
                    "can_revoke": False,
                    "can_resync": True,
                    "message": "Đơn đã bị hủy trên Odoo, có thể đồng bộ lại.",
                    "lines": lines_data,
                }
                return request.make_response(
                    json.dumps(payload), headers=[("Content-Type", "application/json")]
                )
            else:
                # Kiểm tra OUT đã hoàn tất — nếu có thì không cho thu hồi
                # PICK/PACK dù đã done vẫn cho thu hồi (chỉ chặn OUT)
                out_done = so.picking_ids.filtered(
                    lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'done'
                )
                can_revoke = not bool(out_done)

                # --- KIỂM TRA PHIÊN BẢN VÀ TRẠNG THÁI CHỜ DUYỆT (TOÁN TỬ 3 CẤP) ---
                is_pending = bool(getattr(so, 'misa_qty_sync_pending', False))
                is_edit_locked = bool(getattr(so, 'misa_sale_edit_locked', False))
                edit_locked_at = getattr(so, 'misa_sale_edit_locked_at', False)
                history_rec = getattr(so, 'misa_qty_sync_pending_history_id', None)
                history_name = history_rec.name if history_rec else ""
                active_sync_queue = env["misa.sync.queue"].sudo().search([
                    ("name", "=", str(so.misa_id or misa_id or "")),
                    ("sync_type", "=", "so"),
                    ("state", "in", ["draft", "processing"]),
                ], limit=1)
                is_sync_request_pending = bool(active_sync_queue)

                status_label = (
                    "Đã gửi yêu cầu thay đổi - đang chờ hệ thống xử lý" if is_sync_request_pending
                    else (f"Chờ phê duyệt phiên bản {history_name}" if (is_pending and history_name)
                    else ("Chờ kho duyệt thay đổi số lượng" if is_pending
                    else ("Sale đang chỉnh sửa - phiếu OUT đang khóa" if is_edit_locked
                    else state_label)))
                )

                lines_data = []
                for line in so.order_line:
                    if line.display_type:
                        continue
                    lines_data.append({
                        "misa_line_id": line.misa_crm_line_id if hasattr(line, 'misa_crm_line_id') and line.misa_crm_line_id else "",
                        "product_code": line.product_id.default_code if line.product_id else "",
                        "name": line.name or "",
                        "qty": line.product_uom_qty,
                        "price": line.price_unit,
                        "discount": line.discount,
                        "tax_percentages": sorted(line.tax_id.mapped('amount')),
                        "uom": line.product_uom.name or "",
                        "qty_delivered": line.qty_delivered if hasattr(line, 'qty_delivered') else 0.0,
                    })

                # Baseline dùng để extension so sánh ngay trong trình duyệt, không fetch CRM.
                # Pending: so với snapshot chờ mới nhất để phát hiện lần sửa tiếp theo.
                # Bình thường: lấy SO hiện tại; snapshot applied chỉ hỗ trợ quy ngược UoM CRM
                # nếu dòng Odoo vẫn khớp nguyên trạng với lần sync gần nhất.
                applied_snapshot = env[
                    "misa.sale.sync.snapshot"
                ].sudo().search([
                    ("sale_order_id", "=", so.id),
                    ("state", "=", "applied"),
                ], order="fetched_at desc, id desc", limit=1)
                pending_payload = (
                    history_rec.snapshot_payload
                    if is_pending and history_rec and isinstance(history_rec.snapshot_payload, list)
                    else None
                )
                applied_payload = (
                    applied_snapshot.snapshot_payload
                    if applied_snapshot and isinstance(applied_snapshot.snapshot_payload, list)
                    else []
                )
                if pending_payload is not None:
                    sync_baseline_lines = [{
                        "misa_line_id": str(item.get("crm_line_id") or ""),
                        "product_code": item.get("code") or "",
                        "name": item.get("name") or "",
                        "qty": float(item.get("crm_qty", item.get("qty")) or 0.0),
                        "price": float(item.get("crm_price", item.get("price")) or 0.0),
                        "discount": float(item.get("crm_discount", item.get("discount")) or 0.0),
                        "tax_percentages": sorted(
                            env['account.tax'].sudo().browse(item.get("tax_ids") or []).exists().mapped('amount')
                        ),
                        "uom": item.get("crm_uom") or "",
                    } for item in pending_payload]
                    sync_baseline_source = "pending_snapshot"
                else:
                    applied_by_line_id = {
                        str(item.get("crm_line_id") or ""): item
                        for item in applied_payload
                        if item.get("crm_line_id")
                    }
                    sync_baseline_lines = []
                    for line in lines_data:
                        if not line.get("misa_line_id") or not line.get("qty"):
                            continue
                        baseline_line = dict(line)
                        applied = applied_by_line_id.get(str(line["misa_line_id"]))
                        if applied:
                            unchanged_since_sync = (
                                abs(float(line.get("qty") or 0.0) - float(applied.get("qty") or 0.0)) < 0.0001
                                and abs(float(line.get("price") or 0.0) - float(applied.get("price") or 0.0)) < 0.01
                                and abs(float(line.get("discount") or 0.0) - float(applied.get("discount") or 0.0)) < 0.0001
                                and (line.get("product_code") or "") == (applied.get("code") or "")
                                and (line.get("name") or "").strip() == (applied.get("name") or "").strip()
                            )
                            if unchanged_since_sync:
                                baseline_line.update({
                                    "qty": float(applied.get("crm_qty", applied.get("qty")) or 0.0),
                                    "price": float(applied.get("crm_price", applied.get("price")) or 0.0),
                                    "discount": float(applied.get("crm_discount", applied.get("discount")) or 0.0),
                                    "uom": applied.get("crm_uom") or "",
                                })
                        sync_baseline_lines.append(baseline_line)
                    sync_baseline_source = "sale_order"

                payload = {
                    "ok": True,
                    "exists": True,
                    "id": so.id,
                    "name": so.name,
                    "status": so.state,
                    "status_label": status_label,
                    "can_revoke": can_revoke,
                    "misa_qty_sync_pending": is_pending,
                    "misa_sync_request_pending": is_sync_request_pending,
                    "misa_qty_sync_pending_history_name": history_name,
                    "misa_sale_edit_locked": is_edit_locked,
                    "misa_sale_edit_locked_at": (
                        fields.Datetime.to_string(edit_locked_at) if edit_locked_at else False
                    ),
                    "sync_baseline_lines": sync_baseline_lines,
                    "sync_baseline_source": sync_baseline_source,
                    "sync_baseline_header": {
                        "shipping_address": so.misa_shipping_address or "",
                        "phone": getattr(so, 'x_studio_sdt_giao_hang', False) or "",
                        "account_name": so.partner_id.name or "",
                        "book_date": fields.Datetime.to_string(so.date_order) if so.date_order else "",
                        "deadline_date": fields.Datetime.to_string(so.commitment_date) if so.commitment_date else "",
                    },
                    "lines": lines_data,
                }

        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )

    # ============================================================
    # POST /api/extension/so/revoke
    # ============================================================
    @http.route(
        "/api/extension/so/revoke",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_so_revoke(self, **payload):
        """
        Thu hồi (hủy) Đơn bán hàng trên Odoo.
        Chỉ hủy, không xóa record để có thể đồng bộ lại từ đầu.
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

        name = (payload.get("name") or "").strip()
        if not name:
            return json_response({"ok": False, "error": "missing_name", "message": "Thiếu tham số name."}, 400)

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return json_response({"ok": False, "error": "admin_not_found"}, 500)
        env_admin = request.env(user=admin_user)

        try:
            SoModel = env_admin["sale.order"].sudo()
            order = SoModel.search([("name", "=", name)], limit=1)
            
            if not order:
                return json_response({"ok": False, "error": "not_found", "message": f"Không tìm thấy đơn {name}"}, 404)

            # Bước 1: Nếu đã cancelled, chỉ cần báo thành công (không xóa)
            if order.state == 'cancel':
                return json_response({"ok": True, "message": f"Đơn {name} đã ở trạng thái hủy, có thể đồng bộ lại."})

            # Bước 2: Kiểm tra phiếu xuất kho
            out_done = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'done'
            )
            if out_done:
                names = ', '.join(out_done.mapped('name'))
                return json_response({
                    "ok": False, "error": "out_picking_done",
                    "message": f"Đơn {name} đã xuất kho hoàn thành (phiếu OUT: {names}). Phải trả hàng về kho trước."
                }, 400)

            # Bước 3: Kiểm tra hoá đơn
            for invoice in order.invoice_ids:
                if invoice.state == 'posted':
                    return json_response({
                        "ok": False, "error": "invoice_posted",
                        "message": f"Đơn {name} đã vào sổ hoá đơn. Cần huỷ hoá đơn/làm Credit Note trước."
                    }, 400)

            # Bước 4: Hủy SO
            if order.state == 'done':
                order.action_unlock()
            order.with_context(disable_cancel_warning=True).action_cancel()

            # Bước 5: Force cancel nếu cần
            if order.state != 'cancel':
                still_open_picks = order.picking_ids.filtered(lambda p: p.state not in ('cancel', 'done'))
                has_posted_inv = order.invoice_ids.filtered(lambda i: i.state == 'posted')
                if not still_open_picks and not has_posted_inv:
                    order.write({'state': 'cancel'})
                else:
                    return json_response({
                        "ok": False, "error": "cancel_failed",
                        "message": f"Không thể huỷ đơn {name}. Còn picking/invoice chưa huỷ hết."
                    }, 400)

            # Bước 6: Trả về thành công (KHÔNG xóa record)
            if order.state == 'cancel':
                return json_response({"ok": True, "message": f"Đã huỷ thành công đơn hàng {name}, có thể đồng bộ lại."})

            return json_response({"ok": False, "error": "cancel_failed", "message": f"Không thể huỷ đơn {name}"}, 400)

        except Exception as e:
            _logger.exception("MISA API /so/revoke exception: %s", e)
            return json_response({"ok": False, "error": "exception", "message": str(e)}, 500)

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
    # GET /api/extension/po/check?po_code=DMH00001
    # ============================================================
    @http.route(
        "/api/extension/po/check",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_extension_po_check(self, **kwargs):
        token = _clean_token(kwargs.get("token")) or _clean_token(
            request.httprequest.headers.get("X-MISA-Token")
        )
        ok, err = self._authenticate(token)
        if not ok:
            return request.make_response(
                json.dumps(err), headers=[("Content-Type", "application/json")]
            )

        po_code = (kwargs.get("po_code") or kwargs.get("name") or "").strip()
        if not po_code:
            return request.make_response(
                json.dumps({"ok": False, "error": "missing_po_code", "message": "Thiếu po_code."}),
                headers=[("Content-Type", "application/json")],
            )

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env
        po = env["purchase.order"].sudo().search([("name", "=", po_code)], limit=1)

        if not po:
            queue = env["misa.sync.queue"].sudo().search([
                ("name", "=", po_code),
                ("sync_type", "=", "po"),
                ("state", "in", ["draft", "processing", "failed"]),
            ], order="id desc", limit=1)
            if queue:
                status_labels = {
                    "draft": "Đang chờ đồng bộ...",
                    "processing": "Đang xử lý đồng bộ...",
                    "failed": "Đồng bộ lỗi",
                }
                payload = {
                    "ok": True,
                    "exists": True,
                    "name": po_code,
                    "status": "queued" if queue.state in ("draft", "processing") else "failed",
                    "status_label": status_labels.get(queue.state, queue.state),
                    "queue_id": queue.id,
                    "error_log": queue.error_log or "",
                    "can_revoke": False,
                }
            else:
                payload = {"ok": True, "exists": False, "name": po_code, "can_revoke": False}
        else:
            state_label = (
                dict(po._fields["state"].selection).get(po.state, po.state)
                if po.state
                else ""
            )
            done_receipts = po.picking_ids.filtered(lambda p: p.state == "done")
            posted_bills = po.invoice_ids.filtered(lambda inv: inv.state == "posted")
            payload = {
                "ok": True,
                "exists": True,
                "id": po.id,
                "name": po.name,
                "status": po.state,
                "status_label": state_label,
                "can_revoke": not bool(done_receipts or posted_bills),
                "done_receipts": done_receipts.mapped("name"),
                "posted_bills": posted_bills.mapped("name"),
            }

        return request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )

    # ============================================================
    # POST /api/extension/po/sync
    # ============================================================
    @http.route(
        "/api/extension/po/sync",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_po_sync(self, **payload):
        def json_response(data, status=200):
            return request.make_response(
                json.dumps(data), headers=[("Content-Type", "application/json")], status=status
            )

        if request.httprequest.method == "OPTIONS":
            return json_response({"ok": True})

        payload = self._parse_json_body(payload)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return json_response(err, 401)

        po_code = (payload.get("po_code") or payload.get("name") or "").strip()
        if not po_code:
            return json_response({"ok": False, "error": "missing_po_code", "message": "Thiếu po_code."}, 400)

        queue_payload = {
            "po_code": po_code,
            "create_when_missing": bool(payload.get("create_when_missing", True)),
            "delete_when_missing": bool(payload.get("delete_when_missing", True)),
            "source_url": payload.get("source_url") or "",
            "source": "misa_purchase_order_extension",
        }

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env_admin = request.env(user=admin_user) if admin_user else request.env
        queue = env_admin["misa.sync.queue"].sudo().create({
            "name": po_code,
            "sync_type": "po",
            "payload": json.dumps(queue_payload, ensure_ascii=False),
        })
        return json_response({
            "ok": True,
            "queued": True,
            "queue_id": queue.id,
            "name": po_code,
            "message": "Đã đưa đơn mua hàng vào hàng đợi đồng bộ Odoo.",
        })

    # ============================================================
    # POST /api/extension/po/revoke
    # ============================================================
    @http.route(
        "/api/extension/po/revoke",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_po_revoke(self, **payload):
        payload = self._parse_json_body(payload)
        payload["create_when_missing"] = False
        payload["delete_when_missing"] = True
        return self.api_extension_po_sync(**payload)

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
        
        # 2. Lấy thông tin tồn kho11
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

        # Đưa request vào queue thay vì xử lý đồng bộ
        try:
            env_admin["misa.sync.queue"].sudo().create({
                "name": pr_name,
                "sync_type": "pr",
                "payload": json.dumps(payload, ensure_ascii=False)
            })
            return json_response({
                "ok": True, 
                "message": "Đã đưa YCMH vào hàng chờ đồng bộ."
            })
        except Exception as e:
            return json_response({
                "ok": False, 
                "error": "queue_failed", 
                "message": f"Lỗi khi đưa vào hàng chờ: {str(e)}"
            }, 500)

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
        odoo_prod_map = {}  # code -> {"qty": float, "price_unit": float, "price_tax": float, "vat_rate": float, "display": str, "name": str}
        for oline in odoo_lines_detail:
            code = oline["code"]
            if code not in odoo_prod_map:
                odoo_prod_map[code] = {
                    "qty": 0.0,
                    "price_unit": oline.get("price_unit", 0.0),
                    "price_tax": 0.0,
                    "vat_rate": oline.get("vat_rate", 0.0),
                    "display": oline["display"],
                    "name": oline["name"],
                }
            odoo_prod_map[code]["qty"] += oline.get("qty_received", oline.get("qty", 0.0))
            odoo_prod_map[code]["price_tax"] += oline.get("price_tax", 0.0)

        # AMIS: aggregate quantity_receipt
        amis_prod_map = {}  # code -> {"qty": float, "price_unit": float, "price_tax": float, "vat_rate": float, "name": str}
        for aline in amis_lines:
            orig_code = aline.get("inventory_item_code", "unknown_code").strip()
            code = orig_code.lower()
            a_qty = float(aline.get("quantity_receipt", 0))
            a_price = float(aline.get("unit_price", 0) or 0)
            a_tax = float(aline.get("vat_amount", aline.get("tax_amount", 0)) or 0)
            a_vat_rate = float(aline.get("vat_rate", 0) or 0)
            a_name = aline.get("inventory_item_name", "")
            if code not in amis_prod_map:
                amis_prod_map[code] = {"qty": 0.0, "price_unit": a_price, "price_tax": 0.0, "vat_rate": a_vat_rate, "name": a_name, "orig_code": orig_code}
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
                # Thử fallback match theo tên sản phẩm cho trường hợp Odoo code = unknown_code (sản phẩm đã archive)
                fallback_matched = False
                if code == "unknown_code" and o_item.get("name"):
                    o_name_lower = o_item["name"].lower().strip()
                    for alt_code, alt_item in amis_prod_map.items():
                        alt_name = (alt_item.get("name") or "").lower().strip()
                        if alt_name and (alt_name == o_name_lower or o_name_lower in alt_name or alt_name in o_name_lower):
                            # Match found: merge odoo data into amis item
                            a_item = alt_item
                            fallback_matched = True
                            _logger.info("✅ Fallback match by name: Odoo '%s' (name='%s') -> AMIS code='%s'", code, o_item["name"], alt_code)
                            break
                if not fallback_matched:
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
                    
                # So sánh Thuế % (vat_rate)
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

                # So sánh Tiền thuế từng dòng (price_tax)
                o_tax_amt = float(o_item.get("price_tax", 0.0))
                a_tax_amt = float(a_item.get("price_tax", 0.0))
                if abs(o_tax_amt - a_tax_amt) > 100.0:
                    has_tax_diff = True
                    differences.append({
                        "type": "tax_diff",
                        "product_code": code,
                        "product_name": prod_name,
                        "field": "price_tax",
                        "odoo_value": o_tax_amt,
                        "misa_value": a_tax_amt,
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
        elif has_vat_diff or has_total_diff or has_tax_diff:
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
                # Sản phẩm đã bị archive và mất default_code (do tạo lại sản phẩm mới cùng mã)
                # Fallback: tìm sản phẩm active có cùng tên để lấy default_code
                try:
                    active_prod = self.env['product.product'].sudo().search([
                        ('name', '=', oline.product_id.name),
                        ('default_code', '!=', False),
                        ('active', '=', True)
                    ], limit=1)
                    if active_prod and active_prod.default_code:
                        orig_code = active_prod.default_code.strip()
                        code = orig_code.lower()
                except Exception:
                    pass
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
                "uom_name": oline.product_uom.name if oline.product_uom else "",
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
                    
                    amis_lines_detail = []
                    for aline in amis_lines:
                        if not isinstance(aline, dict): continue
                        
                        orig_code = (aline.get("inventory_item_code") or "").strip()
                        prod_name = (aline.get("description") or aline.get("inventory_item_name") or "").strip()
                        code = orig_code.lower()
                        # Lấy thông tin ĐVT để đối chiếu đúng (có thể MISA dùng unit_name còn Odoo dùng main_unit_name)
                        misa_main_qty = float(aline.get("main_quantity") or 0)
                        misa_main_convert = float(aline.get("main_convert_rate") or 1)
                        # Nếu main_convert_rate > 0 và main_quantity > 0, tính lại qty từ main để so sánh
                        misa_qty = float(aline.get("quantity") or 0)
                        misa_qty_receipt = float(aline.get("quantity_receipt") or 0)
                        amis_lines_detail.append({
                            "code": code,
                            "orig_code": orig_code,
                            "name": prod_name,
                            "display": f"[{orig_code}] {prod_name}" if orig_code else "Unknown Code",
                            "qty": misa_qty,
                            "qty_receipt": misa_qty_receipt,
                            "main_quantity": misa_main_qty,
                            "main_quantity_receipt": float(aline.get("main_quantity_receipt") or 0),
                            "main_convert_rate": misa_main_convert,
                            "unit_name": aline.get("unit_name") or "",
                            "main_unit_name": aline.get("main_unit_name") or "",
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

    # ============================================================
    # POST /api/extension/pr/batch_check
    # ============================================================
    @http.route(
        "/api/extension/pr/batch_check",
        type="http",
        auth="none",
        methods=["POST", "OPTIONS"],
        csrf=False,
        cors="*",
    )
    def api_extension_pr_batch_check(self, **payload):
        """
        Kiểm tra trạng thái Odoo của nhiều YCMH cùng lúc (dùng cho list page).

        Body JSON:
        {
            "token": "...",
            "names": ["YCMH2441...", "YCMH2442...", ...]
        }

        Response 200 JSON:
        {
            "ok": true,
            "results": {
                "YCMH2441...": {
                    "exists": true,
                    "state": "draft",
                    "state_label": "Bản nháp"
                },
                "YCMH2442...": {
                    "exists": false
                }
            }
        }
        """
        def json_response(data, status=200):
            return request.make_response(
                json.dumps(data), headers=[("Content-Type", "application/json")]
            )

        if request.httprequest.method == "OPTIONS":
            return json_response({"ok": True})

        payload = self._parse_json_body(payload)
        token = self._extract_token(payload)
        ok, err = self._authenticate(token)
        if not ok:
            return json_response(err, 401)

        names = payload.get("names") or []
        if not names or not isinstance(names, list):
            return json_response({"ok": False, "error": "missing_names", "message": "Thiếu danh sách 'names'."}, 400)

        # Lọc names rỗng
        names = [n.strip() for n in names if n and n.strip()]
        if not names:
            return json_response({"ok": False, "error": "empty_names", "message": "Danh sách 'names' rỗng."}, 400)

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        env = request.env(user=admin_user) if admin_user else request.env

        # Batch search tất cả PRs có name trong danh sách
        prs = env["purchase.request"].sudo().search([("name", "in", names)])
        pr_map = {pr.name: pr for pr in prs}

        # Kiểm tra queue cho các name không có PR
        queue_names = [n for n in names if n not in pr_map]
        queues = env["misa.sync.queue"].sudo().search([
            ('name', 'in', queue_names),
            ('sync_type', '=', 'pr'),
            ('state', 'in', ['draft', 'processing'])
        ])
        queue_name_set = set(q.name for q in queues)

        results = {}
        for name in names:
            if name in pr_map:
                pr = pr_map[name]
                state_label = dict(pr._fields["state"].selection).get(pr.state, pr.state)
                results[name] = {
                    "exists": True,
                    "state": pr.state,
                    "state_label": state_label,
                    "po_progress": pr.progress_purchased_badge or "0/0",
                    "po_progress_status": pr.progress_purchased_status or "not_started",
                    "stock_progress": pr.progress_received_badge or "0/0",
                    "stock_progress_status": pr.progress_received_status or "not_started",
                }
            elif name in queue_name_set:
                results[name] = {
                    "exists": True,
                    "state": "queued",
                    "state_label": "Đang đồng bộ",
                    "po_progress": "-",
                    "po_progress_status": "not_started",
                    "stock_progress": "-",
                    "stock_progress_status": "not_started",
                }
            else:
                results[name] = {
                    "exists": False,
                    "po_progress": "-",
                    "po_progress_status": "not_started",
                    "stock_progress": "-",
                    "stock_progress_status": "not_started",
                }

        return json_response({"ok": True, "results": results})

