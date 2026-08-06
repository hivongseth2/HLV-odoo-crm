# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Computed fields tổng hợp từ picking_ids để đảm bảo 100% tương thích REST API cũ
    x_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả",
        compute="_compute_zalo_return_summary",
        search="_search_x_return_requested",
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả cho ít nhất 1 phiếu giao hàng",
    )

    x_return_state = fields.Selection(
        [
            ("pending", "Chờ duyệt"),
            ("approved", "Đã duyệt"),
            ("processing", "Đang xử lý"),
            ("completed", "Hoàn tất"),
            ("rejected", "Từ chối"),
        ],
        string="Trạng thái đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Trạng thái tổng hợp của các phiếu đổi/trả thuộc đơn Zalo",
    )

    x_return_type = fields.Selection(
        [
            ("return", "Trả hàng hoàn tiền"),
            ("exchange", "Đổi hàng"),
            ("refund", "Hoàn tiền một phần"),
        ],
        string="Loại đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Phân loại đổi/trả của phiếu xuất kho Zalo",
    )

    x_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu trả hàng",
        compute="_compute_zalo_return_summary",
        help="Phiếu nhập kho trả hàng (WH/IN) mới nhất từ phiếu xuất kho Zalo",
    )

    x_return_refund_amount = fields.Float(
        string="Số tiền hoàn lại",
        compute="_compute_zalo_return_summary",
        help="Tổng số tiền hoàn lại của các phiếu kho Zalo",
    )

    x_return_rejected_reason = fields.Text(
        string="Lý do từ chối",
        compute="_compute_zalo_return_summary",
        help="Lý do từ chối yêu cầu đổi/trả Zalo",
    )

    x_return_completed_date = fields.Datetime(
        string="Ngày hoàn tất đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Thời điểm hoàn tất xử lý đổi/trả gần nhất",
    )

    x_return_picking_count = fields.Integer(
        string="Số phiếu đổi/trả",
        compute="_compute_zalo_return_summary",
    )

    @api.depends(
        "picking_ids.x_zalo_return_requested",
        "picking_ids.x_zalo_return_state",
        "picking_ids.x_zalo_return_type",
        "picking_ids.x_zalo_return_refund_amount",
        "picking_ids.x_zalo_return_picking_id",
        "picking_ids.x_zalo_return_rejected_reason",
        "picking_ids.x_zalo_return_completed_date",
    )
    def _compute_zalo_return_summary(self):
        for order in self:
            return_pickings = order.picking_ids.filtered(lambda p: p.x_zalo_return_requested)
            order.x_return_requested = bool(return_pickings)
            order.x_return_picking_count = len(return_pickings)

            if not return_pickings:
                order.x_return_state = False
                order.x_return_type = False
                order.x_return_picking_id = False
                order.x_return_refund_amount = 0.0
                order.x_return_rejected_reason = False
                order.x_return_completed_date = False
                continue

            # Tính toán x_return_state tổng hợp:
            # Ưu tiên: pending -> approved -> processing -> completed -> rejected
            states = return_pickings.mapped("x_zalo_return_state")
            if "pending" in states:
                order.x_return_state = "pending"
            elif "approved" in states:
                order.x_return_state = "approved"
            elif "processing" in states:
                order.x_return_state = "processing"
            elif "completed" in states:
                order.x_return_state = "completed"
            elif "rejected" in states:
                order.x_return_state = "rejected"
            else:
                order.x_return_state = "pending"

            latest = return_pickings[0]
            order.x_return_type = latest.x_zalo_return_type

            valid_return_pickings = return_pickings.filtered(lambda p: p.x_zalo_return_picking_id)
            order.x_return_picking_id = valid_return_pickings[0].x_zalo_return_picking_id if valid_return_pickings else False

            order.x_return_refund_amount = sum(return_pickings.mapped("x_zalo_return_refund_amount"))

            reasons = [r for r in return_pickings.mapped("x_zalo_return_rejected_reason") if r]
            order.x_return_rejected_reason = "\n".join(reasons) if reasons else False

            completed_dates = [d for d in return_pickings.mapped("x_zalo_return_completed_date") if d]
            order.x_return_completed_date = max(completed_dates) if completed_dates else False

    def _search_x_return_requested(self, operator, value):
        if operator in ("=", "!=") and isinstance(value, bool):
            if (operator == "=" and value) or (operator == "!=" and not value):
                return [("picking_ids.x_zalo_return_requested", "=", True)]
            else:
                return [("picking_ids.x_zalo_return_requested", "=", False)]
        return []

    def _is_zalo_order(self):
        """Kiểm tra đơn hàng có phải từ Zalo Mini App không."""
        self.ensure_one()
        return bool(self.partner_id.x_is_zalo_account)

    def action_view_zalo_return_pickings(self):
        """Smart button xem danh sách các phiếu xuất kho Zalo có yêu cầu đổi/trả."""
        self.ensure_one()
        action = self.env.ref("stock.action_picking_tree_all").read()[0]
        return_pickings = self.picking_ids.filtered(lambda p: p.x_zalo_return_requested)
        action["domain"] = [("id", "in", return_pickings.ids)]
        action["context"] = {"default_sale_id": self.id}
        return action

