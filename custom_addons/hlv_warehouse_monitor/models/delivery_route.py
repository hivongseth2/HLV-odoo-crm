# -*- coding: utf-8 -*-
"""
Persistent Delivery Route Board  (Phase 2b — hlv_warehouse_monitor)

wm.delivery.route      : a planned delivery trip (province + date + vehicle type)
wm.delivery.route.line : a sale.order assigned to a route

Lifecycle:
  1. `wm.delivery.route.rebuild_routes(warehouse_id)` — called from UI "Xây dựng tuyến"
     Groups active SOs by province + deadline + vehicle type.
     Creates / updates route + line records.

  2. `stock.picking.button_validate()` (incoming) — after PO receipt done
     Calls `refresh_line_states_for_sos()` to push waiting lines → ready.
     Sets `has_new_stock = True` on affected routes.

  3. Frontend polls `wm.delivery.route.get_board(warehouse_id)` every 30 s.
     After read the `has_new_stock` flag is cleared automatically.
"""
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# ── Vehicle cap constants (mirrors delivery_planner.py) ──────────────────────
_TRUCK_MAX = 15
_MOTORBIKE_MAX = 5
_MOTORBIKE_DIST_KM = 15.0

# ── Province keyword map ──────────────────────────────────────────────────────
# (search_keyword_lowercase, display_name)
# Longer / more specific keywords first to avoid partial subset matches.
_VN_PROVINCE_MAP = [
    ("hồ chí minh", "TP.HCM"),
    ("tp.hcm", "TP.HCM"),
    ("tphcm", "TP.HCM"),
    ("tp hcm", "TP.HCM"),
    ("nhơn trạch", "Đồng Nai"),   # district of Đồng Nai → keep before "đồng nai"
    ("đồng nai", "Đồng Nai"),
    ("bình dương", "Bình Dương"),
    ("bà rịa", "Bà Rịa - Vũng Tàu"),
    ("vũng tàu", "Bà Rịa - Vũng Tàu"),
    ("tây ninh", "Tây Ninh"),
    ("bình phước", "Bình Phước"),
    ("long an", "Long An"),
    ("tiền giang", "Tiền Giang"),
    ("bến tre", "Bến Tre"),
    ("vĩnh long", "Vĩnh Long"),
    ("đồng tháp", "Đồng Tháp"),
    ("an giang", "An Giang"),
    ("kiên giang", "Kiên Giang"),
    ("hậu giang", "Hậu Giang"),
    ("sóc trăng", "Sóc Trăng"),
    ("bạc liêu", "Bạc Liêu"),
    ("cà mau", "Cà Mau"),
    ("trà vinh", "Trà Vinh"),
    ("cần thơ", "Cần Thơ"),
    ("hà nội", "Hà Nội"),
    ("đà nẵng", "Đà Nẵng"),
    ("hải phòng", "Hải Phòng"),
    ("lâm đồng", "Lâm Đồng"),
    ("đắk lắk", "Đắk Lắk"),
    ("đắk nông", "Đắk Nông"),
    ("gia lai", "Gia Lai"),
    ("kon tum", "Kon Tum"),
    ("khánh hòa", "Khánh Hòa"),
    ("ninh thuận", "Ninh Thuận"),
    ("bình thuận", "Bình Thuận"),
    ("phú yên", "Phú Yên"),
    ("quảng nam", "Quảng Nam"),
    ("quảng ngãi", "Quảng Ngãi"),
    ("bình định", "Bình Định"),
]

# ── State display helpers ─────────────────────────────────────────────────────
_STATE_ICONS = {
    "waiting_stock": "⏳",
    "ready_pick": "🏗️",
    "ready_pack": "📦",
    "ready_ship": "✅",
    "done": "✔️",
}
_STATE_LABELS = {
    "waiting_stock": "Chờ hàng",
    "ready_pick": "Cần lấy hàng",
    "ready_pack": "Cần đóng gói",
    "ready_ship": "Sẵn sàng giao",
    "done": "Đã giao",
}


