import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PICKING_STATE_LABELS = {
    "draft": "Nháp",
    "waiting": "Chờ hoạt động khác",
    "confirmed": "Chờ",
    "assigned": "Sẵn sàng",
    "done": "Hoàn thành",
    "cancel": "Hủy",
}


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _monitor_get_event_type(self):
        """Determine event type from picking type code."""
        self.ensure_one()
        code = (self.picking_type_id.sequence_code or "").upper()
        picking_code = self.picking_type_code

        if "PICK" in code:
            return "pick"
        elif "PACK" in code:
            return "pack"
        elif picking_code == "outgoing" or "OUT" in code:
            return "out"
        elif picking_code == "incoming" or "IN" in code:
            return "in"
        elif picking_code == "internal":
            return "internal"
        return "internal"

    def _monitor_find_related_sale(self):
        """Find related sale order via origin, group, or move lines."""
        self.ensure_one()

        # 1) Direct sale_id relation
        if hasattr(self, "sale_id") and self.sale_id:
            return self.sale_id

        # 2) Via procurement group
        if self.group_id and hasattr(self.group_id, "sale_id") and self.group_id.sale_id:
            return self.group_id.sale_id

        # 3) Via move lines
        for move in self.move_ids:
            if hasattr(move, "sale_line_id") and move.sale_line_id:
                return move.sale_line_id.order_id

        # 4) Via origin field
        if self.origin:
            so = self.env["sale.order"].search(
                [("name", "=", self.origin.strip())], limit=1
            )
            if so:
                return so

        return self.env["sale.order"].browse()

    def _monitor_find_related_purchase(self):
        """Find related purchase order via origin."""
        self.ensure_one()
        if self.origin:
            po = self.env["purchase.order"].search(
                [("name", "=", self.origin.strip())], limit=1
            )
            if po:
                return po
        # Via move lines
        for move in self.move_ids:
            if hasattr(move, "purchase_line_id") and move.purchase_line_id:
                return move.purchase_line_id.order_id
        return self.env["purchase.order"].browse()

    def _monitor_build_product_summary(self):
        """Build a text summary of products in this picking."""
        self.ensure_one()
        lines = []
        for move in self.move_ids[:10]:  # max 10 products in summary
            lines.append("%s x %s" % (move.product_id.display_name, move.product_uom_qty))
        if len(self.move_ids) > 10:
            lines.append("... và %d sản phẩm khác" % (len(self.move_ids) - 10))
        return "\n".join(lines)

    def _monitor_build_suggestion(self, event_type, action):
        """Build suggestion text based on context."""
        self.ensure_one()
        suggestion = ""

        if event_type == "in" and action == "validate":
            # PO receipt completed → suggest PICK for related SO
            so = self._monitor_find_related_sale()
            po = self._monitor_find_related_purchase()
            origin_ref = po.name if po else (self.origin or "")

            if so:
                suggestion = (
                    "✅ Nhập kho hoàn thành cho %s (gốc: %s). "
                    "ĐỀ XUẤT: Lấy hàng (PICK) và đóng gói cho đơn bán %s ngay!"
                ) % (self.name, origin_ref, so.name)
            elif origin_ref:
                # Even without direct SO link, suggest checking origin
                suggestion = (
                    "✅ Nhập kho hoàn thành cho %s (gốc: %s). "
                    "Kiểm tra đơn bán liên quan để lấy hàng đóng gói."
                ) % (self.name, origin_ref)

        elif event_type == "pick" and action == "validate":
            so = self._monitor_find_related_sale()
            if so:
                suggestion = (
                    "✅ Lấy hàng hoàn thành cho %s (đơn %s). "
                    "ĐỀ XUẤT: Đóng gói (PACK) cho đơn bán %s."
                ) % (self.name, self.origin or "", so.name)

        elif event_type == "pack" and action == "validate":
            so = self._monitor_find_related_sale()
            if so:
                suggestion = (
                    "✅ Đóng gói hoàn thành cho %s. "
                    "ĐỀ XUẤT: Xuất kho (OUT) cho đơn bán %s."
                ) % (self.name, so.name)

        elif event_type == "out" and action == "validate":
            suggestion = (
                "✅ Xuất kho hoàn thành cho %s. Đơn hàng đã sẵn sàng giao."
            ) % self.name

        return suggestion

    # ── IN → PICK auto-priority ─────────────────────────────────────────────

    def _find_related_picks_for_in(self):
        """After IN validated: find PICK pickings that need prioritization."""
        self.ensure_one()
        SP = self.env["stock.picking"]
        SO = self.env["sale.order"]

        po = self._monitor_find_related_purchase()
        if not po:
            return SP.browse()

        sale_orders = SO.browse()
        # Method 1: PO.origin may contain SO name
        if po.origin:
            for ref in po.origin.split(","):
                ref = ref.strip()
                if not ref:
                    continue
                so = SO.search([("name", "=", ref)], limit=1)
                if so:
                    sale_orders |= so

        # Method 2: via purchase line → sale line link
        for line in po.order_line:
            if hasattr(line, "sale_line_id") and line.sale_line_id:
                sale_orders |= line.sale_line_id.order_id

        if not sale_orders:
            return SP.browse()

        pick_pickings = SP.browse()
        for so in sale_orders:
            if hasattr(so, "picking_ids"):
                for p in so.picking_ids:
                    seq = (p.picking_type_id.sequence_code or "").upper()
                    if "PICK" in seq and p.state in ("confirmed", "assigned", "waiting"):
                        pick_pickings |= p

        return pick_pickings

    def _monitor_ai_score_priority(self, pick_pickings):
        """Use OpenAI to score priority for PICK pickings after IN validated.
        Returns dict {picking_id: '1'=urgent, '0'=normal}.
        Falls back to all-urgent if no API key or request fails.
        Configure key via Settings > Technical > Parameters:
          openai.api_key  or  hlv.openai.api_key
        """
        if not pick_pickings:
            return {}

        api_key = (
            self.env["ir.config_parameter"].sudo().get_param("openai.api_key")
            or self.env["ir.config_parameter"].sudo().get_param("hlv.openai.api_key")
        )
        if not api_key:
            _logger.info(
                "[HLV Monitor] No OpenAI API key — defaulting all PICKs to urgent after IN."
            )
            return {p.id: "1" for p in pick_pickings}

        try:
            import json as _json
            import requests
            from datetime import datetime

            now = datetime.now()
            picks_info = []
            for p in pick_pickings:
                so = p._monitor_find_related_sale()
                sched = p.scheduled_date
                picks_info.append({
                    "picking": p.name,
                    "partner": p.partner_id.name if p.partner_id else "N/A",
                    "order": so.name if so else (p.origin or "N/A"),
                    "order_value": so.amount_total if so else 0,
                    "scheduled_date": str(sched.date()) if sched else "N/A",
                    "overdue": bool(sched and sched < now),
                    "state": p.state,
                    "products_count": len(p.move_ids),
                })

            prompt = (
                "Bạn là hệ thống quản lý kho thông minh. Một phiếu nhập kho (IN) vừa hoàn thành, "
                "hàng đã có trong kho. Dưới đây là danh sách phiếu lấy hàng (PICK) liên quan.\n"
                "Đánh giá ưu tiên dựa trên: giá trị đơn, ngày giao, đã trễ hạn, khách quan trọng.\n"
                "Trả về JSON duy nhất (không giải thích):\n"
                '{"results": [{"picking": "...", "priority": 1}, ...]}\n'
                "priority=1: KHẨN CẤP, priority=0: BÌNH THƯỜNG\n\n"
                "Danh sách PICK:\n"
                + _json.dumps(picks_info, ensure_ascii=False, indent=2)
            )

            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": "Bearer %s" % api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 512,
                },
                timeout=12,
            )

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                data = _json.loads(content)
                name_map = {p.name: p.id for p in pick_pickings}
                scores = {}
                for item in data.get("results", []):
                    pid = name_map.get(item.get("picking"))
                    if pid:
                        scores[pid] = str(item.get("priority", 1))
                for p in pick_pickings:
                    scores.setdefault(p.id, "1")
                _logger.info("[HLV Monitor] AI priority scores: %s", scores)
                return scores
        except Exception as exc:
            _logger.warning("[HLV Monitor] AI priority scoring failed: %s", exc)

        return {p.id: "1" for p in pick_pickings}

    def _auto_prioritize_picks_after_in(self):
        """Orchestrate: find PICKs → AI-score → write priority → log event."""
        self.ensure_one()
        pick_pickings = self._find_related_picks_for_in()
        if not pick_pickings:
            return

        priority_scores = self._monitor_ai_score_priority(pick_pickings)

        for pick in pick_pickings:
            new_priority = priority_scores.get(pick.id, "1")
            if pick.priority != new_priority:
                try:
                    pick.sudo().write({"priority": new_priority})
                except Exception as exc:
                    _logger.warning(
                        "[HLV Monitor] Could not set priority on %s: %s", pick.name, exc
                    )

        urgent = [p for p in pick_pickings if priority_scores.get(p.id) == "1"]
        if not urgent:
            return

        MonitorEvent = self.env["warehouse.monitor.event"]
        warehouse = (
            self.picking_type_id.warehouse_id
            if self.picking_type_id
            else self.env["stock.warehouse"].browse()
        )
        pick_names = ", ".join(p.name for p in urgent[:5])
        extra = " (+%d nữa)" % (len(urgent) - 5) if len(urgent) > 5 else ""
        MonitorEvent._log_event({
            "name": "[AI-ƯU TIÊN] %s → PICK cần xử lý ngay" % self.name,
            "event_type": "pick",
            "action": "priority_set",
            "warehouse_id": warehouse.id if warehouse else False,
            "picking_id": self.id,
            "origin": self.origin or "",
            "summary": "Nhập kho %s hoàn thành → AI đánh dấu KHẨN CẤP: %s%s" % (
                self.name, pick_names, extra
            ),
            "suggestion": "⚡ AI-ƯU TIÊN: Lấy hàng ngay cho: %s%s" % (pick_names, extra),
            "priority": "urgent",
        })

    def _monitor_log_picking_event(self, action, state_before=None, state_after=None):
        """Log a stock.picking event to the monitor."""
        MonitorEvent = self.env["warehouse.monitor.event"]
        for picking in self:
            warehouse = (
                picking.picking_type_id.warehouse_id
                if picking.picking_type_id
                else self.env["stock.warehouse"].browse()
            )
            if not warehouse:
                continue

            event_type = picking._monitor_get_event_type()
            so = picking._monitor_find_related_sale()
            po = picking._monitor_find_related_purchase()

            action_labels = {
                "create": "Tạo mới",
                "confirm": "Xác nhận",
                "assign": "Sẵn sàng",
                "validate": "Hoàn thành",
                "cancel": "Hủy",
            }
            action_label = action_labels.get(action, action)

            event_type_labels = {
                "pick": "PICK",
                "pack": "PACK",
                "out": "OUT",
                "in": "IN",
                "internal": "Chuyển nội bộ",
            }
            type_label = event_type_labels.get(event_type, event_type)

            state_label = PICKING_STATE_LABELS.get(
                state_after or picking.state, state_after or picking.state
            )

            summary = "[%s] %s - %s [%s] - Kho: %s" % (
                type_label,
                picking.name,
                action_label,
                state_label,
                warehouse.name,
            )
            if picking.origin:
                summary += " - Gốc: %s" % picking.origin
            if picking.partner_id:
                summary += " - ĐT: %s" % picking.partner_id.name

            suggestion = picking._monitor_build_suggestion(event_type, action)
            product_summary = picking._monitor_build_product_summary()

            priority = "medium"
            if suggestion:
                priority = "high"
            if action == "validate" and event_type == "in":
                priority = "high"
            if action == "cancel":
                priority = "urgent"

            MonitorEvent._log_event({
                "name": "[%s] %s - %s" % (type_label, picking.name, action_label),
                "event_type": event_type,
                "action": action,
                "warehouse_id": warehouse.id,
                "picking_id": picking.id,
                "sale_id": so.id if so else False,
                "purchase_id": po.id if po else False,
                "origin": picking.origin or "",
                "state_before": PICKING_STATE_LABELS.get(state_before, state_before) if state_before else "",
                "state_after": state_label,
                "summary": summary,
                "suggestion": suggestion,
                "priority": priority,
                "product_summary": product_summary,
                "picking_type_code": (picking.picking_type_id.sequence_code or ""),
            })

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking in pickings:
            try:
                picking._monitor_log_picking_event("create", state_after=picking.state)
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking create: %s", picking.name)
        return pickings

    def action_assign(self):
        states_before = {p.id: p.state for p in self}
        result = super().action_assign()
        for picking in self:
            try:
                picking._monitor_log_picking_event(
                    "assign",
                    state_before=states_before.get(picking.id),
                    state_after=picking.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking assign: %s", picking.name)
        return result

    def button_validate(self):
        states_before = {p.id: p.state for p in self}
        result = super().button_validate()
        for picking in self:
            try:
                if picking.state == "done":
                    picking._monitor_log_picking_event(
                        "validate",
                        state_before=states_before.get(picking.id),
                        state_after=picking.state,
                    )
                    # After IN validated: auto-score and prioritize related PICKs (uses AI)
                    if picking._monitor_get_event_type() == "in":
                        picking._auto_prioritize_picks_after_in()
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking validate: %s", picking.name)
        return result

    def action_cancel(self):
        states_before = {p.id: p.state for p in self}
        result = super().action_cancel()
        for picking in self:
            try:
                picking._monitor_log_picking_event(
                    "cancel",
                    state_before=states_before.get(picking.id),
                    state_after=picking.state,
                )
            except Exception:
                _logger.exception("[HLV Monitor] Error logging picking cancel: %s", picking.name)
        return result
