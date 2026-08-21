# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    is_stock_hold_picking = fields.Boolean(
        string="Phiếu giữ hàng (Giữ hàng theo Sale)",
        default=False,
        copy=False,
        help=(
            "Phiếu chuyển kho nội bộ này được tạo tự động bởi tính năng Giữ hàng theo Sale "
            "(trang /search_stock) để khóa chỗ hàng — KHÔNG đại diện cho một lần chuyển hàng "
            "thật. Không được xác nhận/hoàn tất (validate) phiếu này."
        ),
    )

    def button_validate(self):
        blocked = self.filtered("is_stock_hold_picking")
        if blocked:
            raise UserError(_(
                "Đây là phiếu giữ chỗ (do tính năng Giữ hàng theo Sale tạo ra), không phải phiếu "
                "chuyển hàng thật — KHÔNG được xác nhận/hoàn tất phiếu này. Nếu hoàn tất, hệ thống "
                "sẽ di chuyển hàng thật sang vị trí ảo 'Giữ hàng chờ đơn', làm mất vị trí tồn kho "
                "thực tế và làm hàng bị giữ mất luôn tác dụng khóa (không còn giảm 'Sẵn sàng' nữa).\n\n"
                "Hãy vào menu Kho hàng > Giữ hàng theo Sale, mở yêu cầu tương ứng (%s) và bấm "
                "'Hoàn thành' (khi đã lên đơn/báo giá xong) hoặc 'Hủy' (khi không cần giữ nữa)."
            ) % ", ".join(blocked.mapped("origin")))
        return super().button_validate()

    def action_cancel(self):
        res = super().action_cancel()
        holds = self.env["stock.hold.request"].sudo().search([
            ("hold_picking_id", "in", self.ids),
            ("state", "=", "approved"),
        ])
        holds.write({"state": "cancelled"})
        return res
