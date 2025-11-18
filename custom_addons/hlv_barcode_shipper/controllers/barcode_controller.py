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
                "error": "Access denied. Shipper permissions required.",
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
        Scan PICK order barcode and find related OUT order.

        Payload:
        { "barcode": "PICK00001" }
        """
        barcode = ""
        try:
            # Check access
            access = self._check_shipper_access()
            if not access["success"]:
                return access

            data = json.loads(request.httprequest.data.decode("utf-8"))
            barcode = data.get("barcode", "").strip()

            if not barcode:
                return {"success": False, "error": "Barcode is required"}

            picking_obj = request.env["stock.picking"]
            out_picking = picking_obj.find_out_picking_by_pick_name(barcode)

            # Mark shipper scanned
            out_picking.mark_shipper_scanned()

            # Log
            self._log_scan(
                barcode=barcode,
                scan_type="pick",
                picking_id=out_picking.id,
                status="success",
                message=f"Found OUT order {out_picking.name}",
            )

            return {
                "success": True,
                "out_picking_id": out_picking.id,
                "out_picking_name": out_picking.name,
                "message": f"Found delivery order {out_picking.name}",
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
                message=f"System error: {e}",
            )
            return {"success": False, "error": "System error occurred"}

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
                return {"success": False, "error": "Picking ID is required"}

            picking = request.env["stock.picking"].browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Picking not found"}

            items = picking.get_packages_info()
            total = len(items)
            scanned = len([i for i in items if i.get("scanned")])
            all_scanned = total > 0 and scanned == total

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
                    "scanned_items": scanned,
                    "all_scanned": all_scanned,
                },
            }
        except Exception as e:
            _logger.exception("Error in get_out_order_details")
            return {"success": False, "error": "System error occurred"}

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
                    "error": "Picking ID and barcode are required",
                }

            picking = request.env["stock.picking"].browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Picking not found"}

            # Thực hiện logic ở model
            result = picking.scan_package_or_product(barcode)

            status = "success" if result.get("success") else "error"
            self._log_scan(
                barcode=barcode,
                scan_type=result.get("type") or "package",
                picking_id=picking.id,
                status=status,
                message=result.get("message") or result.get("error"),
            )

            # Tính lại summary
            items = picking.get_packages_info()
            total = len(items)
            scanned = len([i for i in items if i.get("scanned")])
            all_scanned = total > 0 and scanned == total

            if result.get("success"):
                result.update(
                    {
                        "summary": {
                            "total_items": total,
                            "scanned_items": scanned,
                            "all_scanned": all_scanned,
                        }
                    }
                )
            return result
        except Exception as e:
            _logger.exception("Error in scan_package_or_product")
            self._log_scan(
                barcode=barcode,
                scan_type="package",
                status="error",
                message=f"System error: {e}",
            )
            return {"success": False, "error": "System error occurred"}

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
                return {"success": False, "error": "Picking ID is required"}

            picking = request.env["stock.picking"].browse(picking_id)
            if not picking.exists():
                return {"success": False, "error": "Picking not found"}

            if picking.picking_type_id.code != "outgoing":
                return {
                    "success": False,
                    "error": "Only OUT pickings can be completed here",
                }

            # Gọi luồng chuẩn Odoo, dùng sudo để shipper không cần quyền validate
            picking.sudo().button_validate()

            self._log_scan(
                barcode=picking.name,
                scan_type="complete",
                picking_id=picking.id,
                status="success",
                message="Picking completed by shipper",
            )

            return {
                "success": True,
                "message": f"Delivery {picking.name} completed",
            }
        except Exception as e:
            _logger.exception("Error in complete_out")
            return {"success": False, "error": "System error occurred"}

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
            return {"success": False, "error": "System error occurred"}

    # ===== Web UI: /barcode/shipper =====
    @http.route("/barcode/shipper", type="http", auth="user", website=False)
    def shipper_interface(self, **kwargs):
        """Main shipper interface page."""
        if not request.env.user.has_group("hlv_barcode_shipper.group_shipper"):
            return request.render("hlv_barcode_shipper.access_denied", {"user": request.env.user})
        return request.render("hlv_barcode_shipper.shipper_interface", {"user": request.env.user})
