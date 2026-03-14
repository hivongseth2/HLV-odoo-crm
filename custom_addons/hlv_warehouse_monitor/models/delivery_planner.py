# -*- coding: utf-8 -*-
"""
Phase 2 – AI Delivery Planner
- Geocodes sale.order shipping address (misa_shipping_address or partner)
- Clusters nearby orders using haversine distance
- Scores priority: deadline, stock, HTGH note, PO receipt status
- Assigns vehicle type: motorbike (≤5 orders, <15km) vs 1-ton truck
- Notifies when PO is in-transit → prepare packing
Reuses ai_delivery_coordinator config params for API keys & warehouse.
"""
import math
import logging
import requests
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_CLUSTER_RADIUS_KM = 8.0   # orders within this radius form one cluster
_MOTORBIKE_MAX = 5          # max orders per motorbike trip
_TRUCK_MAX = 15             # max orders per truck trip
_MOTORBIKE_DIST_KM = 15    # prefer motorbike if cluster avg distance < this


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════════════════════════════════════
#  sale.order extension  –  geocoding + HTGH + stock helpers
# ══════════════════════════════════════════════════════════════════════════

class SaleOrderDeliveryPlanner(models.Model):
    _inherit = "sale.order"

    wm_delivery_lat = fields.Float("[WM] Vĩ độ giao hàng", digits=(10, 7), copy=False)
    wm_delivery_lng = fields.Float("[WM] Kinh độ giao hàng", digits=(10, 7), copy=False)
    wm_distance_km = fields.Float("[WM] Khoảng cách kho (km)", digits=(10, 1), copy=False)
    wm_geocoded_query = fields.Char("[WM] Query đã geocode", copy=False)

    # ── Geocode helpers ────────────────────────────────────────────────

    def _wm_build_geocode_query(self):
        """Build geocode string: MISA shipping address → partner address."""
        self.ensure_one()
        misa_addr = getattr(self, "misa_shipping_address", None)
        if misa_addr and str(misa_addr).strip():
            partner_name = self.partner_id.name or ""
            addr = str(misa_addr).strip()
            return "%s, %s" % (partner_name, addr) if partner_name else addr
        p = self.partner_shipping_id
        if p:
            parts = []
            if self.partner_id and self.partner_id.name:
                parts.append(self.partner_id.name)
            for f in [p.street, p.city, (p.state_id.name if p.state_id else None)]:
                if f:
                    parts.append(f)
            if parts:
                return ", ".join(parts)
        return ""

    def _wm_rapidapi_geocode(self, query):
        """Single geocode via Google Maps Places (RapidAPI). Returns (lat, lng) or (None, None)."""
        rapidapi_key = (
            self.env["ir.config_parameter"].sudo().get_param("ai_delivery_coordinator.rapidapi_key")
        )
        if not rapidapi_key:
            return None, None
        try:
            resp = requests.post(
                "https://google-map-places-new-v2.p.rapidapi.com/v1/places:searchText",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-FieldMask": (
                        "places.id,places.displayName,places.formattedAddress,places.location"
                    ),
                    "x-rapidapi-host": "google-map-places-new-v2.p.rapidapi.com",
                    "x-rapidapi-key": rapidapi_key,
                },
                json={"textQuery": query, "languageCode": "vi", "maxResultCount": 1},
                timeout=15,
            )
            places = resp.json().get("places", [])
            if places:
                loc = places[0]["location"]
                return loc["latitude"], loc["longitude"]
        except Exception as exc:
            _logger.warning("[WM Geocode] Error for '%s': %s", query, exc)
        return None, None

    def _wm_get_warehouse_coords(self):
        """Return (lat, lng) of the configured warehouse; caches in ir.config_parameter."""
        ICP = self.env["ir.config_parameter"].sudo()
        wh_lat = ICP.get_param("hlv.wm.warehouse_lat")
        wh_lng = ICP.get_param("hlv.wm.warehouse_lng")
        if wh_lat and wh_lng:
            try:
                return float(wh_lat), float(wh_lng)
            except (TypeError, ValueError):
                pass

        wh_id = ICP.get_param("ai_delivery_coordinator.warehouse_id")
        if not wh_id:
            return None, None
        try:
            wh = self.env["stock.warehouse"].sudo().browse(int(wh_id))
            if not wh.exists() or not wh.partner_id:
                return None, None
            addr = wh.partner_id.street or wh.partner_id.contact_address
            if not addr:
                return None, None
            lat, lng = self._wm_rapidapi_geocode(addr)
            if lat and lng:
                ICP.set_param("hlv.wm.warehouse_lat", str(lat))
                ICP.set_param("hlv.wm.warehouse_lng", str(lng))
                return lat, lng
        except Exception as exc:
            _logger.warning("[WM Geocode] Could not get warehouse coords: %s", exc)
        return None, None

    def _wm_geocode_one(self):
        """Geocode this order's shipping address and store result."""
        self.ensure_one()
        query = self._wm_build_geocode_query()
        if not query:
            return
        if self.wm_geocoded_query == query and self.wm_delivery_lat:
            return  # already up-to-date
        lat, lng = self._wm_rapidapi_geocode(query)
        if lat and lng:
            wh_lat, wh_lng = self._wm_get_warehouse_coords()
            dist = _haversine(wh_lat, wh_lng, lat, lng) if wh_lat and wh_lng else 0.0
            self.sudo().write({
                "wm_delivery_lat": lat,
                "wm_delivery_lng": lng,
                "wm_distance_km": round(dist, 1),
                "wm_geocoded_query": query,
            })
            _logger.info("[WM Geocode] %s → %.4f, %.4f – %.1f km", self.name, lat, lng, dist)
        else:
            # Still mark as attempted to avoid infinite retry
            self.sudo().write({"wm_geocoded_query": query})

    # ── HTGH classification ───────────────────────────────────────────

    def _wm_classify_htgh(self):
        """Parse x_studio_htgh to delivery method category.

        Returns:
            (category, display_value)
            category:
              'external'     – CPN / Lalamove / GHN / J&T → skip from self-trips
              'self_wait'    – wait until fully stocked, then self-deliver
              'self_partial' – deliver whatever is available now
              'self'         – default self-delivery
        """
        self.ensure_one()
        val = ""
        if hasattr(self, "x_studio_htgh") and self.x_studio_htgh:
            fld = self._fields.get("x_studio_htgh")
            if fld and fld.type == "selection":
                sel = fld.selection
                if callable(sel):
                    sel = sel(self)
                val = dict(sel).get(self.x_studio_htgh, str(self.x_studio_htgh))
            else:
                val = str(self.x_studio_htgh)
        v = val.lower()
        if any(k in v for k in ("cpn", "chuyển phát", "lalamove", "ghn", "j&t", "jt express", "nhanh")):
            return "external", val
        if any(k in v for k in ("chờ đủ", "cho du", "chờ đủ hàng", "cho du hang")):
            return "self_wait", val
        if any(k in v for k in ("có gì giao nấy", "co gi giao nay", "giao nay")):
            return "self_partial", val
        return "self", val

    # ── Stock & PO helpers ────────────────────────────────────────────

    def _wm_get_stock_status(self):
        """Return 'ready' / 'partial' / 'waiting' / 'unknown' based on OUT pickings."""
        self.ensure_one()
        if not hasattr(self, "picking_ids"):
            return "unknown"
        out_picks = self.picking_ids.filtered(
            lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")
        )
        if not out_picks:
            return "unknown"
        states = out_picks.mapped("state")
        if all(s == "assigned" for s in states):
            return "ready"
        if any(s == "assigned" for s in states):
            return "partial"
        return "waiting"

    def _wm_get_po_status(self):
        """Check related PO(s) receipt status. Returns (status_key, po_ref_str)."""
        self.ensure_one()
        PO = self.env["purchase.order"].sudo()
        pos = PO.search([("origin", "ilike", self.name)], limit=10)
        if not pos:
            return None, None
        pending = pos.filtered(lambda p: p.state not in ("purchase", "done", "cancel"))
        done_pos = pos.filtered(lambda p: p.state in ("purchase", "done"))
        incoming = self.env["stock.picking"].sudo().search([
            ("origin", "in", pos.mapped("name")),
            ("picking_type_code", "=", "incoming"),
            ("state", "not in", ("done", "cancel")),
        ], limit=3)
        if incoming:
            return "in_transit", ", ".join(p.name for p in incoming)
        if done_pos and not pending:
            return "received", ", ".join(done_pos[:3].mapped("name"))
        if pending:
            return "pending", ", ".join(pending[:3].mapped("name"))
        return None, None

    # ── Hook ──────────────────────────────────────────────────────────

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            try:
                order._wm_geocode_one()
            except Exception:
                _logger.exception("[WM Planner] Geocode on confirm error %s", order.name)
        return result


