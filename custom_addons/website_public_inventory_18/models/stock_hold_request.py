# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

APPROVER_GROUP = "website_public_inventory_18.group_stock_hold_approver"


def _rg_sum(row, base):
    """read_group() key naming for ':sum' aggregates varies by field/version; check both forms."""
    v = row.get(f"{base}_sum")
    if v is None:
        v = row.get(base)
    return float(v or 0.0)


class StockHoldRequest(models.Model):
    _name = "stock.hold.request"
    _description = "Yêu cầu giữ hàng"
    _order = "create_date desc"

    name = fields.Char(
        string="Mã yêu cầu", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    product_id = fields.Many2one("product.product", string="Sản phẩm", required=True, tracking=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Kho hàng", required=True, tracking=True)
    quantity = fields.Float(string="Số lượng giữ", required=True)
    hold_until_date = fields.Date(string="Giữ đến ngày", required=True)
    project_name = fields.Char(string="Dự án", required=True)
    sale_name = fields.Char(string="Tên sale", required=True)
    user_id = fields.Many2one(
        "res.users", string="Người tạo", required=True, readonly=True,
        default=lambda self: self.env.user,
    )
    description = fields.Text(string="Mô tả")
    company_id = fields.Many2one(
        "res.company", string="Công ty", related="warehouse_id.company_id", store=True, readonly=True,
    )
    state = fields.Selection([
        ("draft", "Nháp"),
        ("pending_approval", "Chờ duyệt"),
        ("approved", "Đang giữ"),
        ("rejected", "Từ chối"),
        ("completed", "Hoàn thành"),
        ("cancelled", "Đã hủy"),
        ("expired", "Hết hạn"),
    ], string="Trạng thái", default="draft", required=True, tracking=True, copy=False)
    hold_picking_id = fields.Many2one("stock.picking", string="Phiếu giữ hàng", readonly=True, copy=False)
    approved_by_id = fields.Many2one("res.users", string="Người duyệt", readonly=True, copy=False)
    approved_date = fields.Datetime(string="Ngày duyệt", readonly=True, copy=False)
    reject_reason = fields.Text(string="Lý do từ chối", copy=False)
    hold_location_names = fields.Char(
        string="Vị trí đang giữ", compute="_compute_hold_location_names",
        help="Vị trí (bin) thực tế đang giữ hàng, lấy từ phiếu giữ hàng nội bộ — để sale biết "
             "hàng đang nằm ở đâu trong kho.",
    )
    hold_location_breakdown_json = fields.Char(
        string="Chi tiết vị trí đang giữ (JSON)", compute="_compute_hold_location_names",
        help="[{location, qty}, ...] — dùng để hiển thị dialog chi tiết trên trang public.",
    )

    @api.depends(
        "state", "hold_picking_id",
        "hold_picking_id.move_line_ids.location_id", "hold_picking_id.move_line_ids.quantity",
    )
    def _compute_hold_location_names(self):
        for rec in self:
            picking = rec.hold_picking_id.sudo() if rec.state == "approved" else False
            if picking:
                qty_by_loc = {}
                for ml in picking.move_line_ids:
                    loc_name = ml.location_id.display_name
                    qty_by_loc[loc_name] = qty_by_loc.get(loc_name, 0.0) + ml.quantity
                breakdown = [{"location": loc, "qty": qty} for loc, qty in sorted(qty_by_loc.items())]
                rec.hold_location_names = ", ".join(qty_by_loc.keys()) or False
                rec.hold_location_breakdown_json = json.dumps(breakdown)
            else:
                rec.hold_location_names = False
                rec.hold_location_breakdown_json = json.dumps([])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("stock.hold.request") or _("New")
        return super().create(vals_list)

    def _get_wh_qty(self):
        """Tồn thực tế & đã giữ tại kho, cùng công thức với controllers/main.py::_get_qty."""
        self.ensure_one()
        domain = [
            ("product_id", "=", self.product_id.id),
            ("location_id", "child_of", self.warehouse_id.view_location_id.id),
            ("location_id.usage", "=", "internal"),
        ]
        groups = self.env["stock.quant"].sudo().read_group(
            domain, ["quantity:sum", "reserved_quantity:sum"], [],
        )
        if not groups:
            return 0.0, 0.0
        g = groups[0]
        return _rg_sum(g, "quantity"), _rg_sum(g, "reserved_quantity")

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.warehouse_id.hold_requires_approval:
                rec.state = "pending_approval"
            else:
                rec._reserve()
                rec.state = "approved"

    def action_approve(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(_("Bạn không có quyền duyệt yêu cầu giữ hàng."))
        for rec in self:
            if rec.state != "pending_approval":
                continue
            rec._reserve()
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })

    def action_reject(self, reason=None):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(_("Bạn không có quyền từ chối yêu cầu giữ hàng."))
        for rec in self:
            if rec.state != "pending_approval":
                continue
            rec.write({"state": "rejected", "reject_reason": reason or rec.reject_reason})
            rec._notify_sale_zalo(_(
                "❌ YÊU CẦU GIỮ HÀNG BỊ TỪ CHỐI\n"
                "--------------------\n"
                "Mã yêu cầu: %(name)s\n"
                "Sản phẩm: %(product)s\n"
                "Kho: %(wh)s\n"
                "Số lượng: %(qty)s\n"
                "--------------------\n"
                "%(reason)s"
            ) % {
                "name": rec.name,
                "product": rec.product_id.display_name,
                "wh": rec.warehouse_id.display_name,
                "qty": "{:,.0f}".format(rec.quantity),
                "reason": (
                    _("Lý do: %s") % rec.reject_reason
                    if rec.reject_reason
                    else _("Vui lòng liên hệ kho để biết thêm chi tiết.")
                ),
            })

    def action_cancel(self):
        for rec in self:
            if rec.state in ("draft", "pending_approval", "approved"):
                if rec.state == "approved":
                    rec._release()
                rec.state = "cancelled"

    def action_complete(self):
        for rec in self:
            if rec.state == "approved":
                rec._release()
                rec.state = "completed"

    def _reserve(self):
        self.ensure_one()
        if self.quantity <= 0:
            raise UserError(_("Số lượng giữ phải lớn hơn 0."))

        qty_total, qty_reserved = self._get_wh_qty()
        qty_available = qty_total - qty_reserved
        if self.quantity > qty_available:
            raise UserError(_(
                "Số lượng yêu cầu (%(qty)s) vượt quá số lượng sẵn sàng hiện tại (%(avail)s) "
                "tại kho %(wh)s."
            ) % {
                "qty": self.quantity,
                "avail": qty_available,
                "wh": self.warehouse_id.display_name,
            })

        warehouse = self.warehouse_id.sudo()
        hold_location = warehouse._get_or_create_hold_location()
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": hold_location.id,
            "origin": self.name,
            "is_stock_hold_picking": True,
            "move_ids": [(0, 0, {
                "name": self.name,
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity,
                "product_uom": self.product_id.uom_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": hold_location.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()

        reserved_qty = sum(picking.move_line_ids.mapped("quantity"))
        if reserved_qty < self.quantity:
            picking.action_cancel()
            raise UserError(_(
                "Không đủ hàng sẵn sàng để giữ tại thời điểm này (có thể vừa bị đơn khác giữ "
                "trước). Vui lòng thử lại."
            ))
        self.hold_picking_id = picking.id

    def _release(self):
        self.ensure_one()
        if self.hold_picking_id and self.hold_picking_id.state not in ("cancel", "done"):
            self.hold_picking_id.sudo().action_cancel()

    def _notify_sale_zalo(self, message_text):
        """Gửi tin nhắn Zalo OA cho sale đứng tên yêu cầu, dùng map mã sale -> Zalo user_id
        RIÊNG cho hủy dự trữ/giữ hàng (hlv.zalo.stock.notification.hold_unreserve_saler_mapping_text)
        — KHÔNG dùng chung với saler_mapping_text (mapping đó dành cho thông báo phiếu XUẤT kho
        đã validate, hiện đã tạm ngừng dùng cho mục đích đó; dùng chung sẽ vô tình bật lại nó).
        Fire-and-forget: lỗi gửi chỉ log lại, không làm hỏng luồng nghiệp vụ chính (hủy/từ chối/
        hết hạn vẫn phải thành công dù Zalo có gửi được hay không)."""
        self.ensure_one()
        config = self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
        if not config:
            _logger.info("Không có cấu hình Zalo Stock Notification đang active, bỏ qua gửi báo cho %s.", self.name)
            return
        if not config.get_hold_unreserve_saler_user_ids_from_mapping(self.sale_name):
            _logger.info(
                "Không tìm thấy Zalo user_id cho sale_name=%s (yêu cầu %s) trong "
                "hold_unreserve_saler_mapping_text, bỏ qua.",
                self.sale_name, self.name,
            )
            return
        config.send_hold_unreserve_notification(self.sale_name, message_text)

    @api.model
    def _cron_expire_holds(self):
        today = fields.Date.context_today(self)
        expired = self.sudo().search([("state", "=", "approved"), ("hold_until_date", "<", today)])
        for rec in expired:
            rec._release()
            rec._notify_sale_zalo(_(
                "⏰ HẾT HẠN GIỮ HÀNG\n"
                "--------------------\n"
                "Mã yêu cầu: %(name)s\n"
                "Sản phẩm: %(product)s\n"
                "Kho: %(wh)s\n"
                "Số lượng: %(qty)s\n"
                "Giữ đến ngày: %(until)s\n"
                "--------------------\n"
                "Yêu cầu đã HẾT HẠN, hệ thống đã tự động HỦY giữ. Nếu vẫn cần giữ chỗ, vui lòng "
                "tạo lại yêu cầu giữ hàng mới trên trang tra cứu tồn kho."
            ) % {
                "name": rec.name,
                "product": rec.product_id.display_name,
                "wh": rec.warehouse_id.display_name,
                "qty": "{:,.0f}".format(rec.quantity),
                "until": rec.hold_until_date,
            })
        expired.write({"state": "expired"})
