# hlv_barcode_shipper/controllers/barcode_controller.py
# -*- coding: utf-8 -*-

import base64
import json
import logging
import re
from datetime import timedelta

from markupsafe import Markup, escape
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError

VN_OFFSET = timedelta(hours=7)

_logger = logging.getLogger(__name__)


class BarcodeShipperController(http.Controller):
    # ===== Helpe12r =====
    def _check_shipper_access(self):
        """Check if current user has shipper access."""
        if not request.env.user.has_group("hlv_barcode_shipper.group_shipper"):
            return {
                "success": False,
                "error": "Truy cập bị từ chối. Bạn cần quyền 'Shipper'.",
            }
        return {"success": True}

    def _log_scan(self, barcode, scan_type, **kwargs):
        """Log barcode scan for audit trail."""
        try:
            request.env["barcode.scan.log"].log_scan(
                barcode=barcode,
                scan_type=scan_type,
                **kwargs,
            )
        except Exception as e:
            _logger.warning("Failed to log scan: %s", e)

    # ===== Helper: tìm OUT từ PICK – KHÔNG ở model, chỉ ở controller =====
    def _find_out_pickings_by_pick_name(self, pick_name):
        """
        Tìm TẤT CẢ phiếu OUT liên quan đến pick_name.
        Trả về recordset (có thể nhiều phiếu).
        """
        Picking = request.env["stock.picking"].sudo()

        # 0) Thử luôn: có phải đã là phiếu OUT không?
        out_direct = Picking.search([
            "|", ("name", "=", pick_name), ("name", "ilike", pick_name),
            ("picking_type_id.code", "=", "outgoing"),
            ("state", "in", ["assigned", "partially_available"]),
        ])
        if out_direct:
            return out_direct

        # 1) tìm phiếu PICK theo name (bất kể code gì)
        pick = Picking.search([("name", "=", pick_name)], limit=1)
        if not pick:
            pick = Picking.search([("name", "ilike", pick_name)], limit=1)

        if not pick:
            # 1.1) Thử tìm theo Sale Order (Phiếu báo giá)
            SaleOrder = request.env.get("sale.order")
            if SaleOrder is not None:
                so = SaleOrder.sudo().search([("name", "=", pick_name)], limit=1)
                if not so:
                    so = SaleOrder.sudo().search([("name", "ilike", pick_name)], limit=1)

                if so:
                    # Nếu tìm thấy SO, tìm TẤT CẢ phiếu OUT liên quan
                    out_from_so = so.picking_ids.filtered(
                        lambda p: p.picking_type_id.code == "outgoing"
                        and p.state in ["assigned", "partially_available"]
                    )
                    if out_from_so:
                        return out_from_so
                    
                    raise UserError(
                        f"Phiếu báo giá {so.name} không có phiếu xuất kho (OUT) nào đang sẵn sàng."
                    )

            raise UserError(f"Không tìm thấy phiếu {pick_name}")

        # 2) thử theo group_id - lấy TẤT CẢ
        out_pickings = Picking.browse()
        if pick.group_id:
            out_pickings = Picking.search([
                ("group_id", "=", pick.group_id.id),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
            ])

        # 3) fallback theo origin - lấy TẤT CẢ
        if not out_pickings and pick.origin:
            out_pickings = Picking.search([
                ("origin", "=", pick.origin),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
            ])

        if not out_pickings:
            raise UserError(f"Không tìm thấy phiếu xuất kho (OUT) nào liên quan đến {pick_name}")

        return out_pickings

    def _get_packages_info(self, picking):
        """
        Đọc danh sách kiện / sản phẩm từ phiếu OUT.
        Trả về items với flag 'scanned' = True nếu item đó được bỏ qua theo setting.
        """
        items = []

        # Đọc settings từ company
        try:
            skip_package = request.env.company.hlv_barcode_skip_package_scan
        except Exception:
            skip_package = False
        
        try:
            skip_product = request.env.company.hlv_barcode_skip_product_scan
        except Exception:
            skip_product = False

        # 1. Lấy danh sách Packages
        for pl in picking.package_level_ids:
            if not pl.package_id:
                continue
            children = []
            for ml in pl.move_line_ids:
                if ml.product_id:
                    children.append({
                        "name": ml.product_id.display_name,
                        "barcode": ml.product_id.barcode or ml.product_id.default_code or "",
                        "qty": ml.quantity,
                    })
            items.append(
                {
                    "type": "package",
                    "id": pl.id,
                    "name": pl.package_id.name,
                    "barcode": pl.package_id.name,
                    "qty": pl.move_line_ids and sum(pl.move_line_ids.mapped("quantity")) or 0,
                    "scanned": skip_package,  # True = tự động đã quét
                    "picking_id": picking.id, # Link item to picking
                    "children": children,
                }
            )

        # 2. Lấy danh sách sản phẩm lẻ (không thuộc package)
        loose_lines = picking.move_line_ids.filtered(lambda ml: not ml.result_package_id)
        
        for ml in loose_lines:
            items.append(
                {
                    "type": "product",
                    "id": ml.id,
                    "name": ml.product_id.display_name,
                    "barcode": ml.product_id.barcode
                    or ml.product_id.default_code
                    or "",
                    "qty": ml.quantity,
                    "scanned": skip_product,  # True = tự động đã quét
                    "picking_id": picking.id, # Link item to picking
                }
            )

        return items

    def _scan_package_in_picking(self, picking, barcode):
        """
        Kiểm tra barcode có nằm trong picking không.
        Không ghi DB, chỉ trả kết quả để JS xử lý.
        Logic mới: Luôn cho phép quét cả package và product, 
        vì việc bỏ qua được xử lý ở _get_packages_info (scanned flag).
        """
        barcode = (barcode or "").strip()
        if not barcode:
            return {"success": False, "error": "Mã vạch trống"}

        # Kiểm tra Package
        for pl in picking.package_level_ids:
            if pl.package_id and pl.package_id.name == barcode:
                return {
                    "success": True,
                    "type": "package",
                    "name": pl.package_id.name,
                    "message": f"Đã tìm thấy kiện {barcode}",
                    "picking_id": picking.id
                }

        # Kiểm tra Product barcode / default_code
        lines = picking.move_line_ids.filtered(
            lambda ml: ml.product_id
            and (
                (ml.product_id.barcode and ml.product_id.barcode == barcode)
                or (ml.product_id.default_code and ml.product_id.default_code == barcode)
            )
        )
        if lines:
            prod = lines[0].product_id
            return {
                "success": True,
                "type": "product",
                "name": prod.display_name,
                "message": f"Đã tìm thấy sản phẩm {barcode}",
                "picking_id": picking.id
            }

        return {
            "success": False,
            "error": f"Không tìm thấy mã {barcode} trong đơn này",
        }

    # ===== API: scan PICK =====
    @http.route(
        "/api/barcode/scan_pick",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_pick_order(self, **kwargs):
        """
        Scan PICK order barcode.
        
        Logic Mới: 
        1. Tìm các OUT liên quan đến mã quét.
        2. Từ đó xác định Partner (Khách hàng).
        3. Tìm TẤT CẢ các phiếu OUT khác của Partner này mà đang sẵn sàng.
        4. Gom nhóm theo SO (Origin).
        """
        barcode = ""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            barcode = data.get("barcode", "").strip()

            if not barcode:
                return {"success": False, "error": "Vui lòng nhập mã vạch"}

            # 1. Tìm initial OUTs
            initial_out_pickings = self._find_out_pickings_by_pick_name(barcode)
            
            if not initial_out_pickings:
                 return {"success": False, "error": "Không tìm thấy phiếu xuất kho nào."}

            # 2. Xác định Partner từ phiếu đầu tiên tìm thấy
            # Chúng ta giả định tất cả phiếu tìm thấy từ 1 mã scan (ví dụ PICK) đều cùng 1 luồng/khách hàng
            partner = initial_out_pickings[0].partner_id
            if not partner:
                return {"success": False, "error": f"Phiếu {initial_out_pickings[0].name} không có thông tin Khách hàng."}

            # 3. Tìm tất cả OUT của Partner này đã được shipper nhận (shipper_received=True)
            # Chỉ hiển thị phiếu đã nhận bởi shipper hiện tại, chưa trả lại
            uid = request.env.user.id
            all_partner_outs = request.env["stock.picking"].sudo().search([
                ("partner_id", "=", partner.id),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
                ("shipper_received", "=", True),
                ("shipper_returned", "=", False),
                "|",
                ("shipper_received_by", "=", uid),
                ("shipper_user_id", "=", uid),
            ])

            if not all_partner_outs:
                return {
                    "success": False,
                    "error": (
                        f"Không tìm thấy phiếu nào bạn đã nhận của khách hàng này. "
                        f"Vui lòng vào tab 'Nhận hàng' để nhận phiếu trước khi giao."
                    ),
                }

            # 4. Group by SO (Origin)
            so_groups_map = {}
            
            related_ids = initial_out_pickings.ids

            for p in all_partner_outs:
                # Group key: Origin (thường là SO name) hoặc 'Undefined'
                group_key = p.origin or "Không xác định"
                
                if group_key not in so_groups_map:
                    so_groups_map[group_key] = {
                        "so_name": group_key,
                        "pickings": []
                    }
                
                so_groups_map[group_key]["pickings"].append({
                    "id": p.id,
                    "name": p.name,
                    "state": p.state,
                    "scheduled_date": p.scheduled_date.strftime("%d/%m/%Y") if p.scheduled_date else "",
                    "is_related": p.id in related_ids, # Flag để default check nếu muốn
                })

            so_groups_list = list(so_groups_map.values())
            # Sort groups by name
            so_groups_list.sort(key=lambda x: x["so_name"])

            self._log_scan(
                barcode=barcode,
                scan_type="pick",
                status="success",
                message=f"Tìm thấy {len(all_partner_outs)} phiếu OUT cho khách {partner.name}",
            )

            return {
                "success": True,
                "multiple": True, # Luôn coi là multiple để hiện giao diện chọn
                "customer_name": partner.name or "Khách hàng",
                "customer_address": partner.contact_address or "",
                "so_groups": so_groups_list,
                "message": f"Tìm thấy {len(all_partner_outs)} phiếu của {partner.name}",
            }

        except UserError as e:
            self._log_scan(
                barcode=barcode,
                scan_type="pick",
                status="error",
                message=str(e),
            )
            return {"success": False, "error": str(e)}
        except Exception as e:
            _logger.exception("Error in scan_pick_order")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}


    # ===== API: get details for MULTIPLE OUT pickings =====
    @http.route(
        "/api/barcode/get_multiple_outs",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_multiple_out_details(self, **kwargs):
        """
        Return list of details for provided picking_ids.
        
        Payload:
        { "picking_ids": [1, 2, 3] }
        """
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_ids = data.get("picking_ids", [])

            if not picking_ids:
                return {"success": False, "error": "Chưa chọn phiếu nào"}

            pickings = request.env["stock.picking"].sudo().browse(picking_ids)
            result_data = []

            for picking in pickings:
                items = self._get_packages_info(picking)
                result_data.append({
                    "picking": {
                        "id": picking.id,
                        "name": picking.name,
                        "origin": picking.origin or "",
                        "partner_name": picking.partner_id.name or "",
                    },
                    "items": items,
                })
            
            return {
                "success": True,
                "data": result_data
            }

        except Exception as e:
            _logger.exception("Error in get_multiple_out_details")
            return {"success": False, "error": "Lỗi khi tải thông tin đơn hàng"}


    # ===== API: scan package/product (Vẫn giữ logic cũ, chỉ cần loop qua picking list ở JS) =====
    @http.route(
        "/api/barcode/scan_package",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_package_or_product(self, **kwargs):
        """
        Scan package or product barcode inside A SPECIFIC PICKING.
        Current UI will likely scan against the 'active' picking.
        
        Payload:
        { "picking_id": 123, "barcode": "PACK001" }
        """
        barcode = ""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_id = data.get("picking_id")
            barcode = data.get("barcode", "").strip()

            if not picking_id or not barcode:
                return {
                    "success": False,
                    "error": "Thiếu Picking ID hoặc mã vạch",
                }

            picking = request.env["stock.picking"].sudo().browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Không tìm thấy phiếu kho"}

            result = self._scan_package_in_picking(picking, barcode)

            status = "success" if result.get("success") else "error"
            
            # Chỉ log nếu thành công hoặc lỗi nghiêm trọng? 
            # Log mọi lần scan cũng được
            self._log_scan(
                barcode=barcode,
                scan_type=result.get("type") or "package",
                picking_id=picking.id,
                status=status,
                message=result.get("message") or result.get("error"),
            )

            return result

        except Exception as e:
            _logger.exception("Error in scan_package_or_product")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: complete OUT (BATCH) =====
    @http.route(
        "/api/barcode/complete_out",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def complete_out(self, **kwargs):
        """
        Call button_validate() for MULTIPLE pickings.
        
        Payload:
        { "picking_ids": [123, 124] }
        """
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_ids = data.get("picking_ids", [])
            
            # Backup for backward compatibility (if single picking_id passed)
            if not picking_ids and data.get("picking_id"):
                 picking_ids = [data.get("picking_id")]

            if not picking_ids:
                return {"success": False, "error": "Thiếu Picking ID"}

            pickings = request.env["stock.picking"].sudo().browse(picking_ids)
            
            success_names = []
            errors = []

            for picking in pickings:
                try:
                    if picking.picking_type_id.code != "outgoing":
                        errors.append(f"{picking.name}: Không phải phiếu xuất kho")
                        continue
                    
                    if picking.state not in ['assigned', 'partially_available']:
                        # Có thể đã done rồi
                        if picking.state == 'done':
                            success_names.append(picking.name)
                            continue
                        else:
                            errors.append(f"{picking.name}: Trạng thái không hợp lệ ({picking.state})")
                            continue

                    picking.button_validate()
                    success_names.append(picking.name)
                    
                    self._log_scan(
                        barcode=picking.name,
                        scan_type="complete",
                        picking_id=picking.id,
                        status="success",
                        message=f"Đơn hàng {picking.name} đã hoàn tất",
                    )
                except Exception as e:
                    _logger.exception(f"Error validating picking {picking.name}")
                    errors.append(f"{picking.name}: Lỗi hệ thống ({str(e)})")

            if errors:
                return {
                    "success": False, 
                    "error": "\n".join(errors),
                    "partial_success": len(success_names) > 0
                }
            
            return {
                "success": True,
                "message": f"Đã hoàn tất {len(success_names)} đơn hàng thành công!",
            }
            
        except Exception as e:
            _logger.exception("Error in complete_out")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: get delivered pickings =====
    @http.route(
        "/api/barcode/get_delivered",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_delivered(self, **kwargs):
        """Return pickings delivered (state=done) by the current shipper."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            date_filter = data.get("params", {}).get("date_filter") or data.get("date_filter")

            uid = request.env.user.id
            domain = [
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "=", "done"),
                "|",
                ("shipper_received_by", "=", uid),
                ("shipper_user_id", "=", uid),
            ]

            if date_filter:
                from datetime import datetime
                try:
                    day = datetime.strptime(date_filter, "%Y-%m-%d")
                    day_start = day.replace(hour=0, minute=0, second=0) - VN_OFFSET
                    day_end = day.replace(hour=23, minute=59, second=59) - VN_OFFSET
                    domain += [
                        ("date_done", ">=", day_start),
                        ("date_done", "<=", day_end),
                    ]
                except ValueError:
                    pass

            pickings = request.env["stock.picking"].sudo().search(
                domain, order="date_done desc", limit=100
            )

            result = []
            for p in pickings:
                address, sale_order_name, address_source = self._get_picking_misa_shipping_address(p)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "origin": p.origin or "",
                    "sale_order_name": sale_order_name,
                    "partner_name": p.partner_id.name or "",
                    "address": address,
                    "address_source": address_source,
                    "date_done": (p.date_done + VN_OFFSET).strftime("%H:%M %d/%m/%Y") if p.date_done else "",
                })

            return {"success": True, "pickings": result}
        except Exception as e:
            _logger.exception("Error in get_delivered")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: history =====
    @http.route(
        "/api/barcode/scan_history",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_history(self, **kwargs):
        """Return last N scans for current user / picking."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_id = data.get("picking_id")
            limit = int(data.get("limit") or 50)

            log_obj = request.env["barcode.scan.log"]
            # TODO: Support filtering by list of pickings? 
            # For now, just show logs for specific picking or user's recent logs.
            logs = log_obj.get_scan_history(
                picking_id=picking_id, user_id=request.env.user.id, limit=limit
            )

            history = []
            for log in logs:
                history.append(
                    {
                        "barcode": log.barcode,
                        "scan_type": log.scan_type,
                        "scan_time": (log.scan_time + VN_OFFSET).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if log.scan_time
                        else "",
                        "status": log.status,
                        "message": log.message or "",
                        "picking_name": log.picking_id.name or "",
                        "package_name": log.package_id.name or "",
                        "product_name": log.product_id.display_name or "",
                    }
                )

            return {"success": True, "history": history}
        except Exception as e:
            _logger.exception("Error in scan_history")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== Web UI: /barcode/shipper =====
    @http.route("/barcode/shipper", type="http", auth="user", website=False)
    def shipper_interface(self, **kwargs):
        """Main shipper interface page."""
        if not request.env.user.has_group("hlv_barcode_shipper.group_shipper"):
            return request.render(
                "hlv_barcode_shipper.access_denied", {"user": request.env.user}
            )
        return request.render(
            "hlv_barcode_shipper.shipper_interface", {"user": request.env.user}
        )

    # ===== Web UI V2: /barcode/shipper_v2 (OWL) =====
    # @http.route("/barcode/shipper_v2", type="http", auth="user", website=False)
    # def shipper_interface_v2(self, **kwargs):
    #     """V2 shipper interface page using OWL."""
    #     if not request.env.user.has_group("hlv_barcode_shipper.group_shipper"):
    #         return request.render(
    #             "hlv_barcode_shipper.access_denied", {"user": request.env.user}
    #         )
    #     return request.render(
    #         "hlv_barcode_shipper.shipper_interface_v2", {"user": request.env.user}
    #     )

    # ===== Web UI: /barcode/shipper_route (delivery route planner) =====
    @http.route("/barcode/shipper_route", type="http", auth="user", website=False)
    def shipper_delivery_route(self, **kwargs):
        """Route planner page for already received delivery orders."""
        if not request.env.user.has_group("hlv_barcode_shipper.group_shipper"):
            return request.render(
                "hlv_barcode_shipper.access_denied", {"user": request.env.user}
            )
        return request.render(
            "hlv_barcode_shipper.delivery_route_interface",
            {
                "user": request.env.user,
                "google_maps_api_key": request.env.company.hlv_barcode_google_maps_api_key or "",
            },
        )

    def _get_sale_order_for_picking(self, picking):
        """Resolve the sale order linked to a picking without relying only on origin."""
        SaleOrder = request.env["sale.order"]

        sale_orders = SaleOrder.sudo().browse()
        if "sale_id" in picking._fields and picking.sale_id:
            sale_orders |= picking.sale_id.sudo()
        if "move_ids" in picking._fields and "sale_line_id" in request.env["stock.move"]._fields:
            sale_orders |= picking.move_ids.mapped("sale_line_id.order_id").sudo()
        if "move_line_ids" in picking._fields and "sale_line_id" in request.env["stock.move"]._fields:
            sale_orders |= picking.move_line_ids.mapped("move_id.sale_line_id.order_id").sudo()
        if "group_id" in picking._fields and picking.group_id and "sale_id" in picking.group_id._fields:
            sale_orders |= picking.group_id.sale_id.sudo()

        if sale_orders:
            with_address = sale_orders.filtered(lambda so: bool(getattr(so, "misa_shipping_address", False)))
            return (with_address or sale_orders)[:1]

        origin = (picking.origin or "").strip()
        if not origin:
            return False

        origin_names = [origin]
        origin_names += [
            token.strip()
            for token in re.split(r"[,;|\s]+", origin)
            if token.strip()
        ]
        sale_order = SaleOrder.sudo().search([("name", "in", list(dict.fromkeys(origin_names)))], limit=1)
        if not sale_order:
            sale_order = SaleOrder.sudo().search([("name", "ilike", origin)], limit=1)
        return sale_order

    def _get_first_text_field(self, record, field_names):
        """Return the first non-empty text value among possible fields."""
        for field_name in field_names:
            if field_name in record._fields:
                value = getattr(record, field_name, False)
                if value:
                    return value, field_name
        return "", ""

    def _get_picking_misa_shipping_address(self, picking):
        """Return delivery address from picking first, then sale.order.misa_shipping_address."""
        picking_address, source_field = self._get_first_text_field(picking, [
            "x_studio_dia_chi_giao_hang",
            "x_misa_shipping_address",
        ])
        if picking_address:
            return picking_address, picking.origin or "", source_field

        sale_order = self._get_sale_order_for_picking(picking)
        if not sale_order:
            return "", "", ""

        sale_address, source_field = self._get_first_text_field(sale_order, [
            "misa_shipping_address",
        ])
        return sale_address, sale_order.name or "", source_field

    # ===== API: delivery route stops =====
    @http.route(
        "/api/barcode/delivery_route_stops",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def delivery_route_stops(self, **kwargs):
        """Return received OUT pickings as route stops for the current shipper."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            uid = request.env.user.id
            pickings = request.env["stock.picking"].sudo().search([
                ("shipper_received", "=", True),
                ("shipper_returned", "=", False),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
                "|",
                ("shipper_received_by", "=", uid),
                ("shipper_user_id", "=", uid),
            ], order="shipper_receive_time desc, scheduled_date asc, name asc")

            stops = []
            missing_address = []
            for sequence, picking in enumerate(pickings, start=1):
                address, sale_order_name, address_source = self._get_picking_misa_shipping_address(picking)
                if not address:
                    missing_address.append({
                        "picking_name": picking.name,
                        "origin": picking.origin or "",
                        "sale_order_name": sale_order_name,
                    })
                    continue

                lat = False
                lng = False
                if picking.partner_id:
                    root_partner = picking.partner_id.commercial_partner_id or picking.partner_id
                    clean_address = address.strip().lower()
                    for loc in root_partner.hlv_delivery_location_ids:
                        if loc.address and loc.address.strip().lower() == clean_address:
                            lat = loc.latitude
                            lng = loc.longitude
                            break

                item_count = len(picking.package_level_ids) + len(
                    picking.move_line_ids.filtered(lambda ml: not ml.result_package_id)
                )
                stops.append({
                    "id": picking.id,
                    "sequence": sequence,
                    "picking_name": picking.name,
                    "origin": picking.origin or "",
                    "sale_order_name": sale_order_name,
                    "partner_name": picking.partner_id.name or "",
                    "partner_id": picking.partner_id.id,
                    "address": address,
                    "address_source": address_source,
                    "lat": lat,
                    "lng": lng,
                    "item_count": item_count,
                    "receive_time": (
                        (picking.shipper_receive_time + VN_OFFSET).strftime("%H:%M %d/%m")
                        if picking.shipper_receive_time else ""
                    ),
                })

            return {
                "success": True,
                "stops": stops,
                "missing_address": missing_address,
                "received_count": len(pickings),
                "google_maps_api_key": request.env.company.hlv_barcode_google_maps_api_key or "",
            }
        except Exception:
            _logger.exception("Error in delivery_route_stops")
            return {"success": False, "error": "Không thể tải danh sách điểm giao"}

    @http.route(
        "/api/barcode/save_geocode",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def save_geocode(self, **kwargs):
        """Save a new geocode for a root partner's address."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            partner_id = data.get("partner_id")
            address = data.get("address")
            lat = data.get("lat")
            lng = data.get("lng")

            if not partner_id or not address or lat is None or lng is None:
                return {"success": False, "error": "Thiếu dữ liệu"}

            partner = request.env["res.partner"].sudo().browse(partner_id)
            if not partner.exists():
                return {"success": False, "error": "Không tìm thấy đối tác"}

            root_partner = partner.commercial_partner_id or partner
            clean_address = address.strip().lower()

            Location = request.env["res.partner.delivery.location"].sudo()
            
            exists = False
            for loc in root_partner.hlv_delivery_location_ids:
                if loc.address and loc.address.strip().lower() == clean_address:
                    exists = True
                    # Update if coordinates are significantly different? (optional, skip for now as user just wants to save new)
                    break
            
            if not exists:
                Location.create({
                    "partner_id": root_partner.id,
                    "address": address.strip(),
                    "latitude": lat,
                    "longitude": lng,
                })
            
            return {"success": True}
        except Exception:
            _logger.exception("Error in save_geocode")
            return {"success": False}

    # ===== API: get settings =====
    @http.route(
        "/api/barcode/get_settings",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_settings(self, **kwargs):
        """Return barcode shipper config settings for JS frontend."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            company = request.env.company
            return {
                "success": True,
                "settings": {
                    "skip_package_scan": company.hlv_barcode_skip_package_scan,
                    "skip_product_scan": company.hlv_barcode_skip_product_scan,
                    "receive_require_detail_scan": company.hlv_barcode_receive_require_detail_scan,
                    "receive_skip_package_scan": company.hlv_barcode_receive_skip_package_scan,
                    "receive_skip_product_scan": company.hlv_barcode_receive_skip_product_scan,
                    "return_require_detail_scan": company.hlv_barcode_return_require_detail_scan,
                    "return_skip_package_scan": company.hlv_barcode_return_skip_package_scan,
                    "return_skip_product_scan": company.hlv_barcode_return_skip_product_scan,
                },
            }
        except Exception as e:
            _logger.exception("Error in get_settings")
            return {"success": False, "error": "Lỗi tải cấu hình"}

    # ===== API: receive pickings =====
    @http.route(
        "/api/barcode/receive_pickings",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def receive_pickings(self, **kwargs):
        """Shipper confirms receiving pickings for delivery."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_ids = data.get("picking_ids", [])

            if not picking_ids:
                return {"success": False, "error": "Chưa chọn phiếu nào"}

            pickings = request.env["stock.picking"].sudo().browse(picking_ids)
            received = []

            for picking in pickings:
                if not picking.exists():
                    continue
                picking.write({
                    "shipper_received": True,
                    "shipper_receive_time": fields.Datetime.now(),
                    "shipper_received_by": request.env.user.id,
                    "shipper_user_id": request.env.user.id,
                    "shipper_returned": False,
                    "shipper_return_time": False,
                    "shipper_return_reason": False,
                })
                received.append(picking.name)

                self._log_scan(
                    barcode=picking.name,
                    scan_type="receive",
                    picking_id=picking.id,
                    status="success",
                    message=f"Shipper nhận phiếu {picking.name}",
                )

            return {
                "success": True,
                "message": f"Đã nhận {len(received)} phiếu thành công!",
            }
        except Exception as e:
            _logger.exception("Error in receive_pickings")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: get my received pickings =====
    @http.route(
        "/api/barcode/get_my_received",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_my_received(self, **kwargs):
        """Get pickings received by current shipper that are not yet delivered or returned."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            uid = request.env.user.id
            pickings = request.env["stock.picking"].sudo().search([
                ("shipper_received", "=", True),
                ("shipper_returned", "=", False),
                "|",
                ("shipper_received_by", "=", uid),
                ("shipper_user_id", "=", uid),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
            ], order="shipper_receive_time desc")

            result = []
            for p in pickings:
                item_count = len(p.package_level_ids) + len(
                    p.move_line_ids.filtered(lambda ml: not ml.result_package_id)
                )
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "origin": p.origin or "",
                    "partner_name": p.partner_id.name or "",
                    "item_count": item_count,
                    "receive_time": (p.shipper_receive_time + VN_OFFSET).strftime("%H:%M %d/%m") if p.shipper_receive_time else "",
                })

            return {"success": True, "pickings": result}
        except Exception as e:
            _logger.exception("Error in get_my_received")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: return pickings =====
    @http.route(
        "/api/barcode/return_pickings",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def return_pickings(self, **kwargs):
        """Shipper returns pickings back to warehouse."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_ids = data.get("picking_ids", [])
            reason = data.get("reason", "").strip()

            if not picking_ids:
                return {"success": False, "error": "Chưa chọn phiếu nào"}
            if not reason:
                return {"success": False, "error": "Vui lòng nhập lý do trả hàng"}

            pickings = request.env["stock.picking"].sudo().browse(picking_ids)
            returned = []

            for picking in pickings:
                if not picking.exists():
                    continue
                picking.write({
                    "shipper_returned": True,
                    "shipper_return_time": fields.Datetime.now(),
                    "shipper_return_reason": reason,
                    "shipper_received": False,
                })
                returned.append(picking.name)

                self._log_scan(
                    barcode=picking.name,
                    scan_type="return",
                    picking_id=picking.id,
                    status="success",
                    message=f"Shipper trả phiếu {picking.name}: {reason}",
                )

            return {
                "success": True,
                "message": f"Đã trả {len(returned)} phiếu thành công!",
            }
        except Exception as e:
            _logger.exception("Error in return_pickings")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: get all available pickings to receive =====
    @http.route(
        "/api/barcode/get_available_to_receive",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_available_to_receive(self, **kwargs):
        """Return outgoing pickings available to be received (not yet received).
        Supports search, limit, offset for pagination."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            search_query = (data.get("search") or "").strip()
            limit = int(data.get("limit") or 20)
            offset = int(data.get("offset") or 0)

            domain = [
                ("company_id", "=", request.env.company.id),
                ("picking_type_id.code", "=", "outgoing"),
                ("state", "in", ["assigned", "partially_available"]),
                ("shipper_received", "=", False),
            ]
            if search_query:
                domain += ['|', ("name", "ilike", search_query), ("origin", "ilike", search_query)]

            Picking = request.env["stock.picking"].sudo()
            total = Picking.search_count(domain)

            if search_query:
                # Return all matches when searching (no pagination)
                pickings = Picking.search(domain, order="scheduled_date asc, name asc")
            else:
                pickings = Picking.search(domain, order="scheduled_date asc, name asc", limit=limit, offset=offset)

            # Exact match detection for auto-select (name OR origin matches exactly)
            auto_select_ids = []
            if search_query:
                q_upper = search_query.upper()
                exact = pickings.filtered(
                    lambda p: p.name.upper() == q_upper or (p.origin or "").upper() == q_upper
                )
                auto_select_ids = exact.ids

            # Nếu không tìm thấy exact match, thử tìm theo mã PICK
            # (tương tự luồng giao hàng: quét PICK → tìm OUT liên quan)
            if search_query and not auto_select_ids:
                try:
                    resolved_outs = self._find_out_pickings_by_pick_name(search_query)
                    unreceived = resolved_outs.filtered(
                        lambda p: not p.shipper_received
                        and p.state in ("assigned", "partially_available")
                        and p.company_id.id == request.env.company.id
                    )
                    if unreceived:
                        # Merge vào kết quả nếu chưa có
                        new_pickings = unreceived - pickings
                        pickings = pickings | new_pickings
                        total = len(pickings)
                        auto_select_ids = unreceived.ids
                except Exception:
                    pass  # Không tìm thấy qua PICK code thì bỏ qua

            so_groups_map = {}
            for p in pickings:
                group_key = p.origin or p.name
                if group_key not in so_groups_map:
                    so_groups_map[group_key] = {"so_name": group_key, "pickings": []}
                item_count = len(p.package_level_ids) + len(
                    p.move_line_ids.filtered(lambda ml: not ml.result_package_id)
                )
                so_groups_map[group_key]["pickings"].append({
                    "id": p.id,
                    "name": p.name,
                    "state": p.state,
                    "origin": p.origin or "",
                    "partner_name": p.partner_id.name or "",
                    "partner_id": p.partner_id.id,
                    "scheduled_date": p.scheduled_date.strftime("%d/%m/%Y") if p.scheduled_date else "",
                    "item_count": item_count,
                })

            so_groups_list = sorted(so_groups_map.values(), key=lambda x: x["so_name"])
            shown = len(pickings)
            return {
                "success": True,
                "so_groups": so_groups_list,
                "total": total,
                "shown": shown,
                "has_more": (not search_query) and ((offset + shown) < total),
                "auto_select_ids": auto_select_ids,
            }
        except Exception as e:
            _logger.exception("Error in get_available_to_receive")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: scan picking barcode for receive tab =====
    @http.route(
        "/api/barcode/scan_pick_receive",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_pick_for_receive(self, **kwargs):
        """Find pickings by barcode for the receive tab."""
        barcode = ""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            barcode = data.get("barcode", "").strip()
            if not barcode:
                return {"success": False, "error": "Vui lòng nhập mã vạch"}

            initial_outs = self._find_out_pickings_by_pick_name(barcode)
            if not initial_outs:
                return {"success": False, "error": f"Không tìm thấy phiếu: {barcode}"}

            # Only consider pickings not yet received
            unreceived = initial_outs.filtered(lambda p: not p.shipper_received)
            if not unreceived:
                already = initial_outs.filtered(lambda p: p.shipper_received)
                names = ", ".join(already.mapped("name"))
                return {
                    "success": False,
                    "error": f"Tất cả phiếu liên quan đã được nhận rồi ({names})",
                }

            partner = unreceived[0].partner_id
            return {
                "success": True,
                "related_ids": unreceived.ids,
                "partner_name": partner.name or "",
                "message": f"Tìm thấy {len(unreceived)} phiếu của {partner.name}",
            }
        except UserError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            _logger.exception("Error in scan_pick_for_receive")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: scan picking barcode for return tab =====
    @http.route(
        "/api/barcode/scan_pick_return",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_pick_for_return(self, **kwargs):
        """Scan PICK/SO code to find related OUT pickings that shipper has received (for return)."""
        barcode = ""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            barcode = data.get("barcode", "").strip()
            if not barcode:
                return {"success": False, "error": "Vui lòng nhập mã vạch"}

            # Tìm OUT pickings liên quan qua PICK/SO code
            initial_outs = self._find_out_pickings_by_pick_name(barcode)
            if not initial_outs:
                return {"success": False, "error": f"Không tìm thấy phiếu: {barcode}"}

            # Chỉ lấy phiếu đã nhận bởi shipper hiện tại, chưa trả, chưa done
            uid = request.env.user.id
            received = initial_outs.filtered(
                lambda p: p.shipper_received
                and not p.shipper_returned
                and p.state in ("assigned", "partially_available")
                and (p.shipper_received_by.id == uid or p.shipper_user_id.id == uid)
            )
            if not received:
                return {
                    "success": False,
                    "error": f"Không tìm thấy phiếu nào bạn đã nhận liên quan đến {barcode}",
                }

            return {
                "success": True,
                "related_ids": received.ids,
                "message": f"Tìm thấy {len(received)} phiếu liên quan",
            }
        except UserError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            _logger.exception("Error in scan_pick_for_return")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: upload delivery photo to chatter =====
    @http.route(
        "/api/barcode/upload_delivery_photo",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def upload_delivery_photo(self, **kwargs):
        """Receive a delivery photo and post it to the chatter of each picking."""
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return request.make_response(
                    json.dumps(access),
                    headers=[("Content-Type", "application/json")],
                )

            picking_ids_str = request.httprequest.form.get("picking_ids", "[]")
            try:
                picking_ids = json.loads(picking_ids_str)
            except Exception:
                picking_ids = []

            photo_file = request.httprequest.files.get("photo")

            if not picking_ids:
                return request.make_response(
                    json.dumps({"success": False, "error": "Thiếu Picking ID"}),
                    headers=[("Content-Type", "application/json")],
                )
            if not photo_file:
                return request.make_response(
                    json.dumps({"success": False, "error": "Không có ảnh được gửi"}),
                    headers=[("Content-Type", "application/json")],
                )

            photo_data = photo_file.read()
            if len(photo_data) > 10 * 1024 * 1024:
                return request.make_response(
                    json.dumps({"success": False, "error": "Ảnh quá lớn (tối đa 10MB)"}),
                    headers=[("Content-Type", "application/json")],
                )

            photo_name = photo_file.filename or "delivery_photo.jpg"
            shipper_name = request.env.user.shipper_name or request.env.user.name

            pickings = request.env["stock.picking"].sudo().browse(
                [int(pid) for pid in picking_ids]
            )
            posted = []
            for picking in pickings:
                if not picking.exists():
                    continue
                picking.message_post(
                    body=Markup(
                        "<p><i class='fa fa-camera'></i> Shipper <b>{}</b> "
                        "đã chụp ảnh phiếu giao hàng.</p>"
                    ).format(escape(shipper_name)),
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    attachments=[(photo_name, photo_data)],
                )
                posted.append(picking.name)
                self._log_scan(
                    barcode=picking.name,
                    scan_type="complete",
                    picking_id=picking.id,
                    status="success",
                    message=f"Shipper {shipper_name} gửi ảnh phiếu giao hàng",
                )

            return request.make_response(
                json.dumps({
                    "success": True,
                    "message": f"Đã gửi ảnh vào {len(posted)} đơn hàng thành công!",
                }),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.exception("Error in upload_delivery_photo")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )
