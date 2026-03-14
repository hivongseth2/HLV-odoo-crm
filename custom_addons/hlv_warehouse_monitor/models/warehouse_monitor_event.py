import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WarehouseMonitorEvent(models.Model):
    _name = "warehouse.monitor.event"
    _description = "Warehouse Monitor Event"
    _order = "timestamp desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Sự kiện",
        required=True,
        readonly=True,
    )
    event_type = fields.Selection(
        [
            ("sale", "Bán hàng"),
            ("purchase", "Mua hàng"),
            ("pick", "Lấy hàng (PICK)"),
            ("pack", "Đóng gói (PACK)"),
            ("out", "Xuất kho (OUT)"),
            ("in", "Nhập kho (IN)"),
            ("internal", "Chuyển nội bộ"),
            ("inventory", "Kiểm kê"),
            ("return", "Trả hàng"),
        ],
        string="Loại sự kiện",
        required=True,
        readonly=True,
        index=True,
    )
    action = fields.Selection(
        [
            ("create", "Tạo mới"),
            ("confirm", "Xác nhận"),
            ("assign", "Sẵn sàng / Dự trữ"),
            ("validate", "Hoàn thành"),
            ("cancel", "Hủy"),
            ("return", "Trả hàng"),
            ("update", "Cập nhật"),
        ],
        string="Hành động",
        required=True,
        readonly=True,
        index=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Kho",
        readonly=True,
        index=True,
    )
    picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu kho",
        readonly=True,
        ondelete="set null",
    )
    sale_id = fields.Many2one(
        "sale.order",
        string="Đơn bán hàng",
        readonly=True,
        ondelete="set null",
    )
    purchase_id = fields.Many2one(
        "purchase.order",
        string="Đơn mua hàng",
        readonly=True,
        ondelete="set null",
    )
    origin = fields.Char(
        string="Chứng từ gốc",
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Người thực hiện",
        default=lambda self: self.env.user,
        readonly=True,
    )
    timestamp = fields.Datetime(
        string="Thời gian",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
        index=True,
    )
    state_before = fields.Char(
        string="Trạng thái trước",
        readonly=True,
    )
    state_after = fields.Char(
        string="Trạng thái sau",
        readonly=True,
    )
    summary = fields.Text(
        string="Tóm tắt",
        readonly=True,
    )
    suggestion = fields.Text(
        string="Đề xuất",
        readonly=True,
    )
    priority = fields.Selection(
        [
            ("low", "Thấp"),
            ("medium", "Trung bình"),
            ("high", "Cao"),
            ("urgent", "Khẩn cấp"),
        ],
        string="Độ ưu tiên",
        default="medium",
        readonly=True,
        index=True,
    )
    is_read = fields.Boolean(
        string="Đã xem",
        default=False,
    )
    is_suggestion = fields.Boolean(
        string="Có đề xuất",
        compute="_compute_is_suggestion",
        store=True,
    )
    product_summary = fields.Text(
        string="Sản phẩm liên quan",
        readonly=True,
        help="JSON danh sách sản phẩm liên quan",
    )
    picking_type_code = fields.Char(
        string="Mã loại phiếu",
        readonly=True,
    )

    @api.depends("suggestion")
    def _compute_is_suggestion(self):
        for rec in self:
            rec.is_suggestion = bool(rec.suggestion)

    def action_mark_read(self):
        self.write({"is_read": True})

    def action_mark_unread(self):
        self.write({"is_read": False})

    def action_open_picking(self):
        self.ensure_one()
        if self.picking_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "res_id": self.picking_id.id,
                "view_mode": "form",
                "target": "current",
            }

    def action_open_sale(self):
        self.ensure_one()
        if self.sale_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "sale.order",
                "res_id": self.sale_id.id,
                "view_mode": "form",
                "target": "current",
            }

    def action_open_purchase(self):
        self.ensure_one()
        if self.purchase_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "purchase.order",
                "res_id": self.purchase_id.id,
                "view_mode": "form",
                "target": "current",
            }

    # ── Helper: create event from hooks ──────────────────────────
    @api.model
    def _log_event(self, vals):
        """Central method called by all hooks to create monitor events."""
        try:
            return self.sudo().create(vals)
        except Exception:
            _logger.exception("[HLV Monitor] Failed to log event: %s", vals.get("name", ""))
            return self.browse()

    # ── Dashboard RPC methods ────────────────────────────────────
    @api.model
    def get_monitor_dashboard_data(self, warehouse_id=None, date_from=None, date_to=None,
                                   event_type=None, limit=50, offset=0):
        """Return dashboard data for OWL frontend."""
        domain = []
        if warehouse_id and warehouse_id != "all":
            domain.append(("warehouse_id", "=", int(warehouse_id)))
        if date_from:
            domain.append(("timestamp", ">=", date_from))
        if date_to:
            domain.append(("timestamp", "<=", date_to))
        if event_type and event_type != "all":
            domain.append(("event_type", "=", event_type))

        events = self.search(domain, limit=limit, offset=offset, order="timestamp desc")
        total_count = self.search_count(domain)

        # KPI counts (today)
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_domain = domain + [("timestamp", ">=", today_start)]

        kpi = {
            "total_events_today": self.search_count(today_domain),
            "in_today": self.search_count(today_domain + [("event_type", "=", "in")]),
            "out_today": self.search_count(today_domain + [("event_type", "=", "out")]),
            "pick_today": self.search_count(today_domain + [("event_type", "=", "pick")]),
            "pack_today": self.search_count(today_domain + [("event_type", "=", "pack")]),
            "sale_today": self.search_count(today_domain + [("event_type", "=", "sale")]),
            "purchase_today": self.search_count(today_domain + [("event_type", "=", "purchase")]),
            "suggestions_pending": self.search_count(
                domain + [("is_suggestion", "=", True), ("is_read", "=", False)]
            ),
        }

        # Format events
        event_list = []
        for ev in events:
            event_list.append({
                "id": ev.id,
                "name": ev.name,
                "event_type": ev.event_type,
                "action": ev.action,
                "warehouse_id": ev.warehouse_id.id if ev.warehouse_id else False,
                "warehouse_name": ev.warehouse_id.name if ev.warehouse_id else "",
                "picking_id": ev.picking_id.id if ev.picking_id else False,
                "picking_name": ev.picking_id.name if ev.picking_id else "",
                "sale_id": ev.sale_id.id if ev.sale_id else False,
                "sale_name": ev.sale_id.name if ev.sale_id else "",
                "purchase_id": ev.purchase_id.id if ev.purchase_id else False,
                "purchase_name": ev.purchase_id.name if ev.purchase_id else "",
                "origin": ev.origin or "",
                "user_name": ev.user_id.name if ev.user_id else "",
                "timestamp": fields.Datetime.to_string(ev.timestamp),
                "state_before": ev.state_before or "",
                "state_after": ev.state_after or "",
                "summary": ev.summary or "",
                "suggestion": ev.suggestion or "",
                "priority": ev.priority,
                "is_read": ev.is_read,
                "is_suggestion": ev.is_suggestion,
                "picking_type_code": ev.picking_type_code or "",
            })

        # Pending suggestions
        suggestions = self.search(
            domain + [("is_suggestion", "=", True), ("is_read", "=", False)],
            limit=20,
            order="priority desc, timestamp desc",
        )
        suggestion_list = []
        for s in suggestions:
            suggestion_list.append({
                "id": s.id,
                "name": s.name,
                "suggestion": s.suggestion,
                "priority": s.priority,
                "origin": s.origin or "",
                "timestamp": fields.Datetime.to_string(s.timestamp),
                "picking_name": s.picking_id.name if s.picking_id else "",
                "sale_name": s.sale_id.name if s.sale_id else "",
                "purchase_name": s.purchase_id.name if s.purchase_id else "",
            })

        # Warehouses list for filter
        warehouses = self.env["stock.warehouse"].search([])
        warehouse_list = [{"id": w.id, "name": w.name} for w in warehouses]

        return {
            "events": event_list,
            "total_count": total_count,
            "kpi": kpi,
            "suggestions": suggestion_list,
            "warehouses": warehouse_list,
        }

    @api.model
    def mark_events_read(self, event_ids):
        """Mark multiple events as read."""
        events = self.browse(event_ids)
        events.write({"is_read": True})
        return True

    @api.model
    def dismiss_suggestion(self, event_id):
        """Dismiss a suggestion by marking it read."""
        event = self.browse(event_id)
        if event.exists():
            event.write({"is_read": True})
        return True
