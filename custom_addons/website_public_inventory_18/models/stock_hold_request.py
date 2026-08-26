# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .sale_plan_notify import notify_sale_plan_by_code

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
    partner_id = fields.Many2one(
        "res.partner", string="Khách hàng", required=True, tracking=True,
        help="Khách hàng dự kiến của lô hàng giữ này — dùng để khi giữ hàng bị hủy/hết hạn, hệ "
             "thống ưu tiên tự tìm đúng đơn bán của khách hàng này đang chờ hàng để giữ lại ngay.",
    )
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
            reject_message = _(
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
            }
            rec._notify_sale_zalo(reject_message)
            rec._notify_sale_plan(reject_message)

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
        try:
            self._reassign_freed_stock_to_waiting_orders()
        except Exception:
            _logger.exception(
                "Lỗi tự động giữ lại hàng vừa nhả cho đơn đang chờ (yêu cầu %s).", self.name,
            )

    def _reassign_freed_stock_to_waiting_orders(self):
        """Sau khi nhả reservation của yêu cầu giữ hàng, chủ động tìm đơn bán đang chờ hàng để
        giữ (action_assign) lại NGAY tại cùng kho — tránh trường hợp hàng đã có tồn nhưng đơn
        báo thiếu hàng chỉ vì chưa ai bấm giữ lại. Ưu tiên:
        1. Đơn của ĐÚNG khách hàng trên yêu cầu giữ hàng (partner_id) — đơn cũ nhất trước
           ("khách hàng đã giữ trước" được ưu tiên).
        2. Nếu không có đơn nào của khách đó, tìm bất kỳ đơn nào khác tại cùng kho đang chờ hàng
           (chưa lấy hàng) — cũng đơn cũ nhất trước.
        Hỗ trợ giữ cho NHIỀU đơn cùng lúc: gọi action_assign() tuần tự theo đúng thứ tự ưu tiên
        trên, Odoo sẽ tự chia số lượng còn khả dụng cho từng đơn theo đúng thứ tự gọi (đơn ở
        priority 1 luôn được ưu tiên phần tồn kho trước đơn ở priority 2)."""
        self.ensure_one()
        Picking = self.env["stock.picking"].sudo()
        base_domain = [
            ("sale_id", "!=", False),
            ("picking_type_id.warehouse_id", "=", self.warehouse_id.id),
            ("picking_type_id.sequence_code", "=", "PICK"),
            ("state", "in", ("waiting", "confirmed", "partially_available")),
            ("move_ids.product_id", "=", self.product_id.id),
        ]
        candidates = []
        if self.partner_id:
            customer_pickings = Picking.search(
                base_domain + [("sale_id.partner_id", "=", self.partner_id.id)],
                order="scheduled_date asc, id asc", limit=50,
            )
            candidates.extend(customer_pickings)
        else:
            customer_pickings = Picking.browse()
        other_pickings = Picking.search(
            base_domain + [("id", "not in", customer_pickings.ids)],
            order="scheduled_date asc, id asc", limit=50,
        )
        candidates.extend(other_pickings)

        for picking in candidates:
            try:
                picking.action_assign()
            except Exception:
                _logger.exception(
                    "Lỗi tự động giữ lại hàng cho phiếu %s (đơn %s) sau khi nhả yêu cầu giữ "
                    "hàng %s.", picking.name, picking.sale_id.name, self.name,
                )

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

    def _notify_sale_plan(self, message_text):
        """Báo thêm vào chuông thông báo trang /sale_plan (module hlv_sale_delivery_planning) —
        tra alias theo ĐÚNG sale_name (mã sale của chính yêu cầu này), KHÔNG dùng user_id (tài
        khoản đăng nhập tạo yêu cầu) vì 1 tài khoản có thể quản lý nhiều mã sale (trưởng nhóm) —
        đọc alias của tài khoản đó sẽ không biết chính xác yêu cầu này của ai trong số đó.
        Fire-and-forget, không ảnh hưởng luồng chính."""
        self.ensure_one()
        try:
            notify_sale_plan_by_code(
                self.env, self.sale_name, message_text, so=None, author_name="Kho hàng",
            )
        except Exception:
            _logger.exception(
                "Lỗi báo /sale_plan cho yêu cầu giữ hàng %s (mã sale=%s).",
                self.name, self.sale_name,
            )

    @api.model
    def _cron_expire_holds(self):
        today = fields.Date.context_today(self)
        expired = self.sudo().search([("state", "=", "approved"), ("hold_until_date", "<", today)])
        for rec in expired:
            rec._release()
            expire_message = _(
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
            }
            rec._notify_sale_zalo(expire_message)
            rec._notify_sale_plan(expire_message)
        expired.write({"state": "expired"})
