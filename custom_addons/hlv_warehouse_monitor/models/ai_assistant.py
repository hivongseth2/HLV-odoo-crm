# -*- coding: utf-8 -*-
"""
AI Assistant for Warehouse Monitor.

When a significant event fires (IN/PICK/PACK validated, new SO/PO confirmed)
the assistant gathers all related context and calls OpenAI to produce:
  - A short situation analysis (Vietnamese)
  - 2–4 concrete next-action bullets

Results are stored in warehouse.monitor.ai.insight so they persist between
page refreshes and multiple browser tabs.

Config params (shared with ai_delivery_coordinator):
  openai.api_key  or  hlv.openai.api_key
"""
import json
import logging
import re
from datetime import datetime, timedelta

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_SIGNIFICANT_EVENTS = {
    ("in", "validate"),
    ("pick", "validate"),
    ("pack", "validate"),
    ("out", "validate"),
    ("sale", "confirm"),
    ("purchase", "confirm"),
    ("pick", "priority_set"),
    ("in", "cancel"),
    ("out", "cancel"),
}

_TYPE_EMOJI = {
    "in": "📥",
    "out": "📤",
    "pick": "🏗️",
    "pack": "📦",
    "sale": "🛒",
    "purchase": "🛍️",
    "internal": "↔️",
    "inventory": "📋",
    "return": "↩️",
}


# ══════════════════════════════════════════════════════════════════════════
#  Model: warehouse.monitor.ai.insight
# ══════════════════════════════════════════════════════════════════════════

