# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Mở rộng `purchase.request` để:
1. Cung cấp nút "Đẩy sang MISA CRM" trên form (stub TODO).
2. Cung cấp helper `_prepare_misa_user(owner_text)` được controller dùng
   khi tạo PR từ Browser Extension.
3. Cung cấp computed fields tiến độ mua hàng cho list view badge.
4. Hỗ trợ lưu trữ (archive) cho YCMH.
"""

import json
import logging
import re

import requests
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
    x_misa_requested_by = fields.Char(string="Người yêu cầu (MISA)")

    # === Hỗ trợ lưu trữ (YC4) ===
    active = fields.Boolean(string="Hoạt động", default=True)

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
        help="Tổng số dòng yêu cầu (không tính dòng đã hủy hoặc bỏ qua).",
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
    # === YC1: Tách riêng 2 cột ĐH và NK ===
    progress_purchased_badge = fields.Char(
        string="ĐH",
        compute="_compute_purchase_progress",
        store=True,
        help="Số dòng đã tạo ĐH / Tổng số dòng.",
    )
    progress_received_badge = fields.Char(
        string="NK",
        compute="_compute_purchase_progress",
        store=True,
        help="Số dòng đã nhập kho / Tổng số dòng.",
    )
    progress_purchased_status = fields.Selection(
        selection=[
            ("not_started", "Chưa có ĐH"),
            ("partial", "Đã có ĐH một phần"),
            ("done", "Đã có ĐH đầy đủ"),
        ],
        string="Trạng thái ĐH",
        compute="_compute_purchase_progress",
        store=True,
    )
    progress_received_status = fields.Selection(
        selection=[
            ("not_started", "Chưa nhập kho"),
            ("partial", "Nhập một phần"),
            ("done", "Nhập đủ"),
        ],
        string="Trạng thái NK",
        compute="_compute_purchase_progress",
        store=True,
    )

    @api.depends(
        "line_ids",
        "line_ids.cancelled",
        "line_ids.skip_processing",
        "line_ids.purchase_lines",
        "line_ids.purchase_lines.state",
        "line_ids.qty_done",
        "line_ids.product_qty",
        "line_ids.purchase_state",
    )
    def _compute_purchase_progress(self):
        for rec in self:
            # YC3: Bỏ qua các dòng có skip_processing = True hoặc cancelled
            active_lines = rec.line_ids.filtered(
                lambda l: not l.cancelled and not l.skip_processing
            )
            total = len(active_lines)
            if total == 0:
                rec.progress_total = 0
                rec.progress_purchased = 0
                rec.progress_received = 0
                rec.progress_badge = ""
                rec.progress_status = "not_started"
                rec.progress_purchased_badge = ""
                rec.progress_received_badge = ""
                rec.progress_purchased_status = "not_started"
                rec.progress_received_status = "not_started"
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
            rec.progress_purchased_badge = f"{purchased}/{total}"
            rec.progress_received_badge = f"{received}/{total}"

            # Trạng thái tổng thể
            if received >= total and total > 0:
                rec.progress_status = "done"
            elif received > 0:
                rec.progress_status = "partial"
            elif purchased > 0:
                rec.progress_status = "in_progress"
            else:
                rec.progress_status = "not_started"

            # Trạng thái ĐH
            if purchased >= total and total > 0:
                rec.progress_purchased_status = "done"
            elif purchased > 0:
                rec.progress_purchased_status = "partial"
            else:
                rec.progress_purchased_status = "not_started"

            # Trạng thái NK
            if received >= total and total > 0:
                rec.progress_received_status = "done"
            elif received > 0:
                rec.progress_received_status = "partial"
            else:
                rec.progress_received_status = "not_started"

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
    # YC4: Lưu trữ - Cho phép archive khi không phải draft
    # ------------------------------------------------------------
    def _can_be_deleted(self):
        """Cho phép xóa ở draft, hướng dẫn archive ở các state khác."""
        self.ensure_one()
        if self.state == "draft":
            return True
        # Nếu không phải draft → không cho xóa, hướng dẫn archive
        raise UserError(
            _("Bạn không thể xóa YCMH ở trạng thái '%s'. "
              "Hãy sử dụng chức năng Lưu trữ (Archive) để ẩn YCMH này.") % self.state
        )

    def toggle_active(self):
        """Override toggle_active để thêm ghi chú khi archive/unarchive."""
        for rec in self:
            if not rec.active and rec.state == "draft":
                # Khi unarchive từ draft thì OK
                pass
        return super(PurchaseRequest, self).toggle_active()

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
    def _resolve_misa_picking_type(self, raw_data, company_id=False):
        """
        Xác định Kho nhận (stock.picking.type incoming) dựa vào CustomField13/CustomField13Text của MISA payload:
        1: Bến Cam
        2: Hiền Đức
        3: Tân Sơn Nhì
        4: TSN Showroom
        """
        if not raw_data or not isinstance(raw_data, dict):
            raw_data = {}

        type_obj = self.env["stock.picking.type"].sudo()
        wh_obj = self.env["stock.warehouse"].sudo()

        cf13_id = raw_data.get("CustomField13")
        cf13_text = (raw_data.get("CustomField13Text") or "").strip()

        # Map ID -> Warehouse Name search pattern
        id_map = {
            1: "Bến Cam",
            2: "Hiền Đức",
            3: "Tân Sơn Nhì",
            4: "TSN Showroom",
        }

        search_text = False
        if cf13_id in id_map:
            search_text = id_map[cf13_id]
        elif isinstance(cf13_id, str) and cf13_id.isdigit() and int(cf13_id) in id_map:
            search_text = id_map[int(cf13_id)]
        elif cf13_text:
            search_text = cf13_text

        if search_text:
            domain = [
                ("code", "=", "incoming"),
                "|",
                ("warehouse_id.name", "ilike", search_text),
                ("warehouse_id.code", "ilike", search_text),
            ]
            if company_id:
                domain.append(("warehouse_id.company_id", "=", company_id))

            pt = type_obj.search(domain, limit=1)
            if pt:
                return pt.id

            # Fallback search warehouse directly
            wh_domain = [
                "|",
                ("name", "ilike", search_text),
                ("code", "ilike", search_text),
            ]
            if company_id:
                wh_domain.append(("company_id", "=", company_id))
            wh = wh_obj.search(wh_domain, limit=1)
            if wh and wh.in_type_id:
                return wh.in_type_id.id

        # Fallback về mặc định nếu không khớp
        default_pt = self._default_picking_type()
        return default_pt.id if default_pt else False

    @api.model
    def _misa_fetch_conversion_units(self, product_id, headers, cache=None):
        """Fetch the MISA conversion UoMs configured for one product."""
        if not product_id:
            _logger.warning(
                "MISA PR UoM conversions: missing product_id, skip DataSubPaging"
            )
            return []

        cache_key = str(product_id)
        if cache is not None and cache_key in cache:
            return cache[cache_key]

        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/DataSubPaging"
        payload = {
            "Columns": "SUQsQ29udmVyc2lvblVuaXRJRCxDb252ZXJzaW9uVW5pdElEVGV4dCxDb252ZXJzaW9uUmF0ZSxEZXNjcmlwdGlvbixDb252ZXJzaW9uT3BlcmF0b3JJRCxDb252ZXJzaW9uT3BlcmF0b3JJRFRleHQsQ29udmVyc2lvblVuaXRQcmljZTIsQ29udmVyc2lvblVuaXRQcmljZSxDb252ZXJzaW9uVW5pdFByaWNlMSxDb252ZXJzaW9uVW5pdFByaWNlRml4ZWQ=",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 20,
            "Filters": [],
            "DefaultTotal": False,
            "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": str(product_id),
                "TableName": "product_conversion_unit",
                "MasterKey": "ProductID",
                "SumColumn": "",
            },
            "IsApproved": False,
            "CustomPagingData": {
                "SubFormConfig": {
                    "ColumnFieldSubForm": "",
                    "ColumnAggregateSubForm": "",
                    "TableName": "product_conversion_unit",
                    "ParentIDKey": "ProductID",
                    "IsBringSerialType": False,
                    "AggregateField": [],
                }
            },
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": "864e2811-5edd-5ccc-6b85-178b59007e93",
            "AISearchKeyword": "",
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json().get("Data", []) or []
            if cache is not None:
                cache[cache_key] = result
            _logger.info(
                "MISA PR UoM conversions fetched: product_id=%r count=%s",
                product_id,
                len(result),
            )
            return result
        except Exception as exc:
            _logger.exception(
                "MISA PR: loi goi Product/DataSubPaging cho product_id=%r: %s",
                product_id,
                exc,
            )
            return []

    @api.model
    def _convert_qty_price_to_default_uom(
        self,
        product,
        misa_uom_text,
        qty,
        price,
        misa_product_id,
        headers,
        conversion_cache=None,
    ):
        """Convert MISA quantity/unit price to ``product.uom_id``."""
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        requested_uom_key = (misa_uom_text or "").strip().lower()
        default_uom_key = default_uom_name.strip().lower()

        if not requested_uom_key or requested_uom_key == default_uom_key:
            return qty, price, True

        if not misa_product_id:
            _logger.warning(
                "MISA PR: san pham %r khong co MISA ProductID, "
                "khong the lay bang quy doi UoM",
                product.default_code,
            )
        conversions = self._misa_fetch_conversion_units(
            misa_product_id,
            headers,
            cache=conversion_cache,
        ) if misa_product_id else []

        # Normal: MISA line uses a conversion UoM, Odoo uses the base UoM.
        conversion = next((
            item for item in conversions
            if (item.get("ConversionUnitIDText") or "").strip().lower()
            == requested_uom_key
        ), None)
        reverse_conversion = False

        # Reverse: MISA line uses the base UoM, Odoo's default is a conversion UoM.
        if not conversion:
            conversion = next((
                item for item in conversions
                if (item.get("ConversionUnitIDText") or "").strip().lower()
                == default_uom_key
            ), None)
            reverse_conversion = bool(conversion)

        if not conversion:
            _logger.warning(
                "MISA PR: khong tim thay quy doi UoM %r -> %r cho san pham %r; "
                "giu nguyen so lieu",
                misa_uom_text,
                default_uom_name,
                product.default_code,
            )
            return qty, price, False

        try:
            rate = float(conversion.get("ConversionRate") or 0.0)
        except (TypeError, ValueError):
            rate = 0.0
        try:
            operator_id = int(conversion.get("ConversionOperatorID") or 1)
        except (TypeError, ValueError):
            operator_id = 1

        if rate <= 0:
            _logger.warning(
                "MISA PR: ConversionRate khong hop le cho san pham %r, UoM %r",
                product.default_code,
                misa_uom_text,
            )
            return qty, price, False

        if reverse_conversion:
            if operator_id == 1:
                qty_base = qty / rate
                price_base = price * rate
            else:
                qty_base = qty * rate
                price_base = price / rate
        elif operator_id == 1:
            qty_base = qty * rate
            price_base = price / rate
        else:
            qty_base = qty / rate
            price_base = price * rate

        _logger.info(
            "MISA PR UoM converted: product=%r %s %s @ %s -> %s %s @ %s "
            "(rate=%s operator=%s)",
            product.default_code,
            qty,
            misa_uom_text,
            price,
            qty_base,
            default_uom_name,
            price_base,
            rate,
            operator_id,
        )
        return qty_base, price_base, False

    @api.model
    def _misa_fetch_latest_purchase_request(self, raw_data):
        """Return the latest MISA PR header by ID, or an empty dict on failure.

        The browser extension can hold a stale ``FormDataNew`` response while
        users edit header fields inline. Fetching the entity again in the queue
        worker makes MISA the source of truth for those fields.
        """
        raw_data = raw_data if isinstance(raw_data, dict) else {}
        purchase_request_id = (
            raw_data.get("PurchaseRequestID")
            or raw_data.get("PurchaseRequestId")
            or raw_data.get("ID")
            or raw_data.get("id")
        )
        if not purchase_request_id:
            _logger.warning(
                "MISA PR: payload khong co PurchaseRequestID/ID; "
                "khong the tai lai header moi nhat"
            )
            return {}

        try:
            headers = (
                self.env["misa.api.utils"]
                .sudo()
                ._get_cached_crm_headers()
            )
        except Exception as exc:
            _logger.exception(
                "MISA PR: khong lay duoc CRM headers de tai lai PR %r: %s",
                purchase_request_id,
                exc,
            )
            return {}

        def _unwrap_response(response_data):
            if not isinstance(response_data, dict):
                return {}
            if response_data.get("Success") is False:
                return {}
            data = response_data.get("Data", response_data)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (TypeError, ValueError):
                    return {}
            if isinstance(data, dict):
                data = (
                    data.get("CurrentData")
                    or data.get("FormData")
                    or data.get("Data")
                    or data
                )
            return data if isinstance(data, dict) else {}

        def _contains_description(data):
            return any(
                key in data
                for key in ("Description", "description", "Note", "note", "Reason")
            )

        entity_url = (
            "https://amisapp.misa.vn/crm/g2/api/business/"
            "PurchaseRequest/%s/" % purchase_request_id
        )
        columns = ";".join([
            "ID",
            "PurchaseRequestID",
            "PurchaseRequestName",
            "Description",
            "Note",
            "Reason",
            "FormLayoutID",
        ])
        try:
            response = requests.get(
                entity_url,
                headers=headers,
                params={"columns": columns},
                timeout=30,
            )
            response.raise_for_status()
            latest_data = _unwrap_response(response.json())
            if _contains_description(latest_data):
                _logger.info(
                    "MISA PR: da tai header moi nhat bang entity API, ID=%r",
                    purchase_request_id,
                )
                return latest_data
        except Exception as exc:
            _logger.warning(
                "MISA PR: entity API khong doc duoc PR %r, "
                "thu fallback FormDataNew: %s",
                purchase_request_id,
                exc,
            )

        form_layout_id = (
            raw_data.get("FormLayoutID")
            or raw_data.get("FormLayoutId")
            or raw_data.get("LayoutID")
            or raw_data.get("LayoutId")
        )
        if not form_layout_id:
            _logger.warning(
                "MISA PR: PR %r khong co FormLayoutID; "
                "khong the fallback FormDataNew",
                purchase_request_id,
            )
            return {}

        form_url = (
            "https://amisapp.misa.vn/crm/g2/api/business/PurchaseRequest/"
            "FormDataNew/PurchaseRequest/%s/4" % form_layout_id
        )
        form_payload = {
            "ID": str(purchase_request_id),
            "MISAEntityState": 2,
            "ActiveLayoutCode": None,
            "CustomDicData": None,
        }
        try:
            response = requests.post(
                form_url,
                headers=headers,
                json=form_payload,
                timeout=30,
            )
            response.raise_for_status()
            latest_data = _unwrap_response(response.json())
            if _contains_description(latest_data):
                _logger.info(
                    "MISA PR: da tai header moi nhat bang FormDataNew, ID=%r",
                    purchase_request_id,
                )
                return latest_data
        except Exception as exc:
            _logger.exception(
                "MISA PR: khong tai lai duoc header PR %r tu MISA: %s",
                purchase_request_id,
                exc,
            )
        return {}

    @staticmethod
    def _misa_latest_description(latest_data, fallback=""):
        """Read a description while preserving an intentionally empty value."""
        for key in ("Description", "description", "Note", "note", "Reason"):
            if key in latest_data:
                value = latest_data.get(key)
                return "" if value is None else str(value)
        return fallback

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
        
        # Tìm Đơn bán hàng liên quan hoặc Mục đích mua
        so_name = (payload.get("SaleOrderIDText") or "").strip()
        purchase_purpose = (payload.get("PurchasePurpose") or "").strip()
        origin_val = so_name or purchase_purpose or "MISA CRM"

        sale_order_id = False
        if so_name:
            so = self.env["sale.order"].search([("name", "=", so_name)], limit=1)
            if so:
                sale_order_id = so.id

        raw_data = payload.get("rawData") or {}
        latest_misa_data = self._misa_fetch_latest_purchase_request(raw_data)
        description = self._misa_latest_description(
            latest_misa_data,
            fallback=payload.get("description") or "",
        )
        picking_type_id = self._resolve_misa_picking_type(raw_data, self.env.company.id)
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
                "description": description,
                "delivery_address": payload.get("DeliveryAddress") or "",
                "sale_order_id": sale_order_id,
                "origin": origin_val,
            }
            if picking_type_id:
                write_vals["picking_type_id"] = picking_type_id
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
                "origin": origin_val,
                "description": description,
                "delivery_address": payload.get("DeliveryAddress") or "",
                "sale_order_id": sale_order_id,
                "x_misa_requested_by": payload.get("OwnerIDText") or "",
            }
            if picking_type_id:
                pr_vals["picking_type_id"] = picking_type_id
            if date_start:
                pr_vals["date_start"] = date_start
            if create_date:
                pr_vals["create_date"] = create_date
            pr = self.create(pr_vals)

        # Xử lý lines
        product_model = self.env["product.product"]
        uom_model = self.env["uom.uom"]
        line_model = self.env["purchase.request.line"]
        conversion_cache = {}
        crm_headers = None

        def _resolve_product_and_uom(line_data):
            pcode = (line_data.get("product_code") or "").strip()
            line_raw_data = line_data.get("rawData") or {}
            uom_name = (
                line_data.get("uom")
                or line_raw_data.get("UnitIDText")
                or ""
            ).strip()
            product = False
            if pcode:
                product = product_model.search([("default_code", "=", pcode)], limit=1)
                
            if pcode and not product:
                # Gọi odoo.utils của module misa_fetch_po_button để tạo/lấy sản phẩm
                unit_name = uom_name or "Cái"
                if unit_name:
                    uom_exist = uom_model.search([("name", "=ilike", unit_name.strip())], limit=1)
                    if uom_exist and uom_exist.name != unit_name.strip().title():
                        try:
                            uom_exist.write({'name': unit_name.strip().title()})
                        except Exception:
                            pass
                product_name = (line_data.get("name") or line_data.get("product_name") or pcode).strip()
                
                price_unit = 0.0
                try:
                    price_unit = float(line_data.get("misa_price_before_tax") or 0.0)
                except (ValueError, TypeError):
                    pass
                
                odoo_utils = self.env["odoo.utils"].sudo()
                product = odoo_utils._get_or_create_product(
                    code=pcode,
                    name=product_name,
                    unit_name=unit_name,
                    cost=price_unit,
                    product_type="consu",
                    purchase_ok=True,
                    sale_ok=True,
                )
                _logger.info("MISA Sync PR: Gọi odoo.utils tạo sản phẩm mới %s (%s)", product_name, pcode)

            uom = False
            if product:
                uom = product.uom_id
            elif uom_name:
                uom_match = uom_model.search([("name", "=ilike", uom_name)], limit=1)
                if uom_match:
                    uom = uom_match
            return product, uom

        for idx, line in enumerate(lines_in):
            misa_line_id = (line.get("misa_line_id") or "").strip()
            
            product, uom = _resolve_product_and_uom(line)
            product_id = product.id if product else False
            uom_id = uom.id if uom else False

            # Ưu tiên lấy tên từ datasubpaging (line.get("name")), fallback về product.name
            line_name = (
                line.get("name")
                or line.get("product_name")
                or (product.name if product else "Sản phẩm không tên")
            ).strip()
            try:
                qty = float(line.get("qty", 1.0))
            except (ValueError, TypeError):
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
            
            raw = line.get("rawData") or {}
            custom_field_6 = raw.get("CustomField6")
            if custom_field_6 is None:
                custom_field_6 = line.get("CustomField6")
            misa_note_val = str(custom_field_6 or "").strip()

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

            price_before_tax = _float_val("misa_price_before_tax")
            price_after_tax = _float_val("misa_price_after_tax")

            # PR lines are always stored in the product's default Odoo UoM.
            # Normalize MISA quantity and unit prices before creating/updating
            # the line so its monetary totals remain unchanged.
            misa_uom_text = (
                line.get("uom")
                or raw.get("UnitIDText")
                or ""
            ).strip()
            misa_product_id = (
                line.get("misa_product_id")
                or line.get("ProductID")
                or line.get("ProductId")
                or raw.get("ProductID")
                or raw.get("ProductId")
            )
            if (
                product
                and misa_uom_text
                and misa_uom_text.strip().lower()
                != ((product.uom_id and product.uom_id.name) or "").strip().lower()
            ):
                if crm_headers is None and misa_product_id:
                    crm_headers = (
                        self.env["misa.api.utils"]
                        .sudo()
                        ._get_cached_crm_headers()
                    )
                qty, unit_price_factor, _is_default_uom = (
                    self._convert_qty_price_to_default_uom(
                        product=product,
                        misa_uom_text=misa_uom_text,
                        qty=qty,
                        price=1.0,
                        misa_product_id=misa_product_id,
                        headers=crm_headers or {},
                        conversion_cache=conversion_cache,
                    )
                )
                price_before_tax *= unit_price_factor
                price_after_tax *= unit_price_factor

            line_vals = {
                "request_id": pr.id,
                "name": line_name,
                "product_id": product_id,
                "product_uom_id": uom_id,
                "product_qty": qty,
                "misa_line_id": misa_line_id,
                "sale_proposed_supplier_id": misa_supplier_id,
                "misa_supplier_id": misa_supplier_id,
                "misa_note": misa_note_val,
                # Các trường giá trị từ MISA
                "misa_amount": _float_val("misa_amount"),
                "misa_price_before_tax": price_before_tax,
                "misa_price_after_tax": price_after_tax,
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
