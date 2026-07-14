# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Mở rộng `purchase.request` để:
1. Cung cấp nút "Đẩy sang MISA CRM" trên form (stub TODO).
2. Cung cấp helper `_prepare_misa_user(owner_text)` được controller dùng
   khi tạo PR từ Browser Extension.
3. Cung cấp computed fields tiến độ mua hàng cho list view badge.
"""

import json
import logging
import re

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    # ------------------------------------------------------------
    # THÊM CÁC TRƯỜNG TÙY CHỈNH
    # ------------------------------------------------------------
    sale_order_id = fields.Many2one('sale.order', string="Đơn bán hàng liên quan")
    delivery_address = fields.Char(string="Địa điểm giao")
    picking_type_id = fields.Many2one(
        default=lambda self: self._default_picking_type(),
    )
    misa_new_supplier_json = fields.Text(string="Dữ liệu NCC mới (JSON)")
    misa_has_new_supplier = fields.Boolean(
        string="Có NCC mới", 
        compute="_compute_misa_has_new_supplier"
    )

    def _compute_misa_has_new_supplier(self):
        for rec in self:
            if rec.misa_new_supplier_json:
                rec.misa_has_new_supplier = True
            else:
                # Fallback check qua chatter messages
                has_msg = self.env['mail.message'].search_count([
                    ('res_id', '=', rec.id),
                    ('model', '=', 'purchase.request'),
                    ('body', 'ilike', 'NCC mới từ MISA cần kiểm tra:')
                ]) > 0
                rec.misa_has_new_supplier = has_msg

    # ------------------------------------------------------------
    # COMPUTED FIELDS: TIẾN ĐỘ MUA HÀNG (cho list view badge)
    # ------------------------------------------------------------
    progress_total = fields.Integer(
        string="Tổng SL món",
        compute="_compute_purchase_progress",
        store=True,
        help="Tổng số dòng yêu cầu (không tính dòng đã hủy).",
    )
    progress_purchased = fields.Integer(
        string="SL đã tạo ĐH",
        compute="_compute_purchase_progress",
        store=True,
        help="Số dòng đã có Đơn mua hàng (PO/RFQ).",
    )
    progress_received = fields.Integer(
        string="SL đã nhận",
        compute="_compute_purchase_progress",
        store=True,
        help="Số dòng đã nhận đủ hàng.",
    )
    progress_badge = fields.Char(
        string="Tiến độ mua hàng",
        compute="_compute_purchase_progress",
        store=True,
        help="Hiển thị: 'ĐH 4/5 • NK 3/5' = đã tạo ĐH 4/5, đã nhập kho 3/5.",
    )
    progress_status = fields.Selection(
        selection=[
            ("not_started", "Chưa mua"),
            ("in_progress", "Đang mua"),
            ("partial", "Nhận một phần"),
            ("done", "Hoàn thành"),
        ],
        string="Trạng thái tiến độ",
        compute="_compute_purchase_progress",
        store=True,
        help="Dùng cho decoration-* trong list view.",
    )

    @api.depends(
        "line_ids",
        "line_ids.cancelled",
        "line_ids.purchase_lines",
        "line_ids.purchase_lines.state",
        "line_ids.qty_done",
        "line_ids.product_qty",
        "line_ids.purchase_state",
    )
    def _compute_purchase_progress(self):
        for rec in self:
            active_lines = rec.line_ids.filtered(lambda l: not l.cancelled)
            total = len(active_lines)
            if total == 0:
                rec.progress_total = 0
                rec.progress_purchased = 0
                rec.progress_received = 0
                rec.progress_badge = ""
                rec.progress_status = "not_started"
                continue

            purchased = 0
            received = 0
            for line in active_lines:
                # Đã tạo ĐH: có ít nhất 1 purchase_line không bị hủy
                has_po = any(
                    pl.state != "cancel" for pl in line.purchase_lines
                )
                if has_po:
                    purchased += 1

                # Đã nhận đủ: qty_done >= product_qty (và có qty_done > 0)
                if line.product_qty > 0 and line.qty_done >= line.product_qty:
                    received += 1
                elif line.purchase_state == "done" and line.qty_done > 0:
                    received += 1

            rec.progress_total = total
            rec.progress_purchased = purchased
            rec.progress_received = received
            rec.progress_badge = f"ĐH {purchased}/{total} • NK {received}/{total}"

            if received >= total and total > 0:
                rec.progress_status = "done"
            elif received > 0:
                rec.progress_status = "partial"
            elif purchased > 0:
                rec.progress_status = "in_progress"
            else:
                rec.progress_status = "not_started"

    @api.model
    def _default_picking_type(self):
        type_obj = self.env["stock.picking.type"]
        company_id = self.env.context.get("company_id") or self.env.company.id

        # Cố gắng tìm Kho Bến Cam trước
        ben_cam = type_obj.search([
            ("code", "=", "incoming"),
            ("warehouse_id.company_id", "=", company_id),
            ("warehouse_id.name", "ilike", "Bến Cam")
        ], limit=1)

        if ben_cam:
            return ben_cam

        return super(PurchaseRequest, self)._default_picking_type()

    # ------------------------------------------------------------
    # NÚT BẤM TRÊN FORM (STUB - TODO)
    # ------------------------------------------------------------
    def action_send_to_misa_crm(self):
        """
        Nút 'Đẩy sang MISA CRM' trên form Purchase Request.

        TODO: Xây dựng luồng đẩy về MISA sau.
        Hiện tại chỉ là stub - raise UserError để UX rõ ràng rằng
        tính năng chưa hoàn thiện (KHÔNG im lặng).
        """
        self.ensure_one()
        # TODO: Xây dựng luồng đẩy về MISA sau
        raise UserError(
            _("Tính năng đẩy sang MISA CRM đang được phát triển.")
        )

    # ------------------------------------------------------------
    # HELPER DÙNG BỞI CONTROLLER
    # ------------------------------------------------------------
    @api.model
    def _prepare_misa_user(self, owner_text):
        """
        Tìm res.users dựa trên chuỗi `OwnerIDText` của MISA CRM.

        Input ví dụ: "MAI VĂN NAM (MAIVANNAM1)"

        Logic:
        1. Bóc tách phần trong ngoặc (nếu có) - đó là login.
           Fallback nếu không có ngoặc: dùng nguyên chuỗi.
        2. Tìm res.users theo login (case-insensitive exact) HOẶC
           name (case-insensitive contains).
        3. Nếu không thấy, return (admin_user_id, message) - message
           sẽ được log vào Chatter để truy vết.

        :return: tuple(user_id: int, message: str | False)
        """
        message = False
        if not owner_text:
            user = self.env.ref("base.user_root", raise_if_not_found=False)
            return (user.id if user else 2, "OwnerIDText rỗng → dùng Admin.")

        owner_text = (owner_text or "").strip()

        # Bóc tách "MAI VĂN NAM (MAIVANNAM1)" -> "MAIVANNAM1"
        match = re.search(r"\(([^)]+)\)\s*$", owner_text)
        if match:
            login_candidate = match.group(1).strip()
        else:
            login_candidate = owner_text

        user = self.env["res.users"].search(
            ["|", ("login", "=ilike", login_candidate),
             ("name", "=ilike", owner_text)],
            limit=1,
        )

        if user:
            return (user.id, False)

        admin = self.env.ref("base.user_root", raise_if_not_found=False) \
            or self.env.ref("base.user_admin", raise_if_not_found=False)
        message = _("Người thực hiện: %s") % owner_text
        _logger.info("MISA Sync PR: Khong thay user, fallback to admin. %s", message)
        return (admin.id if admin else 2, message)

    @api.depends('line_ids', 'line_ids.estimated_cost', 'line_ids.misa_amount')
    def _compute_estimated_cost(self):
        for rec in self:
            total = 0.0
            for line in rec.line_ids:
                total += line.misa_amount if line.misa_amount else line.estimated_cost
            rec.estimated_cost = total


    @api.model
    def api_create_from_misa_payload(self, payload):
        """
        Tạo PR từ JSON payload của MISA (đã trích xuất từ controller extension_api)
        """
        pr_name = (payload.get("PurchaseRequestName") or "").strip()
        if not pr_name:
            raise UserError(_("Thiếu trường 'PurchaseRequestName'."))
            
        lines_in = payload.get("lines") or []
        if not lines_in:
            raise UserError(_("Thiếu danh sách 'lines'."))

        user_id, owner_message = self._prepare_misa_user(payload.get("OwnerIDText"))
        
        # Tìm Đơn bán hàng liên quan
        so_name = (payload.get("SaleOrderIDText") or "").strip()
        sale_order_id = False
        if so_name:
            so = self.env["sale.order"].search([("name", "=", so_name)], limit=1)
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

        pr = self.search([("name", "=", pr_name)], limit=1)
        existing_lines_by_misa_id = {}
        
        if pr:
            if pr.state not in ['draft', 'to_approve']:
                raise UserError(_("YCMH %s đã tồn tại và ở trạng thái %s, không thể cập nhật.") % (pr_name, pr.state))
            
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
            
            if create_date:
                self.env.cr.execute("UPDATE purchase_request SET create_date=%s WHERE id=%s", (create_date, pr.id))
        else:
            pr_vals = {
                "name": pr_name,
                "requested_by": user_id,
                "assigned_to": self.env.ref("base.user_admin", raise_if_not_found=False).id if self.env.ref("base.user_admin", raise_if_not_found=False) else False,
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
            pr = self.create(pr_vals)

        # Xử lý lines
        product_model = self.env["product.product"]
        uom_model = self.env["uom.uom"]
        line_model = self.env["purchase.request.line"]

        def _resolve_product_and_uom(line_data):
            pcode = (line_data.get("product_code") or "").strip()
            product = False
            if pcode:
                product = product_model.search([("default_code", "=", pcode)], limit=1)
            uom = False
            if product:
                uom = product.uom_id
            uom_name = (line_data.get("uom") or "").strip()
            if uom_name:
                uom_match = uom_model.search([("name", "=ilike", uom_name)], limit=1)
                if uom_match:
                    uom = uom_match
            return product, uom

        for idx, line in enumerate(lines_in):
            misa_line_id = (line.get("misa_line_id") or "").strip()
            
            product, uom = _resolve_product_and_uom(line)
            product_id = product.id if product else False
            uom_id = uom.id if uom else False

            line_name = (line.get("name") or "Sản phẩm không tên").strip()
            try:
                qty = float(line.get("qty", 1.0))
            except ValueError:
                qty = 1.0

            misa_supplier_id = None
            # Extension gửi key "misa_supplier_id", nhưng cũng hỗ trợ "sale_proposed_supplier_id"
            # CHỈ gán nếu partner ID tồn tại trong Odoo, tránh lỗi FK violation
            supplier_key = line.get("misa_supplier_id") or line.get("sale_proposed_supplier_id")
            if supplier_key:
                try:
                    partner_id = int(supplier_key)
                    if self.env['res.partner'].sudo().browse(partner_id).exists():
                        misa_supplier_id = partner_id
                except (ValueError, TypeError):
                    misa_supplier_id = None
            
            raw = line.get("rawData", {})

            def _float_val(key, default=0.0):
                """Helper lấy float từ line hoặc raw, ưu tiên line."""
                val = line.get(key)
                if val is None:
                    val = raw.get(key)
                if val is None:
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            line_vals = {
                "request_id": pr.id,
                "name": line_name,
                "product_id": product_id,
                "product_uom_id": uom_id,
                "product_qty": qty,
                "misa_line_id": misa_line_id,
                "sale_proposed_supplier_id": misa_supplier_id,
                "misa_supplier_id": misa_supplier_id,
                # Các trường giá trị từ MISA
                "misa_amount": _float_val("misa_amount"),
                "misa_price_before_tax": _float_val("misa_price_before_tax"),
                "misa_price_after_tax": _float_val("misa_price_after_tax"),
                "misa_tax_rate": _float_val("misa_tax_rate"),
                "misa_tax_amount": _float_val("misa_tax_amount"),
                "misa_discount_rate": _float_val("misa_discount_rate"),
                "misa_discount_amount": _float_val("misa_discount_amount"),
                "misa_stock_total": _float_val("misa_stock_total"),
                "misa_stock_selected": _float_val("misa_stock_selected"),
                "misa_stock_undelivered": _float_val("misa_stock_undelivered"),
            }

            # Lưu dữ liệu NCC mới per-line (nếu có)
            nsd = line.get("new_supplier_data")
            if nsd and nsd.get("name"):
                line_vals["misa_new_supplier_json"] = json.dumps(nsd)
            else:
                line_vals["misa_new_supplier_json"] = False
            
            if date_required:
                line_vals["date_required"] = date_required
                
            if misa_line_id and misa_line_id in existing_lines_by_misa_id:
                existing_line = existing_lines_by_misa_id[misa_line_id]
                existing_line.write(line_vals)
                del existing_lines_by_misa_id[misa_line_id]
            else:
                line_model.create(line_vals)

        # Xóa các dòng cũ trên Odoo nhưng không có trên MISA (chỉ xoá những dòng có misa_line_id)
        for old_line in existing_lines_by_misa_id.values():
            old_line.unlink()

        # ============================================================
        # POST CHATTER MESSAGES
        # ============================================================

        # 1. Post message "Người thực hiện" nếu không tìm thấy user
        if owner_message:
            pr.message_post(body=Markup("<b>%s</b>") % owner_message)

        # 2. Xử lý new_supplier_data - chỉ hiển thị thông tin, không tự động tạo
        new_supplier_msgs = []
        new_supplier_list = []
        for line_data in lines_in:
            nsd = line_data.get("new_supplier_data")
            if nsd and nsd.get("name"):
                new_supplier_list.append(nsd)
                pcode = (line_data.get("product_code") or "").strip()
                line_ref = "SP [%s]" % pcode if pcode else "Dòng %s" % (lines_in.index(line_data) + 1)
                items = []
                items.append(Markup("<b>Tên NCC:</b> %s") % nsd['name'])
                if nsd.get('address'): items.append(Markup("<b>Địa chỉ:</b> %s") % nsd['address'])
                if nsd.get('phone'): items.append(Markup("<b>Điện thoại:</b> %s") % nsd['phone'])
                if nsd.get('vat'): items.append(Markup("<b>Mã số thuế:</b> %s") % nsd['vat'])
                if nsd.get('note'): items.append(Markup("<b>Ghi chú:</b> %s") % nsd['note'])
                html = Markup('<div style="margin: 4px 0; padding: 6px 10px; border-left: 3px solid #ffc107; background: #fffdf0;">')
                html += Markup('<div style="font-weight: 600; color: #856404; margin-bottom: 4px;">%s</div>') % line_ref
                html += Markup('<div style="padding-left: 8px;">%s</div>') % Markup("<br/>").join(items)
                html += Markup('</div>')
                new_supplier_msgs.append(html)

        if new_supplier_msgs:
            msg = Markup("<b>NCC mới từ MISA cần kiểm tra:</b><br/>%s") % Markup("<br/>").join(new_supplier_msgs)
            pr.message_post(body=msg)
            
        if new_supplier_list:
            pr.write({
                'misa_new_supplier_json': json.dumps(new_supplier_list)
            })

        # 3. Post message tổng kết đồng bộ
        summary_parts = []
        if pr.create_date:
            create_dt = fields.Datetime.to_string(pr.create_date)[:16]
            summary_parts.append(_("Ngày tạo: %s") % create_dt)
        summary_parts.append(_("Số dòng: %s") % len(lines_in))
        if new_supplier_msgs:
            summary_parts.append(_("NCC mới cần kiểm tra: %s") % len(new_supplier_msgs))
        summary_msg = _("Đồng bộ YCMH từ MISA CRM thành công. %s") % " | ".join(summary_parts)
        pr.message_post(body=Markup("<i>%s</i>") % summary_msg)

        return pr