def _action_to_state(action_needed):
    """Convert _wm_detect_action_needed result → route line state string."""
    return {
        "need_pick": "ready_pick",
        "need_pack": "ready_pack",
        "ready_ship": "ready_ship",
    }.get(action_needed, "waiting_stock")


# ══════════════════════════════════════════════════════════════════════════════
#  wm.delivery.route
# ══════════════════════════════════════════════════════════════════════════════

class WmDeliveryRoute(models.Model):
    _name = "wm.delivery.route"
    _description = "Tuyến giao hàng"
    _order = "date_plan asc, province asc, vehicle_type asc"
    _rec_name = "name"

    name = fields.Char("Tên tuyến", required=True)
    date_plan = fields.Date("Ngày giao dự kiến", required=True, default=fields.Date.today)
    province = fields.Char("Tỉnh / Thành phố")
    vehicle_type = fields.Selection(
        [("motorbike", "Xe máy"), ("truck", "Xe tải 1 tấn")],
        default="truck",
        required=True,
    )
    vehicle_id = fields.Many2one("fleet.vehicle", string="Xe giao")
    state = fields.Selection(
        [
            ("draft", "Lên kế hoạch"),
            ("ready", "Sẵn sàng"),
            ("done", "Đã giao"),
            ("cancelled", "Hủy"),
        ],
        default="draft",
        required=True,
    )
    warehouse_id = fields.Many2one("stock.warehouse", string="Kho")
    line_ids = fields.One2many("wm.delivery.route.line", "route_id", string="Đơn hàng")
    last_updated = fields.Datetime("Cập nhật lần cuối", default=fields.Datetime.now)
    has_new_stock = fields.Boolean("Vừa có hàng mới", default=False)

    # ── Province extraction ───────────────────────────────────────────────────

    @api.model
    def _extract_province_for_so(self, so):
        """Extract delivery province string from a sale.order record.

        Priority:
          1. partner_shipping_id.state_id.name  (Odoo province field)
          2. partner_id.state_id.name
          3. Keyword scan on misa_shipping_address / partner address text
          4. "Chưa xác định"
        """
        for p in [so.partner_shipping_id, so.partner_id]:
            if p and p.state_id and p.state_id.name:
                name = p.state_id.name
                # Normalize "Thành phố Hồ Chí Minh" / "TP. Hồ Chí Minh" → "TP.HCM"
                if "hồ chí minh" in name.lower():
                    return "TP.HCM"
                return name

        # Collect address text to scan
        addr_parts = []
        misa_addr = getattr(so, "misa_shipping_address", None)
        if misa_addr:
            addr_parts.append(str(misa_addr))
        p = so.partner_shipping_id or so.partner_id
        if p:
            for f in [p.street, p.city]:
                if f:
                    addr_parts.append(f)
        addr_lower = " ".join(addr_parts).lower()

        for keyword, province_name in _VN_PROVINCE_MAP:
            if keyword in addr_lower:
                return province_name

        return "Chưa xác định"

    # ── Rebuild all routes ────────────────────────────────────────────────────

    @api.model
    def rebuild_routes(self, warehouse_id=None):
        """Drop old draft routes and rebuild from current active SOs.

        Returns the same payload as ``get_board()`` so the frontend can
        update immediately without a second round-trip.
        """
        from .delivery_planner import _wm_detect_action_needed  # avoid circular at module level

        SO = self.env["sale.order"].sudo()
        now = datetime.now()
        today = date.today()

        # ── Resolve warehouse ─────────────────────────────────────────────────
        wh_id = False
        if warehouse_id and str(warehouse_id) not in ("all", "False", ""):
            try:
                wh = self.env["stock.warehouse"].sudo().browse(int(warehouse_id))
                if wh.exists():
                    wh_id = wh.id
            except Exception:
                pass

        # ── Collect candidate SOs ─────────────────────────────────────────────
        domain = [("state", "=", "sale")]
        if wh_id:
            domain += [("warehouse_id", "=", wh_id)]
        all_orders = SO.search(domain, limit=500, order="commitment_date asc nulls last, id desc")

        compiled_ignores = []
        for spec in self.env["wm.customer.ignore"].sudo().search([("active", "=", True)]):
            try:
                compiled_ignores.append(re.compile(spec.pattern, re.IGNORECASE))
            except re.error:
                pass

        candidates = []
        for o in all_orders:
            if compiled_ignores:
                pname = o.partner_id.name or ""
                if any(pat.search(pname) for pat in compiled_ignores):
                    continue
            # Skip fully delivered
            out_done = o.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state == "done"
            )
            if out_done and not o.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")
            ):
                continue
            action_needed = _wm_detect_action_needed(o)
            if action_needed == "none":
                continue

            days_left = None
            overdue = False
            dp = today
            if o.commitment_date:
                delta = o.commitment_date - now
                days_left = round(delta.total_seconds() / 86400, 1)
                overdue = days_left < 0
                dp = o.commitment_date.date()
                if dp < today:
                    dp = today  # overdue → plan for today

            province = self._extract_province_for_so(o)
            candidates.append({
                "id": o.id,
                "dist": o.wm_distance_km or 0.0,
                "action_needed": action_needed,
                "province": province,
                "date_plan": dp,
                "days_left": days_left,
                "overdue": overdue,
            })

        # ── Group by (province, date_plan) ────────────────────────────────────
        groups = defaultdict(list)
        for c in candidates:
            groups[(c["province"], c["date_plan"])].append(c)

        # ── Determine vehicle type, split large groups ────────────────────────
        route_groups = []
        for (province, dp), grp in groups.items():
            n = len(grp)
            dists = [c["dist"] for c in grp if c["dist"]]
            avg_dist = sum(dists) / len(dists) if dists else 999.0

            if n <= _MOTORBIKE_MAX and avg_dist <= _MOTORBIKE_DIST_KM:
                vtype, max_per = "motorbike", _MOTORBIKE_MAX
            else:
                vtype, max_per = "truck", _TRUCK_MAX

            for start in range(0, n, max_per):
                route_groups.append((province, dp, vtype, grp[start : start + max_per]))

        # ── Load existing draft/ready routes for this warehouse ───────────────
        base_domain = [("state", "in", ("draft", "ready"))]
        if wh_id:
            base_domain += [("warehouse_id", "=", wh_id)]
        else:
            base_domain += [("warehouse_id", "=", False)]
        existing_routes = self.sudo().search(base_domain)

        # Build lookup: (province, date_plan, vehicle_type) → route
        route_lookup = {}
        for r in existing_routes:
            if r.date_plan and r.date_plan >= today:
                key = (r.province or "", r.date_plan, r.vehicle_type)
                route_lookup.setdefault(key, r)

        # ── Upsert routes and lines ───────────────────────────────────────────
        touched_ids = set()
        for province, dp, vtype, sub in route_groups:
            key = (province, dp, vtype)
            route = route_lookup.get(key)
            if not route:
                vl = "Xe máy" if vtype == "motorbike" else "Xe tải"
                route = self.sudo().create({
                    "name": "%s %s – %s" % (vl, province or "Chưa rõ", dp.strftime("%d/%m")),
                    "province": province,
                    "date_plan": dp,
                    "vehicle_type": vtype,
                    "warehouse_id": wh_id or False,
                    "state": "draft",
                })
                route_lookup[key] = route
            touched_ids.add(route.id)

            existing_line_map = {ln.sale_order_id.id: ln for ln in route.line_ids}
            sub_ids = {c["id"] for c in sub}

            for c in sub:
                new_state = _action_to_state(c["action_needed"])
                if c["id"] in existing_line_map:
                    ln = existing_line_map[c["id"]]
                    if ln.state != new_state:
                        ln.write({"state": new_state, "state_changed": True})
                    else:
                        ln.write({"state_changed": False})
                else:
                    self.env["wm.delivery.route.line"].sudo().create({
                        "route_id": route.id,
                        "sale_order_id": c["id"],
                        "state": new_state,
                        "state_changed": False,
                    })
            # Remove lines for SOs no longer in this sub-group
            for so_id, ln in existing_line_map.items():
                if so_id not in sub_ids:
                    ln.sudo().unlink()

            route.write({"last_updated": now, "has_new_stock": False})

        # Remove old draft routes not touched by this rebuild
        for r in existing_routes:
            if r.id not in touched_ids and r.state == "draft":
                r.sudo().unlink()

        return self.get_board(warehouse_id)

    # ── Get board ─────────────────────────────────────────────────────────────

    @api.model
    def get_board(self, warehouse_id=None):
        """Return current route board payload for frontend."""
        today = date.today()
        now = datetime.now()

        wh_id = False
        if warehouse_id and str(warehouse_id) not in ("all", "False", ""):
            try:
                wh_id = int(warehouse_id)
            except (ValueError, TypeError):
                pass

        domain = [("state", "not in", ("done", "cancelled"))]
        if wh_id:
            domain += [("warehouse_id", "=", wh_id)]
        routes = self.sudo().search(domain, order="date_plan asc, province asc, vehicle_type asc")

        routes_data = []
        total_orders = 0
        new_stock_route_ids = []

        for route in routes:
            active_lines = route.line_ids.filtered(lambda l: l.state != "done")
            if not active_lines:
                continue

            order_count = len(active_lines)
            ready_count = len(active_lines.filtered(lambda l: l.state == "ready_ship"))
            waiting_count = len(active_lines.filtered(lambda l: l.state == "waiting_stock"))

            # Priority from lines
            has_overdue = any(l.commitment_date and l.commitment_date < now for l in active_lines)
            has_urgent = any(
                l.commitment_date
                and 0 <= (l.commitment_date - now).total_seconds() / 86400 <= 1
                for l in active_lines
            )
            priority = "overdue" if has_overdue else ("urgent" if has_urgent else "normal")

            # Date label
            if route.date_plan == today:
                date_label = "Hôm nay"
            elif route.date_plan == today + timedelta(days=1):
                date_label = "Ngày mai"
            elif route.date_plan:
                date_label = route.date_plan.strftime("%d/%m/%Y")
            else:
                date_label = "?"

            vehicle_label = "🏍️ Xe máy" if route.vehicle_type == "motorbike" else "🚛 Xe tải 1 tấn"
            vehicle_name = ""
            if route.vehicle_id:
                plate = route.vehicle_id.license_plate or route.vehicle_id.name or ""
                model = (
                    route.vehicle_id.model_id.name
                    if route.vehicle_id.model_id
                    else ""
                )
                vehicle_name = ("%s (%s)" % (model, plate)).strip(" ()")

            orders_data = []
            for ln in active_lines.sorted(key=lambda l: (l.commitment_date or datetime(2099, 1, 1))):
                so = ln.sale_order_id
                days_left = None
                overdue_ln = False
                if ln.commitment_date:
                    delta = ln.commitment_date - now
                    days_left = round(delta.total_seconds() / 86400, 1)
                    overdue_ln = days_left < 0
                orders_data.append({
                    "id": so.id,
                    "line_id": ln.id,
                    "name": so.name,
                    "partner": so.partner_id.name or "",
                    "state": ln.state,
                    "state_icon": _STATE_ICONS.get(ln.state, "❓"),
                    "state_label": _STATE_LABELS.get(ln.state, "?"),
                    "commitment_date": str(ln.commitment_date)[:10] if ln.commitment_date else "",
                    "days_left": days_left,
                    "overdue": overdue_ln,
                    "distance_km": round(so.wm_distance_km or 0.0, 1),
                    "state_changed": ln.state_changed,
                })

            if route.has_new_stock:
                new_stock_route_ids.append(route.id)

            routes_data.append({
                "id": route.id,
                "name": route.name,
                "date_plan": str(route.date_plan) if route.date_plan else "",
                "date_plan_label": date_label,
                "province": route.province or "Chưa xác định",
                "vehicle_type": route.vehicle_type,
                "vehicle_type_label": vehicle_label,
                "vehicle_name": vehicle_name,
                "state": route.state,
                "priority": priority,
                "order_count": order_count,
                "ready_count": ready_count,
                "waiting_count": waiting_count,
                "has_new_stock": route.has_new_stock,
                "orders": orders_data,
            })
            total_orders += order_count

        # PO notifications
        po_notify = self._get_po_notifications(wh_id)

        # last_rebuild timestamp
        last_rebuild = None
        if routes:
            valid_ts = [r.last_updated for r in routes if r.last_updated]
            if valid_ts:
                last_rebuild = max(valid_ts).strftime("%H:%M %d/%m")

        # Clear has_new_stock after sending to frontend
        if new_stock_route_ids:
            self.sudo().browse(new_stock_route_ids).write({"has_new_stock": False})

        return {
            "routes": routes_data,
            "po_notifications": po_notify,
            "total_routes": len(routes_data),
            "total_orders": total_orders,
            "last_rebuild": last_rebuild,
        }

    # ── PO notifications ──────────────────────────────────────────────────────

    @api.model
    def _get_po_notifications(self, warehouse_id=False):
        """List orders whose stock is waiting and have an in-transit PO."""
        SO = self.env["sale.order"].sudo()
        domain = [("state", "=", "sale")]
        if warehouse_id:
            domain += [("warehouse_id", "=", warehouse_id)]
        notify = []
        for o in SO.search(domain, limit=200):
            stock_st = o._wm_get_stock_status() if hasattr(o, "_wm_get_stock_status") else "unknown"
            if stock_st != "waiting":
                continue
            po_st, po_ref = (
                o._wm_get_po_status()
                if hasattr(o, "_wm_get_po_status")
                else (None, None)
            )
            if po_st == "in_transit":
                notify.append({
                    "order": o.name,
                    "partner": o.partner_id.name or "",
                    "po_ref": po_ref or "",
                    "message": "PO %s đang về → chuẩn bị PACK cho %s (%s)" % (
                        po_ref or "?", o.name, o.partner_id.name or ""
                    ),
                })
        return notify

    # ── Refresh after PO receipt ──────────────────────────────────────────────

    @api.model
    def refresh_line_states_for_sos(self, so_ids):
        """Update route line states after a PO receipt is validated.

        Called by ``stock.picking.button_validate`` when picking_type == 'in'.
        Transitions waiting_stock lines → ready_pick/ready_pack/ready_ship.
        Flags affected routes as ``has_new_stock = True`` so the UI highlights them.
        """
        from .delivery_planner import _wm_detect_action_needed

        if not so_ids:
            return
        lines = self.env["wm.delivery.route.line"].sudo().search([
            ("sale_order_id", "in", list(so_ids)),
            ("state", "not in", ("done",)),
        ])
        affected_route_ids = set()
        for ln in lines:
            new_state = _action_to_state(_wm_detect_action_needed(ln.sale_order_id))
            if ln.state != new_state:
                ln.write({"state": new_state, "state_changed": True})
                affected_route_ids.add(ln.route_id.id)

        if affected_route_ids:
            self.sudo().browse(list(affected_route_ids)).write({
                "has_new_stock": True,
                "last_updated": datetime.now(),
            })
            _logger.info(
                "[WM Route] Refreshed %d lines for SOs %s. Routes flagged: %s",
                len(lines), so_ids, affected_route_ids,
            )


# ══════════════════════════════════════════════════════════════════════════════
#  wm.delivery.route.line
# ══════════════════════════════════════════════════════════════════════════════

class WmDeliveryRouteLine(models.Model):
    _name = "wm.delivery.route.line"
    _description = "Đơn hàng trong tuyến giao"
    _order = "commitment_date asc nulls last, id asc"

    route_id = fields.Many2one(
        "wm.delivery.route", string="Tuyến", required=True, ondelete="cascade", index=True
    )
    sale_order_id = fields.Many2one(
        "sale.order", string="Đơn bán", required=True, index=True
    )
    state = fields.Selection(
        [
            ("waiting_stock", "Chờ hàng"),
            ("ready_pick", "Cần lấy hàng"),
            ("ready_pack", "Cần đóng gói"),
            ("ready_ship", "Sẵn sàng giao"),
            ("done", "Đã giao"),
        ],
        default="waiting_stock",
        required=True,
        string="Trạng thái",
    )
    commitment_date = fields.Datetime(related="sale_order_id.commitment_date", store=True)
    state_changed = fields.Boolean("Trạng thái vừa thay đổi", default=False)
