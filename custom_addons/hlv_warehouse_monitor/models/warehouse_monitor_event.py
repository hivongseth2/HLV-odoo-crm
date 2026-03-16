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
        # Use sudo for read-only dashboard access — any logged-in user can view
        ME = self.sudo()
        domain = []
        if warehouse_id and warehouse_id != "all":
            domain.append(("warehouse_id", "=", int(warehouse_id)))
        if date_from:
            domain.append(("timestamp", ">=", date_from))
        if date_to:
            domain.append(("timestamp", "<=", date_to))
        if event_type and event_type != "all":
            domain.append(("event_type", "=", event_type))

        events = ME.search(domain, limit=limit, offset=offset, order="timestamp desc")
        total_count = ME.search_count(domain)

        # ── Live KPI from actual models (not event log) ──────────
        # This ensures data is available even before the event log is populated
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        SP = self.env["stock.picking"].sudo()
        SO = self.env["sale.order"].sudo()
        PO = self.env["purchase.order"].sudo()

        wh_picking_filter = []
        if warehouse_id and warehouse_id != "all":
            wh_picking_filter = [("picking_type_id.warehouse_id", "=", int(warehouse_id))]
        wh_sale_filter = []
        if warehouse_id and warehouse_id != "all":
            wh_sale_filter = [("warehouse_id", "=", int(warehouse_id))]

        # Count active pickings per type (in progress, not done/cancel)
        active_states = ["confirmed", "assigned"]
        pick_active = SP.search_count(
            wh_picking_filter + [("picking_type_id.sequence_code", "ilike", "PICK"),
                                  ("state", "in", active_states)]
        )
        pack_active = SP.search_count(
            wh_picking_filter + [("picking_type_id.sequence_code", "ilike", "PACK"),
                                  ("state", "in", active_states)]
        )
        # Count validated today
        out_done_today = SP.search_count(
            wh_picking_filter + [("picking_type_code", "=", "outgoing"),
                                  ("state", "=", "done"),
                                  ("date_done", ">=", today_start)]
        )
        in_done_today = SP.search_count(
            wh_picking_filter + [("picking_type_code", "=", "incoming"),
                                  ("state", "=", "done"),
                                  ("date_done", ">=", today_start)]
        )
        # Sales confirmed today
        sale_today = SO.search_count(
            wh_sale_filter + [("state", "in", ["sale", "done"]),
                              ("date_order", ">=", today_start)]
        )
        # POs confirmed today
        po_today = PO.search_count(
            [("state", "in", ["purchase", "done"]),
             ("date_approve", ">=", today_start)]
        )
        suggestions_pending = ME.search_count(
            domain + [("is_suggestion", "=", True), ("is_read", "=", False)]
        )

        kpi = {
            "total_events_today": pick_active + pack_active + out_done_today + in_done_today,
            "in_today": in_done_today,
            "out_today": out_done_today,
            "pick_today": pick_active,
            "pack_today": pack_active,
            "sale_today": sale_today,
            "purchase_today": po_today,
            "suggestions_pending": suggestions_pending,
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
        suggestions = ME.search(
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
        warehouses = self.env["stock.warehouse"].sudo().search([])
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
        self.browse(event_ids).sudo().write({"is_read": True})
        return True

    @api.model
    def dismiss_suggestion(self, event_id):
        """Dismiss a suggestion by marking it read."""
        event = self.sudo().browse(event_id)
        if event.exists():
            event.write({"is_read": True})
        return True

    # ── Queue Screen RPC ─────────────────────────────────────────
    @api.model
    def get_queue_screen_data(self, warehouse_id=None):
        """Return PICK and PACK active queues for the hospital-style queue screen."""
        PickingType = self.env["stock.picking.type"].sudo()
        StockPicking = self.env["stock.picking"].sudo()

        # Resolve warehouse filter
        wh_filter = []
        if warehouse_id and warehouse_id != "all":
            wh_filter = [("warehouse_id", "=", int(warehouse_id))]

        # Find PICK picking types
        pick_types = PickingType.search(
            [("sequence_code", "ilike", "PICK"), ("active", "=", True)] + wh_filter
        )
        # Find PACK picking types
        pack_types = PickingType.search(
            [("sequence_code", "ilike", "PACK"), ("active", "=", True)] + wh_filter
        )

        def _compute_display_priority(p):
            """Smart priority: overdue > user-urgent+ready > ready > waiting.
            Odoo default sets all SO-picking priority to '1', so we only honor
            priority='1' when the picking is also assigned (ready). A confirmed
            (waiting stock) picking is never shown as urgent.
            """
            now = fields.Datetime.now()
            is_overdue = p.scheduled_date and p.scheduled_date < now
            is_assigned = p.state == "assigned"
            user_marked_urgent = p.priority == "1"

            if is_overdue:
                return "overdue"        # Trễ hạn — màu đỏ pulse
            if user_marked_urgent and is_assigned:
                return "urgent"         # Được đánh dấu khẩn + sẵn sàng — cam
            if is_assigned:
                return "ready"          # Sẵn sàng lấy — xanh
            return "waiting"            # Chờ hàng về — vàng

        def _format_pickings(pickings):
            result = []
            for p in pickings:
                so = None
                if hasattr(p, "sale_id") and p.sale_id:
                    so = p.sale_id
                if not so and p.group_id and hasattr(p.group_id, "sale_id"):
                    so = p.group_id.sale_id

                product_names = []
                for move in p.move_ids[:5]:
                    product_names.append(
                        "%s x%g" % (move.product_id.display_name, move.product_uom_qty)
                    )
                if len(p.move_ids) > 5:
                    product_names.append("... +%d" % (len(p.move_ids) - 5))

                result.append({
                    "id": p.id,
                    "name": p.name,
                    "origin": p.origin or "",
                    "partner_name": p.partner_id.name if p.partner_id else "",
                    "state": p.state,
                    "computed_priority": _compute_display_priority(p),
                    "scheduled_date": fields.Datetime.to_string(p.scheduled_date) if p.scheduled_date else "",
                    "move_count": len(p.move_ids),
                    "warehouse_name": (
                        p.picking_type_id.warehouse_id.name
                        if p.picking_type_id and p.picking_type_id.warehouse_id
                        else ""
                    ),
                    "sale_name": so.name if so else "",
                    "picking_type_name": p.picking_type_id.name if p.picking_type_id else "",
                    "products": product_names,
                })
            return result

        # Active PICK queue: confirmed + assigned, ordered urgent first then oldest
        pick_domain = [("state", "in", ["confirmed", "assigned"])]
        if pick_types:
            pick_domain.append(("picking_type_id", "in", pick_types.ids))
        else:
            # Fallback: outgoing internal with PICK in name
            pick_domain.append(("picking_type_id.sequence_code", "ilike", "PICK"))
        pick_pickings = StockPicking.search(
            pick_domain, order="scheduled_date asc", limit=50
        )

        # Active PACK queue
        pack_domain = [("state", "in", ["confirmed", "assigned"])]
        if pack_types:
            pack_domain.append(("picking_type_id", "in", pack_types.ids))
        else:
            pack_domain.append(("picking_type_id.sequence_code", "ilike", "PACK"))
        pack_pickings = StockPicking.search(
            pack_domain, order="scheduled_date asc", limit=50
        )

        warehouses = self.env["stock.warehouse"].sudo().search([])
        return {
            "pick_queue": _format_pickings(pick_pickings),
            "pack_queue": _format_pickings(pack_pickings),
            "warehouses": [{"id": w.id, "name": w.name} for w in warehouses],
            "pick_count": len(pick_pickings),
            "pack_count": len(pack_pickings),
        }
