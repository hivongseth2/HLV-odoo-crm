# -*- coding: utf-8 -*-
import time

from odoo import Command, api, fields, models
from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number

from .misa_invoice_utils import (DETAIL_URL, LIST_URL, MAX_PAGES, amounts_by_order, debt_share, detail_payload,
                                 is_last_page, list_payload, normalize_tax_code, parse_invoice_row)
from .payment_utils import PAID_TOLERANCE

# Lúc bắt đầu lượt lấy hoá đơn MISA cho mọi NCC (UTC) — NCC lấy xong trước lúc này coi như chưa lấy trong lượt.
ROUND_START_PARAM = "hlv_vendor_payment_docs.misa_round_start"


class MisaPurchaseInvoice(models.Model):
    """Sổ hoá đơn mua vào ĐÃ THANH TOÁN lấy từ MISA (kế toán trả trên MISA, không qua đề nghị chi của Odoo) — mỗi
    hoá đơn một dòng, khoá MST + số HĐ. Lấy lại nhiều lần không ghi trùng; hoá đơn đã ghi nhận mà MISA bỏ thanh toán
    thì đánh dấu để kế toán xem (không tự huỷ phiếu).

    Tiền hoá đơn chia ba phần: ghi công nợ (thành phiếu thanh toán công nợ), đã trả qua đề nghị chi / phiếu khác (đơn
    hết nợ — không đếm lần hai), và không khớp (đơn trước mốc công nợ, đơn chỉ có trên MISA, dòng không gắn đơn)."""

    _name = "hlv.misa.purchase.invoice"
    _description = "Hoá đơn mua vào MISA đã thanh toán"
    _order = "inv_date desc, id desc"

    key = fields.Char(string="Khoá MST_số HĐ", required=True, index=True, readonly=True)
    refid = fields.Char(string="MISA refid", index=True, readonly=True)
    partner_id = fields.Many2one("res.partner", string="NCC", required=True, index=True, readonly=True)
    tax_code = fields.Char(string="MST", readonly=True)
    vendor_name = fields.Char(string="Tên NCC trên MISA", readonly=True)
    inv_no = fields.Char(string="Số hoá đơn", readonly=True)
    inv_date = fields.Date(string="Ngày hoá đơn", readonly=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(string="Tổng hoá đơn", readonly=True)
    debt_amount = fields.Monetary(string="Ghi công nợ", readonly=True)
    covered_amount = fields.Monetary(string="Đã trả qua ĐNC / phiếu khác", readonly=True)
    unmatched_amount = fields.Monetary(string="Không khớp đơn", readonly=True)
    state = fields.Selection([
        ("imported", "Đã ghi công nợ"),
        ("covered", "Đã trả qua đề nghị chi"),
        ("no_order", "Không khớp đơn"),
        ("unpaid_again", "MISA bỏ thanh toán"),
    ], string="Kết quả", required=True, index=True, readonly=True)
    debt_payment_id = fields.Many2one("hlv.vendor.debt.payment", string="Phiếu công nợ", readonly=True,
                                      ondelete="set null")
    note = fields.Text(string="Chi tiết", readonly=True)

    _sql_constraints = [
        ("key_unique", "UNIQUE(key)", "Hoá đơn (MST + số HĐ) này đã có trong sổ hoá đơn MISA."),
    ]

    # ------------------------------------------------------------------ gọi MISA
    @api.model
    def _hlv_misa_pages(self, url, make_payload, context):
        """Mọi dòng của một lệnh tìm MISA, lật trang tới khi hết. make_payload(page) → body. Lỗi phiên / MISA trả
        Success=false → raise (không coi là "không có dữ liệu")."""
        utils = self.env["misa.api.utils"]
        rows = []
        for page in range(1, MAX_PAGES + 1):
            data = utils._fetch_misa_json_with_session_retry(url, make_payload(page), context)
            page_rows = ((data or {}).get("Data") or {}).get("PageData") or []
            rows.extend(page_rows)
            if is_last_page(page_rows):
                break
        return rows

    @api.model
    def _hlv_vendor_invoices(self, vendor, date_from, date_to):
        """Hoá đơn mua vào của NCC trên MISA trong khoảng ngày (đã parse_invoice_row), chỉ đúng MST của NCC.
        Ô tìm nhanh MISA tìm kiểu CHỨA trên chuỗi MISA lưu: gửi MST NGUYÊN DẠNG (MST chi nhánh "0107338930-001" — bỏ
        gạch đi thì không khớp), rồi phần MST chính trước gạch, rồi tên; dừng ở lần đầu ra hoá đơn đúng MST. Kết quả
        luôn lọc lại đúng MST (đã chuẩn hoá) — tìm rộng không lẫn NCC khác."""
        tax = normalize_tax_code(vendor.vat)
        raw_vat = (vendor.vat or "").strip()
        searches = list(dict.fromkeys(term for term in (raw_vat, raw_vat.split("-")[0].strip(), vendor.name) if term))
        found = {}
        for search in searches:
            rows = self._hlv_misa_pages(
                LIST_URL, lambda page, s=search: list_payload(date_from, date_to, s, page),
                "pu_invoice %s" % search)
            for invoice in map(parse_invoice_row, rows):
                if invoice["tax_code"] == tax and invoice["key"]:
                    found[invoice["key"]] = invoice
            if found:
                break
        return sorted(found.values(), key=lambda inv: (inv["inv_date"] or fields.Date.today(), inv["inv_no"]))

    # ------------------------------------------------------------------ ghi nhận
    @api.model
    def _hlv_sync_vendor(self, vendor, deadline):
        """Lấy hoá đơn của NCC từ mốc công nợ tới hôm nay, ghi nhận hoá đơn đã thanh toán chưa có trong sổ, đánh dấu
        hoá đơn đã ghi mà MISA bỏ thanh toán. deadline: time.monotonic() phải dừng đọc chi tiết (giới hạn thời gian một
        lần bấm) — hoá đơn chưa kịp đọc để lần sau.
        Trả dict: found (hoá đơn của NCC), paid, new, debt (tiền ghi công nợ), unpaid_again, pending (chưa kịp)."""
        cutoff = self.env["purchase.order"]._hlv_debt_cutoff()
        invoices = self._hlv_vendor_invoices(vendor, cutoff, fields.Date.context_today(self))
        existing = {rec.key: rec for rec in self.search([("key", "in", [inv["key"] for inv in invoices])])}
        stats = {"found": len(invoices), "paid": 0, "new": 0, "debt": 0.0, "unpaid_again": 0, "pending": 0}
        for invoice in invoices:
            record = existing.get(invoice["key"])
            if not invoice["is_paid"]:
                if record and record.state == "imported":
                    record.state = "unpaid_again"
                    stats["unpaid_again"] += 1
                continue
            stats["paid"] += 1
            if record:
                if record.state == "unpaid_again":
                    record.state = "imported"  # MISA thanh toán lại — phiếu cũ vẫn đúng
                continue
            if time.monotonic() > deadline:
                stats["pending"] += 1
                continue
            lines = self._hlv_misa_pages(DETAIL_URL, lambda page, r=invoice["refid"]: detail_payload(r, page),
                                         "pu_invoice detail %s" % invoice["inv_no"])
            record = self._hlv_record_invoice(vendor, invoice, lines)
            stats["new"] += 1
            stats["debt"] += record.debt_amount
        return stats

    @api.model
    def _hlv_record_invoice(self, vendor, invoice, lines):
        """Ghi một hoá đơn đã thanh toán: chia tiền theo đơn mua, phần đơn còn nợ thành phiếu thanh toán công nợ
        (nguồn MISA), phần còn lại ghi vào sổ để đối chiếu. Trả bản ghi sổ vừa tạo."""
        per_order = amounts_by_order(lines)
        Order = self.env["purchase.order"].sudo()
        orders = {order.name: order for order in Order.search([
            ("name", "in", [refno for refno in per_order if refno]),
            ("partner_id", "child_of", vendor.id), ("state", "in", CONFIRMED_STATES)])}
        debt_lines, covered, unmatched, notes = [], 0.0, 0.0, []
        for refno, amount in sorted(per_order.items()):
            order = orders.get(refno)
            if not order or not order._hlv_debt_tracked():
                unmatched += amount
                reason = "dòng không gắn đơn mua" if not refno else (
                    "đơn trước mốc công nợ" if order else "đơn không có trong Odoo")
                notes.append(f"{refno or '—'}: {format_vn_number(round(amount))} — {reason}")
                continue
            share = debt_share(amount, order._hlv_open_amount())
            covered += amount - share
            if share > PAID_TOLERANCE:
                debt_lines.append(Command.create({"purchase_order_id": order.id, "amount": share}))
            notes.append(f"{refno}: {format_vn_number(round(amount))} — ghi công nợ {format_vn_number(share)}"
                         + (f", đã trả qua ĐNC / phiếu khác {format_vn_number(round(amount - share))}"
                            if amount - share > PAID_TOLERANCE else ""))
        payment = self.env["hlv.vendor.debt.payment"]
        if debt_lines:
            payment = payment.sudo().create({
                "partner_id": vendor.id,
                "amount": sum(command[2]["amount"] for command in debt_lines),
                "payment_date": invoice["inv_date"] or fields.Date.context_today(self),
                "payment_method": "bank",
                "source": "misa",
                "memo": f"Hoá đơn {invoice['inv_no']}"
                        + (f" ngày {invoice['inv_date'].strftime('%d/%m/%Y')}" if invoice["inv_date"] else "")
                        + " — đã thanh toán trên MISA",
                "line_ids": debt_lines,
            })
        state = "imported" if payment else ("covered" if covered > PAID_TOLERANCE else "no_order")
        return self.create({
            "key": invoice["key"],
            "refid": invoice["refid"],
            "partner_id": vendor.id,
            "tax_code": invoice["tax_code"],
            "vendor_name": invoice["vendor_name"],
            "inv_no": invoice["inv_no"],
            "inv_date": invoice["inv_date"],
            "amount": invoice["amount"],
            "debt_amount": payment.amount if payment else 0.0,
            "covered_amount": covered,
            "unmatched_amount": unmatched,
            "state": state,
            "debt_payment_id": payment.id or False,
            "note": "\n".join(notes),
        })

    # ------------------------------------------------------------------ lượt lấy cho mọi NCC
    @api.model
    def _hlv_round_start(self):
        """Lúc bắt đầu lượt lấy cho mọi NCC đang chạy (UTC); chưa từng bắt đầu → None (NCC chưa lấy lần nào là còn)."""
        value = self.env["ir.config_parameter"].sudo().get_param(ROUND_START_PARAM)
        return fields.Datetime.to_datetime(value) if value else None

    @api.model
    def _hlv_start_round(self):
        self.env["ir.config_parameter"].sudo().set_param(ROUND_START_PARAM, fields.Datetime.to_string(fields.Datetime.now()))

    @api.model
    def _hlv_round_vendors(self):
        """(mọi NCC có tài khoản vendor + MST, NCC chưa lấy trong lượt này) — res.partner pháp nhân."""
        accesses = self.env["hlv.vendor.quote.access"].sudo().search([])
        vendors = accesses.partner_id.commercial_partner_id.filtered(lambda p: normalize_tax_code(p.vat))
        start = self._hlv_round_start()
        done = accesses.filtered(
            lambda a: a.hlv_misa_synced_at and (not start or a.hlv_misa_synced_at >= start)
        ).partner_id.commercial_partner_id
        return vendors, vendors - done

    @api.model
    def _hlv_mark_synced(self, vendor):
        self.env["hlv.vendor.quote.access"].sudo().search([("partner_id", "child_of", vendor.id)]).write(
            {"hlv_misa_synced_at": fields.Datetime.now()})

    @api.model
    def _hlv_sync_one(self, vendor, deadline):
        """Lấy cho một NCC; xong hết (không còn hoá đơn chờ đọc) thì đánh dấu đã lấy trong lượt. Trả stats."""
        stats = self._hlv_sync_vendor(vendor, deadline)
        if not stats["pending"]:
            self._hlv_mark_synced(vendor)
        return stats

    @api.model
    def _hlv_sync_round(self, deadline):
        """Lấy tiếp các NCC chưa lấy trong lượt, tới khi hết giờ. Trả {vendors, new, debt, unpaid_again}."""
        _vendors, pending = self._hlv_round_vendors()
        totals = {"vendors": 0, "new": 0, "debt": 0.0, "unpaid_again": 0}
        for vendor in pending.sorted("name"):
            if time.monotonic() > deadline:
                break
            stats = self._hlv_sync_one(vendor, deadline)
            totals["vendors"] += 0 if stats["pending"] else 1
            for key in ("new", "debt", "unpaid_again"):
                totals[key] += stats[key]
        return totals
