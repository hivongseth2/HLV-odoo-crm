# -*- coding: utf-8 -*-
"""Giao hàng từng đợt của đơn mua lên từ báo giá NCC (NCC thiếu hàng / hẹn giao phần còn lại):

- Kho nhận một phần → đơn "Đã giao một phần", mở đợt mới: tiến độ NCC về chờ đóng gói, thông tin gửi
  của đợt trước ghi vào chatter; báo NCC phần còn lại + báo sale.
- NCC đổi ngày giao dự kiến của hàng còn chờ trên trang NCC → tự cập nhật ngày trên đơn mua (đường chuẩn
  Odoo: hoạt động "Date Updated" cho người mua) + ngày phiếu nhập chờ; ghi chatter (không email), báo sale.
- Cron hằng ngày: hàng quá ngày hẹn mà kho chưa nhận → báo sale, người mua, NCC — mỗi dòng một lần / ngày.
"""

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.chat_bus import notify_order_status
from ..services.notify import log_internal
from ..services.vendor_chat import post_chat
from .delivery_utils import due_datetime, due_day_error, is_late, local_day, pending_text, remaining_qty
from .purchase_order import CONFIRMED_STATES
from .vendor_quote_utils import DATE_FMT


class PurchaseOrderDelivery(models.Model):
    _inherit = "purchase.order"

    # Việc mới nhất về giao hàng (giao một phần / NCC đổi ngày / trễ hẹn) — hiện trong chuông + popup trang
    # sale. Xoá khi NCC báo tiến độ bình thường (đóng gói / gửi hàng / đã giao).
    hlv_vendor_event = fields.Char(string="Tin giao hàng gần nhất", copy=False, readonly=True)

    # ------------------------------------------------------------------ đọc
    def _hlv_pending_lines(self):
        """Dòng hàng (không phải dịch vụ / dòng ghi chú) còn chờ giao."""
        self.ensure_one()
        return self.sudo().order_line.filtered(
            lambda l: not l.display_type and l.product_id.type != "service"
            and remaining_qty(l.product_qty, l.qty_received) > 0
        )

    def _hlv_partly_received(self):
        """Kho đã nhận một phần: có phiếu nhập đã xong, còn phiếu nhập chờ."""
        self.ensure_one()
        receipts = self.sudo().picking_ids.filtered(lambda p: p.picking_type_code == "incoming" and p.state != "cancel")
        return any(p.state == "done" for p in receipts) and any(p.state != "done" for p in receipts)

    def _hlv_pending_text(self, lines=None):
        """"Phốt dầu 4 Cái hẹn 20/10/2026; …" cho hàng còn chờ (hoặc lines)."""
        lines = self._hlv_pending_lines() if lines is None else lines
        return pending_text([
            (l.product_id.display_name, remaining_qty(l.product_qty, l.qty_received), l.product_uom.name or "",
             local_day(l.date_planned)) for l in lines
        ])

    def _hlv_pending_info(self):
        """Hàng còn chờ giao cho trang NCC: [{line_id, name, remaining, uom, due (yyyy-mm-dd), due_text, late}]."""
        today = self.env["hlv.vendor.quote"]._vendor_today()
        info = []
        for line in self._hlv_pending_lines():
            rest = remaining_qty(line.product_qty, line.qty_received)
            day = local_day(line.date_planned)
            info.append({
                "line_id": line.id,
                "name": line.hlv_invoice_name or line.product_id.display_name,
                "remaining": rest,
                "uom": line.product_uom.name or "",
                "due": day.isoformat() if day else "",
                "due_text": day.strftime(DATE_FMT) if day else "",
                "late": is_late(day, today, rest),
            })
        return info

    def _hlv_vendor_progress(self):
        """Thêm "partial" (đã giao một phần): kho nhận một phần, NCC chưa báo gì cho đợt sau."""
        progress = super()._hlv_vendor_progress()
        if progress == "waiting" and self._hlv_partly_received():
            return "partial"
        return progress

    def _hlv_vendor_stage(self):
        """Đã giao một phần nằm tab "Chờ đóng gói" — phần còn lại là việc NCC cần làm."""
        stage = super()._hlv_vendor_stage()
        return "waiting" if stage == "partial" else stage

    def _hlv_advance_status(self, status, author, body, notify_staff=True, source="vendor"):
        """NCC báo tiến độ bình thường → tin giao hàng cũ (giao một phần / đổi ngày / trễ hẹn) hết thời sự."""
        if self.hlv_vendor_event:
            self.hlv_vendor_event = False
        return super()._hlv_advance_status(status, author, body, notify_staff=notify_staff, source=source)

    # ------------------------------------------------------------------ kho nhận một phần → đợt mới
    def _hlv_mark_delivered_by_receipt(self):
        super()._hlv_mark_delivered_by_receipt()
        # Chỉ đơn lên từ báo giá NCC — đơn mua thường (MISA…) nhận thiếu thì để nguyên như cũ.
        for order in self.sudo().filtered(lambda o: o.state in CONFIRMED_STATES and not o._hlv_receipts_done()):
            if order._hlv_partly_received() and order.hlv_vendor_quote_ids:
                order._hlv_start_next_batch()

    def _hlv_start_next_batch(self):
        """Kho vừa nhận một đợt, còn hàng chờ: đưa tiến độ NCC về chờ đóng gói cho đợt sau, ghi lại thông
        tin gửi của đợt vừa nhận, báo NCC phần còn lại và báo sale."""
        self.ensure_one()
        pending = self._hlv_pending_text()
        done_ship = self._hlv_ship_text()
        event = _("Kho đã nhận một phần — còn chờ: %s", pending)
        self.write({
            "hlv_vendor_status": False, "hlv_ship_method": False, "hlv_ship_carrier": False, "hlv_ship_ref": False,
            "hlv_vendor_status_date": fields.Datetime.now(), "hlv_vendor_event": event, "hlv_vendor_event_source": "system",
        })
        body = Markup(_("Kho đã nhận một phần%(ship)s. Còn chờ giao: <b>%(pending)s</b> — tiến độ NCC về chờ đóng gói cho đợt sau.")) % {
            "ship": Markup(_(" (đợt vừa nhận: %s)")) % done_ship if done_ship else "", "pending": pending,
        }
        log_internal(self, body, self.env.user.partner_id)
        notify_order_status(self)
        self._hlv_notify_vendor(lambda o: _(
            "Kho đã nhận một phần đơn %(name)s. Còn chờ giao: %(pending)s. Chuẩn bị đợt sau, %(next)s; đổi được ngày "
            "giao dự kiến ngay trên trang đơn mua.", name=o.name, pending=pending, next=o._hlv_vendor_next_hint(),
        ))

    # ------------------------------------------------------------------ NCC đổi ngày giao
    def _vendor_set_due_dates(self, due_days, vendor_partner):
        """NCC đổi ngày giao dự kiến của hàng còn chờ. due_days: {id dòng đơn mua: date}. Dòng không đổi bỏ
        qua; dòng không còn chờ / ngày sai → UserError. Ghi bằng sudo (NCC trên trang công khai)."""
        self.ensure_one()
        self._hlv_check_vendor_can_update()
        order = self.sudo()
        pending = order._hlv_pending_lines()
        today = order.env["hlv.vendor.quote"]._vendor_today()
        changes = []
        for line_id, new_day in due_days.items():
            line = pending.filtered(lambda l, i=line_id: l.id == i)
            if not line:
                raise UserError(_("Mặt hàng này đã giao đủ hoặc không thuộc đơn %s.", order.name))
            error = due_day_error(new_day, today)
            if error:
                raise UserError(_("%(product)s: %(error)s.", product=line.product_id.display_name, error=error))
            if new_day != local_day(line.date_planned):
                changes.append((line, local_day(line.date_planned), new_day))
        if not changes:
            return False
        order._hlv_apply_due_dates(changes)
        # Ghi vào khung trao đổi của đơn (NCC + bên mua cùng xem) — không gọi tên ai, không email.
        items = "\n".join(
            f"- {line.product_id.display_name}: {old.strftime(DATE_FMT) if old else '—'} → {new.strftime(DATE_FMT)}"
            for line, old, new in changes)
        post_chat(order, _("NCC đổi ngày giao dự kiến (tự cập nhật vào đơn):\n%s", items), vendor_partner,
                  from_vendor=True, notify=False)
        order.write({
            "hlv_vendor_status_date": fields.Datetime.now(),
            "hlv_vendor_event_source": "vendor",
            "hlv_vendor_event": _("NCC đổi ngày giao: %s", "; ".join(
                f"{line.product_id.display_name} → {new.strftime(DATE_FMT)}" for line, _old, new in changes)),
        })
        notify_order_status(order)
        return True

    def _hlv_apply_due_dates(self, changes):
        """Ghi ngày mới lên dòng đơn mua + hàng chờ nhận (ngày phiếu nhập). Có người mua: qua đường chuẩn
        _update_date_planned_for_lines (thêm hoạt động "Date Updated" giao người mua); không có thì ghi thẳng —
        hoạt động sẽ giao nhầm cho người đang thao tác (trên trang NCC là user công khai)."""
        # Chỉ dời ngày — không đánh dấu thay chứng từ MISA (amis_callback theo dõi date_planned trên dòng đơn mua;
        # tiền / số lượng không đổi thì không đẩy lại MISA).
        dated = [(line.with_context(skip_misa_purchase_order_lifecycle=True), due_datetime(new, line.date_planned))
                 for line, _old, new in changes]
        if self.user_id:
            # mail_activity_quick_update: hoạt động "Date Updated" cho người mua không kèm email báo giao việc.
            self.with_context(mail_activity_quick_update=True)._update_date_planned_for_lines(dated)
        else:
            for line, when in dated:
                line._update_date_planned(when)
        for line, when in dated:
            # Chuẩn Odoo chỉ dời hạn chót (date_deadline); dời cả ngày dự kiến để phiếu nhập hiện đúng lịch.
            line.move_ids.filtered(lambda m: m.state not in ("done", "cancel")).write({"date": when})

    # ------------------------------------------------------------------ trễ hẹn
    @api.model
    def _cron_hlv_late_deliveries(self):
        """Hằng ngày: đơn mua lên từ báo giá NCC có hàng quá ngày hẹn mà kho chưa nhận → báo sale (chuông),
        người mua (thông báo Odoo), NCC (tin nhắn nhắc cập nhật ngày giao). Mỗi dòng một lần / ngày."""
        today = self.env["hlv.vendor.quote"]._vendor_today()
        orders = self.sudo().search([("state", "in", CONFIRMED_STATES), ("receipt_status", "!=", "full")])
        for order in orders:
            late = order._hlv_pending_lines().filtered(
                lambda l: is_late(local_day(l.date_planned), today, remaining_qty(l.product_qty, l.qty_received))
                and l.hlv_late_notified != today
            )
            # Lọc dòng trễ trước, tra liên kết báo giá sau (tốn truy vấn hơn) — chỉ đơn lên từ báo giá NCC.
            if late and order.hlv_vendor_quote_ids:
                order._hlv_report_late(late, today)

    def _hlv_buyer_activity(self, summary, note):
        """Báo người mua của đơn bằng hoạt động trong Odoo — KHÔNG email (mail_activity_quick_update bỏ thư báo giao
        việc). Đơn đã có hoạt động mở cùng tiêu đề thì cập nhật nội dung, không đẻ thêm. Không có người mua → bỏ qua."""
        self.ensure_one()
        if not self.user_id:
            return
        existing = self.activity_ids.filtered(lambda a: a.summary == summary and a.user_id == self.user_id)[:1]
        if existing:
            existing.with_context(mail_activity_quick_update=True).note = note
        else:
            self.with_context(mail_activity_quick_update=True).activity_schedule(
                "mail.mail_activity_data_warning", summary=summary, note=note, user_id=self.user_id.id,
            )

    def _hlv_report_late(self, lines, today):
        self.ensure_one()
        text = self._hlv_pending_text(lines)
        lines.write({"hlv_late_notified": today})
        self.write({"hlv_vendor_status_date": fields.Datetime.now(), "hlv_vendor_event": _("Trễ hẹn giao: %s", text),
                    "hlv_vendor_event_source": "system"})
        self._hlv_buyer_activity(_("Trễ hẹn giao"), Markup(_("<b>Trễ hẹn giao</b>: %s — kho chưa nhận.")) % text)
        notify_order_status(self)
        self._hlv_notify_vendor(lambda o: _(
            "Đơn %(name)s đã quá ngày hẹn giao: %(items)s. Vui lòng giao hàng hoặc cập nhật ngày giao dự kiến trên "
            "trang đơn mua.", name=o.name, items=text,
        ))


class PurchaseOrderLineDelivery(models.Model):
    _inherit = "purchase.order.line"

    hlv_late_notified = fields.Date(string="Đã báo trễ hẹn ngày", copy=False, readonly=True)
