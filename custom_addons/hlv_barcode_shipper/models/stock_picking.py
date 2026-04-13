# hlv_barcode_shipper/models/stock_picking.py
# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    shipper_scanned = fields.Boolean(
        string="Shipper Scanned",
        default=False,
        help="Indicates if this picking has been scanned by shipper",
    )

    shipper_scan_time = fields.Datetime(
        string="Shipper Scan Time",
        help="When the shipper first scanned this picking",
    )

    shipper_user_id = fields.Many2one(
        "res.users", string="Shipper", help="User who scanned this picking"
    )

    # === Receive fields ===
    shipper_received = fields.Boolean(
        string="Shipper Received",
        default=False,
        help="Shipper confirmed receiving this picking for delivery",
    )
    shipper_receive_time = fields.Datetime(
        string="Receive Time",
        help="When the shipper confirmed receiving this picking",
    )
    shipper_received_by = fields.Many2one(
        "res.users",
        string="Received By",
        help="Shipper who received this picking",
    )

    # === Return fields ===
    shipper_returned = fields.Boolean(
        string="Shipper Returned",
        default=False,
        help="Shipper returned this picking back to warehouse",
    )
    shipper_return_time = fields.Datetime(
        string="Return Time",
        help="When the shipper returned this picking",
    )
    shipper_return_reason = fields.Char(
        string="Return Reason",
        help="Reason for returning this picking",
    )

    scan_log_ids = fields.One2many(
        "barcode.scan.log",
        "picking_id",
        string="Scan Logs",
        help="Barcode scan logs for this picking",
    )

    # === Helper: tìm phiếu OUT từ PICK ===
    @api.model
    def find_out_picking_by_pick_name(self, pick_name):
        """
        Find OUT picking related to PICK order name.

        Logic: PICK (internal transfer) -> liên kết qua origin / sale_id / group_id
        """
        # 1) Tìm phiếu PICK
        pick_picking = self.search(
            [("name", "=", pick_name), ("picking_type_id.code", "=", "internal")],
            limit=1,
        )
        if not pick_picking:
            # fallback ilike
            pick_picking = self.search(
                [("name", "ilike", pick_name)], limit=1
            )

        if not pick_picking:
            raise UserError(f"PICK order {pick_name} not found")

        # 2) Tìm phiếu OUT liên quan
        out_picking = False

        # qua origin
        if pick_picking.origin:
            out_picking = self.search(
                [
                    ("origin", "=", pick_picking.origin),
                    ("picking_type_id.code", "=", "outgoing"),
                    ("state", "in", ["assigned", "partially_available"]),
                ],
                limit=1,
            )

        # qua sale_id
        if not out_picking and pick_picking.sale_id:
            out_picking = self.search(
                [
                    ("sale_id", "=", pick_picking.sale_id.id),
                    ("picking_type_id.code", "=", "outgoing"),
                    ("state", "in", ["assigned", "partially_available"]),
                ],
                limit=1,
            )

        # qua procurement group
        if not out_picking and pick_picking.group_id:
            out_picking = self.search(
                [
                    ("group_id", "=", pick_picking.group_id.id),
                    ("picking_type_id.code", "=", "outgoing"),
                    ("state", "in", ["assigned", "partially_available"]),
                ],
                limit=1,
            )

        if not out_picking:
            raise UserError(f"No related OUT order found for PICK {pick_name}")

        return out_picking

    def mark_shipper_scanned(self, user_id=None):
        """Đánh dấu phiếu đã được shipper quét (sudo để không vướng quyền)."""
        self.ensure_one()
        self.sudo().write(
            {
                "shipper_scanned": True,
                "shipper_scan_time": fields.Datetime.now(),
                "shipper_user_id": user_id or self.env.user.id,
            }
        )

    # === Dữ liệu đưa ra mobile ===
    def get_packages_info(self):
        """
        Trả về list packages hoặc products để hiển thị trên mobile.
        KHÔNG đụng gì tới workflow Odoo chuẩn.
        """
        self.ensure_one()
        packages_info = []

        if self.package_level_ids:
            # Có kiện PACK
            for package_level in self.package_level_ids:
                packages_info.append(
                    {
                        "id": package_level.id,
                        "name": package_level.package_id.name,
                        "barcode": package_level.package_id.name,  # giả định name = barcode
                        "scanned": bool(package_level.scanned),
                        "type": "package",
                    }
                )
        else:
            # Không có PACK -> dùng từng dòng move line
            for move_line in self.move_line_ids:
                packages_info.append(
                    {
                        "id": move_line.id,
                        "name": move_line.product_id.display_name,
                        "barcode": move_line.product_id.barcode
                        or move_line.product_id.default_code,
                        "scanned": bool(getattr(move_line, "scanned", False)),
                        "qty": move_line.quantity,
                        "type": "product",
                    }
                )

        return packages_info

    def scan_package_or_product(self, barcode):
        """
        Đánh dấu 1 kiện hoặc 1 dòng move line là đã scan.
        Không chặn validate, không sửa stock.move.
        """
        self.ensure_one()

        # Ưu tiên tìm package theo name (PACKxxx)
        package_level = self.package_level_ids.filtered(
            lambda pl: pl.package_id.name == barcode
        )
        if package_level:
            package_level.mark_scanned()
            return {
                "success": True,
                "type": "package",
                "name": package_level.package_id.name,
                "message": f"Package {barcode} scanned successfully",
            }

        # Nếu không có package, tìm product theo barcode hoặc default_code
        move_line = self.move_line_ids.filtered(
            lambda ml: ml.product_id.barcode == barcode
            or ml.product_id.default_code == barcode
        )
        if move_line:
            # nếu nhiều dòng trùng thì đánh dấu tất cả
            for ml in move_line:
                ml.mark_scanned()
            return {
                "success": True,
                "type": "product",
                "name": move_line[0].product_id.display_name,
                "message": f"Product {barcode} scanned successfully",
            }

        # Không tìm thấy
        return {
            "success": False,
            "error": f"Barcode {barcode} not found in this picking",
        }
