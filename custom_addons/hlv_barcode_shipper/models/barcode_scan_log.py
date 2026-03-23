# hlv_barcode_shipper/models/barcode_scan_log.py
# -*- coding: utf-8 -*-

from odoo import models, fields, api


class BarcodeScanLog(models.Model):
    _name = "barcode.scan.log"
    _description = "Barcode Scan Log"
    _order = "scan_time desc"
    _rec_name = "barcode"

    barcode = fields.Char(
        string="Barcode",
        required=True,
        help="Scanned barcode value",
    )

    scan_type = fields.Selection(
        [
            ("pick", "Quét phiếu PICK"),
            ("package", "Quét kiện hàng"),
            ("product", "Quét sản phẩm"),
            ("complete", "Hoàn thành đơn"),
            ("receive", "Nhận hàng"),
            ("return", "Trả hàng"),
        ],
        string="Loại quét",
        required=True,
    )

    scan_time = fields.Datetime(
        string="Scan Time",
        default=fields.Datetime.now,
        required=True,
    )

    user_id = fields.Many2one(
        "res.users",
        string="Scanned By",
        default=lambda self: self.env.user,
        required=True,
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Related Picking",
        help="Related stock picking record",
    )

    package_id = fields.Many2one(
        "stock.quant.package",
        string="Package",
        help="Related package if scanning package",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        help="Related product if scanning product",
    )

    status = fields.Selection(
        [("success", "Success"), ("error", "Error"), ("warning", "Warning")],
        string="Status",
        default="success",
    )

    message = fields.Text(
        string="Message",
        help="Additional information or error message",
    )

    session_id = fields.Char(
        string="Session ID",
        help="Session identifier for grouping related scans",
    )

    @api.model
    def log_scan(
        self,
        barcode,
        scan_type,
        picking_id=None,
        package_id=None,
        product_id=None,
        status="success",
        message=None,
        session_id=None,
    ):
        """Create a scan log entry (sudo để shipper không cần quyền write)."""
        vals = {
            "barcode": barcode,
            "scan_type": scan_type,
            "status": status,
            "message": message,
            "session_id": session_id,
            "user_id": self.env.user.id,
        }
        if picking_id:
            vals["picking_id"] = picking_id
        if package_id:
            vals["package_id"] = package_id
        if product_id:
            vals["product_id"] = product_id

        return self.sudo().create(vals)

    @api.model
    def get_scan_history(self, picking_id=None, user_id=None, limit=50):
        """Get scan history with optional filters."""
        domain = []
        if picking_id:
            domain.append(("picking_id", "=", picking_id))
        if user_id:
            domain.append(("user_id", "=", user_id))

        return self.search(domain, limit=limit)
