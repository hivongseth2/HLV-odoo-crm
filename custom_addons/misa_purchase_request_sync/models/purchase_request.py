# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Mở rộng `purchase.request` để:
1. Cung cấp nút "Đẩy sang MISA CRM" trên form (stub TODO).
2. Cung cấp helper `_prepare_misa_user(owner_text)` được controller dùng
   khi tạo PR từ Browser Extension.
"""

import logging
import re

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
