# -*- coding: utf-8 -*-
"""
Delivery Config — supplementary data models for the AI Delivery Planner:
  - wm.customer.ignore  : regex patterns to skip customers from route analysis
  - wm.customer.address : manual address book with lat/lng geocode cache
"""
import logging
import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
#  wm.customer.ignore
# ══════════════════════════════════════════════════════════════════════════

class WmCustomerIgnore(models.Model):
    _name = "wm.customer.ignore"
    _description = "Danh sách khách hàng bỏ qua phân tích tuyến"
    _order = "name"

    name = fields.Char(
        "Mô tả / Nhãn",
        required=True,
        help="Ví dụ: Bán lẻ tại quầy, POS Counter, Khách vãng lai...",
    )
    pattern = fields.Char(
        "Regex tên khách hàng",
        required=True,
        help=(
            "Biểu thức chính quy Python (case-insensitive) so với tên đối tác.\n"
            "Ví dụ: ^quầy|POS|tại chỗ|counter|vãng lai"
        ),
    )
    active = fields.Boolean("Đang bật", default=True)
    note = fields.Char("Ghi chú")

    @api.model
    def get_active_patterns(self):
        """Return list of active regex patterns (called by delivery planner)."""
        recs = self.sudo().search([("active", "=", True)])
        return [{"id": r.id, "name": r.name, "pattern": r.pattern} for r in recs]


# ══════════════════════════════════════════════════════════════════════════
#  wm.customer.address
# ══════════════════════════════════════════════════════════════════════════

class WmCustomerAddress(models.Model):
    _name = "wm.customer.address"
    _description = "Sổ địa chỉ khách hàng (cache geocode thủ công)"
    _order = "customer_name"

    customer_name = fields.Char("Tên khách hàng (khớp chính xác)", required=True)
    address_text = fields.Char("Địa chỉ giao hàng đầy đủ", required=True)
    lat = fields.Float("Vĩ độ", digits=(10, 7))
    lng = fields.Float("Kinh độ", digits=(10, 7))
    last_geocoded = fields.Datetime("Lần geocode cuối", readonly=True)
    note = fields.Char("Ghi chú")

    # ── Internal helpers ──────────────────────────────────────────────

    @api.model
    def find_cached_coords(self, partner_name):
        """Return (lat, lng) if partner_name matches a cached entry, else (None, None)."""
        if not partner_name:
            return None, None
        rec = self.sudo().search(
            [("customer_name", "=ilike", partner_name), ("lat", "!=", 0.0), ("lng", "!=", 0.0)],
            limit=1,
        )
        if rec:
            return rec.lat, rec.lng
        return None, None

    # ── Geocode action (button) ───────────────────────────────────────

    def action_geocode(self):
        """Geocode address_text via RapidAPI → store lat/lng."""
        ICP = self.env["ir.config_parameter"].sudo()
        rapidapi_key = ICP.get_param("ai_delivery_coordinator.rapidapi_key")
        if not rapidapi_key:
            raise models.ValidationError(
                "Chưa cấu hình RapidAPI key (ai_delivery_coordinator.rapidapi_key)"
            )
        for rec in self:
            try:
                resp = requests.post(
                    "https://google-map-places-new-v2.p.rapidapi.com/v1/places:searchText",
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-FieldMask": "places.location",
                        "x-rapidapi-host": "google-map-places-new-v2.p.rapidapi.com",
                        "x-rapidapi-key": rapidapi_key,
                    },
                    json={
                        "textQuery": rec.address_text,
                        "languageCode": "vi",
                        "maxResultCount": 1,
                    },
                    timeout=15,
                )
                places = resp.json().get("places", [])
                if not places:
                    raise models.ValidationError(
                        "Không tìm được toạ độ cho địa chỉ: %s" % rec.address_text
                    )
                loc = places[0]["location"]
                rec.sudo().write(
                    {
                        "lat": loc["latitude"],
                        "lng": loc["longitude"],
                        "last_geocoded": fields.Datetime.now(),
                    }
                )
                _logger.info(
                    "[WM AddrBook] Geocoded '%s': %.4f, %.4f",
                    rec.customer_name,
                    loc["latitude"],
                    loc["longitude"],
                )
            except models.ValidationError:
                raise
            except Exception as exc:
                _logger.warning("[WM AddrBook] Geocode error: %s", exc)
                raise models.ValidationError("Lỗi geocode: %s" % str(exc))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": "Geocode thành công!", "type": "success", "sticky": False},
        }

    # ── RPC methods for frontend ──────────────────────────────────────

    @api.model
    def rpc_get_entries(self):
        recs = self.sudo().search([])
        return [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "address_text": r.address_text,
                "lat": r.lat,
                "lng": r.lng,
                "has_coords": bool(r.lat and r.lng),
                "last_geocoded": str(r.last_geocoded)[:16] if r.last_geocoded else "",
            }
            for r in recs
        ]

    @api.model
    def rpc_save_entry(self, data):
        customer_name = (data.get("customer_name") or "").strip()
        address_text = (data.get("address_text") or "").strip()
        if not customer_name or not address_text:
            return {"error": "Tên và địa chỉ không được để trống"}
        rec_id = data.get("id")
        if rec_id:
            rec = self.sudo().browse(int(rec_id))
            if rec.exists():
                rec.write({"customer_name": customer_name, "address_text": address_text})
                return {"id": rec.id, "ok": True}
        rec = self.sudo().create({"customer_name": customer_name, "address_text": address_text})
        return {"id": rec.id, "ok": True}

    @api.model
    def rpc_geocode_entry(self, entry_id):
        rec = self.sudo().browse(int(entry_id))
        if not rec.exists():
            return {"error": "Không tìm thấy bản ghi"}
        try:
            rec.action_geocode()
            return {"lat": rec.lat, "lng": rec.lng, "ok": True}
        except Exception as exc:
            return {"error": str(exc)}

    @api.model
    def rpc_delete_entry(self, entry_id):
        rec = self.sudo().browse(int(entry_id))
        if rec.exists():
            rec.unlink()
        return {"ok": True}