class WarehouseMonitorAIInsight(models.Model):
    _name = "warehouse.monitor.ai.insight"
    _description = "AI Insight tự động từ sự kiện kho"
    _order = "timestamp desc, id desc"
    _rec_name = "headline"

    headline = fields.Char(string="Tiêu đề", required=True, readonly=True)
    event_id = fields.Many2one(
        "warehouse.monitor.event",
        string="Sự kiện nguồn",
        ondelete="set null",
        readonly=True,
        index=True,
    )
    event_type = fields.Char(string="Loại sự kiện", readonly=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Kho", readonly=True, index=True)
    timestamp = fields.Datetime(
        string="Thời điểm phân tích",
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    # AI content
    analysis = fields.Text(string="Phân tích AI", readonly=True)
    actions_json = fields.Text(string="Hành động gợi ý (JSON)", readonly=True)
    priority = fields.Selection(
        [("urgent", "Khẩn cấp"), ("high", "Cao"), ("normal", "Bình thường")],
        string="Mức ưu tiên",
        default="normal",
        readonly=True,
        index=True,
    )
    # Set to True when user typed a free-form question
    is_question = fields.Boolean(string="Câu hỏi tự do", default=False, readonly=True)
    question = fields.Char(string="Câu hỏi", readonly=True)
    # Dismiss flag
    is_dismissed = fields.Boolean(string="Đã ẩn", default=False, index=True)

    def _actions_list(self):
        """Return actions as Python list (safe parse)."""
        self.ensure_one()
        try:
            return json.loads(self.actions_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []


# ══════════════════════════════════════════════════════════════════════════
#  Extend warehouse.monitor.event with AI analysis RPCs
# ══════════════════════════════════════════════════════════════════════════

class WarehouseMonitorEventAI(models.Model):
    _inherit = "warehouse.monitor.event"

    # ── Internal: context builders ────────────────────────────────────────

    def _ai_build_context(self):
        """Build a rich context dict for AI analysis from this event."""
        self.ensure_one()
        ctx = {
            "event": {
                "id": self.id,
                "name": self.name,
                "type": self.event_type,
                "action": self.action,
                "summary": self.summary or "",
                "suggestion": self.suggestion or "",
                "state_before": self.state_before or "",
                "state_after": self.state_after or "",
                "origin": self.origin or "",
                "time": str(self.timestamp)[:19] if self.timestamp else "",
            }
        }

        # ── Picking context ──────────────────────────────────────────
        if self.picking_id:
            p = self.picking_id.sudo()
            moves = []
            for m in p.move_ids[:15]:
                moves.append({
                    "product": m.product_id.display_name,
                    "qty": m.product_uom_qty,
                    "done_qty": m.quantity if hasattr(m, "quantity") else m.product_uom_qty,
                })
            ctx["picking"] = {
                "name": p.name,
                "type_code": p.picking_type_id.sequence_code or "",
                "state": p.state,
                "scheduled_date": str(p.scheduled_date)[:16] if p.scheduled_date else "",
                "partner": p.partner_id.name if p.partner_id else "",
                "origin": p.origin or "",
                "moves": moves,
            }

        # ── Sale order context ────────────────────────────────────────
        so = None
        if self.sale_id:
            so = self.sale_id.sudo()
        elif self.picking_id:
            p = self.picking_id.sudo()
            # Try group_id → sale_id
            if hasattr(p.group_id, "sale_id") and p.group_id.sale_id:
                so = p.group_id.sale_id.sudo()
            elif hasattr(p, "sale_id") and p.sale_id:
                so = p.sale_id.sudo()
            # Try origin
            if not so and p.origin:
                so_rec = self.env["sale.order"].sudo().search(
                    [("name", "=", p.origin.strip())], limit=1
                )
                if so_rec:
                    so = so_rec

        if so:
            htgh_val = ""
            if hasattr(so, "x_studio_htgh") and so.x_studio_htgh:
                fld = so._fields.get("x_studio_htgh")
                if fld and fld.type == "selection":
                    sel = fld.selection
                    if callable(sel):
                        sel = sel(so)
                    htgh_val = dict(sel).get(so.x_studio_htgh, str(so.x_studio_htgh))
                else:
                    htgh_val = str(so.x_studio_htgh)

            # Picking chain state summary
            pick_chain = {}
            if hasattr(so, "picking_ids"):
                for pk in so.picking_ids.sudo():
                    seq = (pk.picking_type_id.sequence_code or "").upper()
                    if seq not in pick_chain:
                        pick_chain[seq] = []
                    pick_chain[seq].append({"name": pk.name, "state": pk.state})

            ctx["sale_order"] = {
                "name": so.name,
                "partner": so.partner_id.name if so.partner_id else "",
                "state": so.state,
                "amount_total": so.amount_total,
                "commitment_date": str(so.commitment_date)[:16] if so.commitment_date else "",
                "htgh": htgh_val,
                "picking_chain": pick_chain,
            }

        # ── Purchase order context ─────────────────────────────────────
        po = None
        if self.purchase_id:
            po = self.purchase_id.sudo()
        elif self.picking_id and self.picking_id.origin:
            po_rec = self.env["purchase.order"].sudo().search(
                [("name", "=", self.picking_id.origin.strip())], limit=1
            )
            if po_rec:
                po = po_rec

        if po:
            ctx["purchase_order"] = {
                "name": po.name,
                "partner": po.partner_id.name if po.partner_id else "",
                "state": po.state,
                "amount_total": po.amount_total,
                "origin": po.origin or "",
                "date_planned": str(po.date_approve or po.date_order)[:16] if po.date_order else "",
            }

        # ── Recent context events (same warehouse, last 1h) ────────────
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent = self.sudo().search(
            [
                ("id", "!=", self.id),
                ("warehouse_id", "=", self.warehouse_id.id) if self.warehouse_id else ("id", "!=", self.id),
                ("timestamp", ">=", str(one_hour_ago)[:19]),
            ],
            limit=5,
            order="timestamp desc",
        )
        ctx["recent_events"] = [
            {"name": e.name, "type": e.event_type, "action": e.action, "time": str(e.timestamp)[:19]}
            for e in recent
        ]

        return ctx

    def _ai_build_prompt(self, ctx, question=None):
        """Build the Vietnamese prompt for OpenAI."""
        lines = [
            "Bạn là trợ lý AI thông minh cho hệ thống quản lý kho bán lẻ tại Việt Nam.",
            "Nhiệm vụ: phân tích sự kiện và đề xuất hành động tiếp theo ngắn gọn, thực tế.",
            "",
        ]

        ev = ctx["event"]
        type_emoji = _TYPE_EMOJI.get(ev["type"], "📌")
        lines.append(f"=== SỰ KIỆN VỪA XẢY RA ===")
        lines.append(f"{type_emoji} Loại: {ev['type'].upper()} | Hành động: {ev['action']}")
        lines.append(f"Tên: {ev['name']}")
        if ev["summary"]:
            lines.append(f"Tóm tắt: {ev['summary']}")
        if ev["state_before"] and ev["state_after"]:
            lines.append(f"Trạng thái: {ev['state_before']} → {ev['state_after']}")
        if ev["origin"]:
            lines.append(f"Chứng từ gốc: {ev['origin']}")
        if ev["time"]:
            lines.append(f"Thời gian: {ev['time']}")

        if ctx.get("picking"):
            pk = ctx["picking"]
            lines.append(f"\n--- Phiếu kho: {pk['name']} ({pk['type_code']}) ---")
            lines.append(f"Trạng thái: {pk['state']} | Đối tác: {pk['partner']}")
            if pk["scheduled_date"]:
                lines.append(f"Ngày hẹn: {pk['scheduled_date']}")
            if pk["moves"]:
                lines.append("Hàng hoá:")
                for m in pk["moves"][:8]:
                    lines.append(f"  • {m['product']} x{m['qty']}")

        if ctx.get("sale_order"):
            so = ctx["sale_order"]
            lines.append(f"\n--- Đơn bán: {so['name']} ---")
            lines.append(f"Khách hàng: {so['partner']} | Giá trị: {so['amount_total']:,.0f} VNĐ")
            if so["commitment_date"]:
                lines.append(f"Ngày giao hẹn: {so['commitment_date']}")
            if so["htgh"]:
                lines.append(f"Hình thức giao: {so['htgh']}")
            if so["picking_chain"]:
                lines.append("Chuỗi phiếu kho:")
                for seq, pks in so["picking_chain"].items():
                    states = ", ".join(f"{pk['name']}({pk['state']})" for pk in pks[:3])
                    lines.append(f"  {seq}: {states}")

        if ctx.get("purchase_order"):
            po = ctx["purchase_order"]
            lines.append(f"\n--- Đơn mua: {po['name']} ---")
            lines.append(f"NCC: {po['partner']} | Trạng thái: {po['state']}")
            if po["origin"]:
                lines.append(f"Gốc: {po['origin']}")

        if ctx.get("recent_events"):
            lines.append("\n--- 5 sự kiện gần nhất cùng kho ---")
            for re_ev in ctx["recent_events"]:
                lines.append(f"  • [{re_ev['type'].upper()}] {re_ev['action']} – {re_ev['name'][:60]}")

        lines.append("")
        if question:
            lines.append(f"=== CÂU HỎI CỦA NGƯỜI DÙNG ===")
            lines.append(question)
            lines.append("")
            lines.append("Trả lời câu hỏi trên dựa vào ngữ cảnh kho ở trên.")
        else:
            lines.append("=== YÊU CẦU ===")
            lines.append(
                "Dựa vào toàn bộ thông tin trên, hãy:\n"
                "1. Phân tích ngắn gọn tình huống (2-3 câu, tiếng Việt)\n"
                "2. Liệt kê 2-4 hành động tiếp theo cụ thể, ưu tiên nhất\n"
                "3. Đánh giá mức độ khẩn cấp: urgent / high / normal"
            )

        lines.append("")
        lines.append(
            "Trả về JSON (không giải thích thêm):\n"
            '{"analysis": "...", "actions": ["...", "..."], "priority": "urgent|high|normal"}'
        )

        return "\n".join(lines)

    def _ai_call_openai(self, prompt):
        """Call OpenAI API. Returns (analysis_str, actions_list, priority_str) or raises."""
        ICP = self.env["ir.config_parameter"].sudo()
        api_key = (
            ICP.get_param("openai.api_key")
            or ICP.get_param("hlv.openai.api_key")
            or ICP.get_param("ai_delivery_coordinator.openai_api_key")
        )
        if not api_key:
            raise ValueError("Chưa cấu hình OpenAI API key (openai.api_key)")

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Bạn là trợ lý AI của hệ thống giám sát kho hàng. "
                            "Luôn trả lời bằng tiếng Việt, ngắn gọn, thực tế. "
                            "Chỉ trả về JSON đúng format được yêu cầu."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 600,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        data = json.loads(content)
        analysis = data.get("analysis", "")
        actions = data.get("actions", [])
        if isinstance(actions, str):
            actions = [actions]
        priority = data.get("priority", "normal")
        if priority not in ("urgent", "high", "normal"):
            priority = "normal"

        return analysis, actions, priority

    # ── Public RPC methods ─────────────────────────────────────────────────

    @api.model
    def analyze_event(self, event_id):
        """Analyze a specific event and store result.

        Returns insight dict or error dict.
        """
        event = self.sudo().browse(event_id)
        if not event.exists():
            return {"error": "Không tìm thấy sự kiện"}

        # Avoid duplicating analysis within 5 minutes
        five_min_ago = datetime.now() - timedelta(minutes=5)
        existing = self.env["warehouse.monitor.ai.insight"].sudo().search(
            [("event_id", "=", event_id), ("timestamp", ">=", str(five_min_ago)[:19])],
            limit=1,
        )
        if existing:
            return self._format_insight(existing)

        try:
            ctx = event._ai_build_context()
            prompt = event._ai_build_prompt(ctx)
            analysis, actions, priority = event._ai_call_openai(prompt)
        except ValueError as exc:
            # No API key
            return {"error": str(exc), "no_key": True}
        except Exception as exc:
            _logger.warning("[WM AI] analyze_event failed for #%d: %s", event_id, exc)
            return {"error": "Lỗi gọi AI: %s" % str(exc)[:120]}

        type_emoji = _TYPE_EMOJI.get(event.event_type, "📌")
        headline = f"{type_emoji} {event.name}"[:200]

        insight = self.env["warehouse.monitor.ai.insight"].sudo().create({
            "headline": headline,
            "event_id": event_id,
            "event_type": event.event_type,
            "warehouse_id": event.warehouse_id.id if event.warehouse_id else False,
            "analysis": analysis,
            "actions_json": json.dumps(actions, ensure_ascii=False),
            "priority": priority,
        })

        _logger.info("[WM AI] Insight created for event #%d: %s", event_id, priority)
        return self._format_insight(insight)

    @api.model
    def ask_ai(self, question, context_event_id=None):
        """Free-form question to AI, optionally anchored to an event for context.

        Returns insight dict or error dict.
        """
        if not question or not question.strip():
            return {"error": "Câu hỏi không được rỗng"}

        question = question.strip()[:500]

        # Build context: use event or most recent significant event
        event = None
        if context_event_id:
            event = self.sudo().browse(context_event_id)
            if not event.exists():
                event = None

        if not event:
            event = self.sudo().search([], limit=1, order="timestamp desc")

        if event:
            ctx = event._ai_build_context()
            prompt = event._ai_build_prompt(ctx, question=question)
        else:
            prompt = (
                "Bạn là trợ lý AI của hệ thống quản lý kho. "
                "Câu hỏi người dùng: " + question + "\n\n"
                "Hãy trả lời bằng tiếng Việt ngắn gọn.\n"
                'Trả về JSON: {"analysis": "...", "actions": [], "priority": "normal"}'
            )

        try:
            analysis, actions, priority = event._ai_call_openai(prompt) if event else (None, None, None)
        except ValueError as exc:
            return {"error": str(exc), "no_key": True}
        except Exception as exc:
            _logger.warning("[WM AI] ask_ai failed: %s", exc)
            return {"error": "Lỗi gọi AI: %s" % str(exc)[:120]}

        insight = self.env["warehouse.monitor.ai.insight"].sudo().create({
            "headline": f"❓ {question[:80]}",
            "event_id": event.id if event else False,
            "event_type": "question",
            "warehouse_id": event.warehouse_id.id if event and event.warehouse_id else False,
            "analysis": analysis or "",
            "actions_json": json.dumps(actions or [], ensure_ascii=False),
            "priority": priority or "normal",
            "is_question": True,
            "question": question,
        })

        return self._format_insight(insight)

    @api.model
    def get_ai_insights(self, limit=15, warehouse_id=None):
        """Return recent non-dismissed insights for the AI panel."""
        domain = [("is_dismissed", "=", False)]
        if warehouse_id and str(warehouse_id) not in ("all", "False", ""):
            try:
                domain.append(("warehouse_id", "=", int(warehouse_id)))
            except (ValueError, TypeError):
                pass

        insights = self.env["warehouse.monitor.ai.insight"].sudo().search(
            domain, limit=limit, order="timestamp desc"
        )
        return [self._format_insight(i) for i in insights]

    @api.model
    def dismiss_ai_insight(self, insight_id):
        ins = self.env["warehouse.monitor.ai.insight"].sudo().browse(insight_id)
        if ins.exists():
            ins.write({"is_dismissed": True})
        return True

    @api.model
    def clear_ai_insights(self):
        """Clear all insights (called by user)."""
        self.env["warehouse.monitor.ai.insight"].sudo().search([]).write(
            {"is_dismissed": True}
        )
        return True

    def _format_insight(self, insight):
        """Serialize an insight record for the frontend."""
        return {
            "id": insight.id,
            "headline": insight.headline or "",
            "event_id": insight.event_id.id if insight.event_id else None,
            "event_type": insight.event_type or "",
            "warehouse": insight.warehouse_id.name if insight.warehouse_id else "",
            "analysis": insight.analysis or "",
            "actions": insight._actions_list(),
            "priority": insight.priority or "normal",
            "timestamp": str(insight.timestamp)[:19] if insight.timestamp else "",
            "is_question": insight.is_question,
            "question": insight.question or "",
        }
