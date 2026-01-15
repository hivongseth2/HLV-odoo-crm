# hlv_barcode_shipper/controllers/barcode_controller.py
# -*- coding: utf-8 -*-

import json
import logging

from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BarcodeShipperController(http.Controller):
    # ===== Helper =====
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
            items.append(
                {
                    "type": "package",
                    "id": pl.id,
                    "name": pl.package_id.name,
                    "barcode": pl.package_id.name,
                    "qty": pl.move_line_ids and sum(pl.move_line_ids.mapped("quantity")) or 0,
                    "scanned": skip_package,  # True = tự động đã quét
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
        Scan PICK order barcode and find related OUT order(s).

        Payload:
        { "barcode": "PICK00001" }
        
        Response:
        - Nếu có 1 OUT: { success: true, out_picking_id, out_picking_name, ... }
        - Nếu có nhiều OUT: { success: true, multiple: true, pickings: [...] }
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

            out_pickings = self._find_out_pickings_by_pick_name(barcode)

            if len(out_pickings) == 1:
                # Chỉ có 1 phiếu -> tự động chọn
                out_picking = out_pickings[0]
                self._log_scan(
                    barcode=barcode,
                    scan_type="pick",
                    picking_id=out_picking.id,
                    status="success",
                    message=f"Tìm thấy đơn xuất kho {out_picking.name}",
                )
                return {
                    "success": True,
                    "out_picking_id": out_picking.id,
                    "out_picking_name": out_picking.name,
                    "message": f"Đã tìm thấy đơn giao hàng {out_picking.name}",
                }
            else:
                # Có nhiều phiếu -> trả về danh sách để user chọn
                pickings_list = []
                for p in out_pickings:
                    pickings_list.append({
                        "id": p.id,
                        "name": p.name,
                        "partner_name": p.partner_id.name or "",
                        "origin": p.origin or "",
                        "state": p.state,
                        "scheduled_date": p.scheduled_date.strftime("%d/%m/%Y") if p.scheduled_date else "",
                    })
                
                self._log_scan(
                    barcode=barcode,
                    scan_type="pick",
                    status="success",
                    message=f"Tìm thấy {len(out_pickings)} phiếu OUT",
                )
                
                return {
                    "success": True,
                    "multiple": True,
                    "pickings": pickings_list,
                    "message": f"Tìm thấy {len(out_pickings)} phiếu xuất kho. Vui lòng chọn một phiếu.",
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
            self._log_scan(
                barcode=barcode,
                scan_type="pick",
                status="error",
                message=f"Lỗi hệ thống: {e}",
            )
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}


    # ===== API: get OUT details =====
    @http.route(
        "/api/barcode/get_out",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def get_out_order_details(self, **kwargs):
        """
        Return OUT picking info + list packages/products for mobile.

        Payload:
        { "picking_id": 123 }
        """
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_id = data.get("picking_id")

            if not picking_id:
                return {"success": False, "error": "Thiếu Picking ID"}

            picking = request.env["stock.picking"].sudo().browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Không tìm thấy phiếu kho"}

            items = self._get_packages_info(picking)
            total = len(items)

            return {
                "success": True,
                "picking": {
                    "id": picking.id,
                    "name": picking.name,
                    "partner_name": picking.partner_id.name or "",
                    "state": picking.state,
                    "origin": picking.origin or "",
                },
                "items": items,
                "summary": {
                    "total_items": total,
                    "scanned_items": 0,      # scan client-side
                    "all_scanned": False,    # scan client-side
                },
            }
        except Exception as e:
            _logger.exception("Error in get_out_order_details")
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: scan package/product =====
    @http.route(
        "/api/barcode/scan_package",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def scan_package_or_product(self, **kwargs):
        """
        Scan package or product barcode.

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
            self._log_scan(
                barcode=barcode,
                scan_type=result.get("type") or "package",
                picking_id=picking.id,
                status=status,
                message=result.get("message") or result.get("error"),
            )

            # TẠM THỜI: không trả summary, để JS tự đếm trên client
            return result

        except Exception as e:
            _logger.exception("Error in scan_package_or_product")
            self._log_scan(
                barcode=barcode,
                scan_type="package",
                status="error",
                message=f"Lỗi hệ thống: {e}",
            )
            return {"success": False, "error": "Đã xảy ra lỗi hệ thống"}

    # ===== API: complete OUT (DONE) =====
    @http.route(
        "/api/barcode/complete_out",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def complete_out(self, **kwargs):
        """
        Call Odoo standard button_validate() để DONE phiếu OUT.

        Payload:
        { "picking_id": 123 }
        """
        try:
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            picking_id = data.get("picking_id")

            if not picking_id:
                return {"success": False, "error": "Thiếu Picking ID"}

            picking = request.env["stock.picking"].sudo().browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Không tìm thấy phiếu kho"}

            if picking.picking_type_id.code != "outgoing":
                return {
                    "success": False,
                    "error": "Chỉ có thể hoàn tất phiếu xuất kho (OUT) tại đây",
                }

            # GỌI LUỒNG CHUẨN – KHÔNG OVERRIDE GÌ CẢ
            picking.button_validate()

            self._log_scan(
                barcode=picking.name,
                scan_type="complete",
                picking_id=picking.id,
                status="success",
                message="Đơn hàng đã được Shipper hoàn tất",
            )

            return {
                "success": True,
                "message": f"Đơn hàng {picking.name} đã hoàn tất",
            }
        except Exception as e:
            _logger.exception("Error in complete_out")
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
            logs = log_obj.get_scan_history(
                picking_id=picking_id, user_id=request.env.user.id, limit=limit
            )

            history = []
            for log in logs:
                history.append(
                    {
                        "barcode": log.barcode,
                        "scan_type": log.scan_type,
                        "scan_time": log.scan_time.strftime(
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