# ══════════════════════════════════════════════════════════════════════════
#  warehouse.monitor.event extension  –  delivery plan RPC
# ══════════════════════════════════════════════════════════════════════════

class WarehouseMonitorDeliveryPlanner(models.Model):
    _inherit = "warehouse.monitor.event"

    @api.model
    def get_delivery_plan_suggestions(self, warehouse_id=None):
        """Phase 2: Geocode + cluster + AI-score delivery trips.

        Returns::
            {
              'trips': [...],          # suggested delivery groups
              'po_notify': [...],      # POs in transit → notify packing
              'total_orders': int,
              'total_trips': int,
            }
        """
        SO = self.env["sale.order"].sudo()
        now = datetime.now()

        # ── 1. Collect candidate SOs ───────────────────────────────────
        domain = [("state", "=", "sale")]
        if warehouse_id and str(warehouse_id) not in ("all", "False", ""):
            try:
                wh = self.env["stock.warehouse"].sudo().browse(int(warehouse_id))
                if wh.exists():
                    domain += [("warehouse_id", "=", wh.id)]
            except Exception:
                pass

        all_orders = SO.search(domain, limit=200, order="commitment_date asc nulls last, id desc")
        candidates = []
        po_notify = []

        for o in all_orders:
            # Skip fully delivered
            out_done = o.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state == "done"
            )
            if out_done and not o.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")
            ):
                continue

            htgh_cat, htgh_val = o._wm_classify_htgh()
            if htgh_cat == "external":
                continue  # third-party carrier, skip

            stock_st = o._wm_get_stock_status()

            # self_wait: only include if stock ready; but check PO for notification
            if htgh_cat == "self_wait" and stock_st not in ("ready", "partial"):
                po_st, po_ref = o._wm_get_po_status()
                if po_st == "in_transit":
                    po_notify.append({
                        "order": o.name,
                        "partner": o.partner_id.name or "",
                        "po_ref": po_ref or "",
                        "message": "PO %s đang về → chuẩn bị PACK cho %s (%s)" % (
                            po_ref or "?", o.name, o.partner_id.name or ""
                        ),
                    })
                continue

            overdue = False
            days_left = None
            if o.commitment_date:
                delta = o.commitment_date - now
                days_left = round(delta.total_seconds() / 86400, 1)
                overdue = days_left < 0

            candidates.append({
                "id": o.id,
                "name": o.name,
                "partner": o.partner_id.name or "",
                "htgh_cat": htgh_cat,
                "htgh_val": htgh_val or "",
                "stock_status": stock_st,
                "commitment_date": str(o.commitment_date)[:19] if o.commitment_date else "",
                "days_left": days_left,
                "overdue": overdue,
                "lat": o.wm_delivery_lat,
                "lng": o.wm_delivery_lng,
                "dist": o.wm_distance_km or 0.0,
                "has_coords": bool(o.wm_delivery_lat and o.wm_delivery_lng),
                "amount_total": o.amount_total,
            })

        if not candidates:
            return {
                "trips": [], "po_notify": po_notify,
                "total_orders": 0, "total_trips": 0,
            }

        # ── 2. Trigger lazy geocoding for orders without coords (batch ≤10) ──
        no_coords = [c for c in candidates if not c["has_coords"]]
        if no_coords:
            orders_to_geo = SO.browse([c["id"] for c in no_coords[:10]])
            for o in orders_to_geo:
                try:
                    o._wm_geocode_one()
                    if o.wm_delivery_lat:
                        for c in candidates:
                            if c["id"] == o.id:
                                c.update({
                                    "lat": o.wm_delivery_lat,
                                    "lng": o.wm_delivery_lng,
                                    "dist": o.wm_distance_km or 0.0,
                                    "has_coords": True,
                                })
                except Exception:
                    pass

        # ── 3. Sort: overdue first → deadline → distance ───────────────
        def _sort_key(c):
            return (
                0 if c["overdue"] else 1,
                c["days_left"] if c["days_left"] is not None else 999.0,
                c["dist"],
            )
        candidates.sort(key=_sort_key)

        # ── 4. Greedy proximity clustering ────────────────────────────
        with_coords = [c for c in candidates if c["has_coords"]]
        without_coords = [c for c in candidates if not c["has_coords"]]

        clusters = []
        used = set()
        for anchor in with_coords:
            if anchor["id"] in used:
                continue
            cluster = [anchor]
            used.add(anchor["id"])
            for cand in with_coords:
                if cand["id"] in used:
                    continue
                if _haversine(anchor["lat"], anchor["lng"], cand["lat"], cand["lng"]) <= _CLUSTER_RADIUS_KM:
                    cluster.append(cand)
                    used.add(cand["id"])
            clusters.append(cluster)

        # Orders without coords: each becomes a separate single-order cluster
        for c in without_coords:
            clusters.append([c])

        # ── 5. Query available fleet vehicles ─────────────────────────
        vehicles = {"motorbike": [], "truck": []}
        try:
            fleet = self.env["fleet.vehicle"].sudo().search([], limit=50)
            for v in fleet:
                model_name = (v.model_id.name or "").lower()
                plate = v.license_plate or v.name or str(v.id)
                tag = {"id": v.id, "name": "%s (%s)" % (v.model_id.name or "Xe", plate)}
                if any(k in model_name for k in ("xe máy", "xe_may", "honda", "motor", "scooter", "wave")):
                    vehicles["motorbike"].append(tag)
                else:
                    vehicles["truck"].append(tag)
        except Exception as exc:
            _logger.warning("[WM Planner] Could not query fleet: %s", exc)

        # ── 6. Build trip suggestions ──────────────────────────────────
        trips = []
        trip_seq = 1
        for cluster in clusters:
            n = len(cluster)
            avg_dist = (
                sum(c["dist"] for c in cluster if c["dist"]) / max(1, sum(1 for c in cluster if c["dist"]))
            )
            # Decide vehicle type
            if n <= _MOTORBIKE_MAX and avg_dist <= _MOTORBIKE_DIST_KM:
                vtype = "motorbike"
                vtype_label = "🏍️ Xe máy"
                max_per_vehicle = _MOTORBIKE_MAX
            else:
                vtype = "truck"
                vtype_label = "🚚 Xe tải 1 tấn"
                max_per_vehicle = _TRUCK_MAX

            # Split large clusters into multiple trips
            for start in range(0, n, max_per_vehicle):
                sub = cluster[start : start + max_per_vehicle]
                sub_dist = (
                    sum(c["dist"] for c in sub if c["dist"]) / max(1, sum(1 for c in sub if c["dist"]))
                )
                has_overdue = any(c["overdue"] for c in sub)
                has_urgent = any(
                    c["days_left"] is not None and 0 <= c["days_left"] <= 1
                    for c in sub
                )
                priority = "overdue" if has_overdue else ("urgent" if has_urgent else "normal")

                trips.append({
                    "id": trip_seq,
                    "vehicle_type": vtype,
                    "vehicle_type_label": vtype_label,
                    "suggested_vehicle": vehicles[vtype][0] if vehicles[vtype] else None,
                    "available_vehicles": vehicles[vtype][:5],
                    "order_count": len(sub),
                    "avg_distance_km": round(sub_dist, 1),
                    "priority": priority,
                    "orders": [
                        {
                            "id": c["id"],
                            "name": c["name"],
                            "partner": c["partner"],
                            "stock_status": c["stock_status"],
                            "htgh_val": c["htgh_val"],
                            "commitment_date": c["commitment_date"],
                            "days_left": c["days_left"],
                            "overdue": c["overdue"],
                            "distance_km": round(c["dist"], 1),
                            "has_coords": c["has_coords"],
                            "amount_total": c["amount_total"],
                        }
                        for c in sub
                    ],
                })
                trip_seq += 1

        return {
            "trips": trips,
            "po_notify": po_notify,
            "total_orders": len(candidates),
            "total_trips": len(trips),
        }
