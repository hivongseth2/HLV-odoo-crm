# -*- coding: utf-8 -*-
"""Dữ liệu trang "Lịch sử báo giá" của NCC: các dòng NCC đã báo (lọc theo chữ / ngày / sale / mặt hàng),
kết quả từng dòng, chỉ số tổng và thống kê theo mặt hàng. Đọc bằng sudo — gọi từ trang công khai, đã
khoá theo link của NCC (access)."""

from ..models.history_utils import WON_OUTCOMES, day_range_utc, line_outcome, success_rate
from ..models.purchase_order import CONFIRMED_STATES
from ..models.vendor_quote import VENDOR_VISIBLE_STATES
from ..models.vendor_quote_utils import price_incl_vat

# Thống kê tính trên tối đa chừng này dòng gần nhất trong bộ lọc — giữ trang nhanh với NCC báo rất nhiều.
STAT_LINE_LIMIT = 5000
# Phiếu đã có kết quả: bên mua lên YCMH / đóng / huỷ — dòng chưa được chọn coi như "không được chọn".
DECIDED_INQUIRY_STATES = ("requested", "closed", "cancel")


def history_domain(access, q="", day_from=None, day_to=None, sale_code="", product_id=0):
    """Domain dòng báo giá NCC đã gửi (báo giá có ngày gửi), lọc theo chữ (mã / tên hàng / số báo giá),
    khoảng ngày gửi (giờ VN), mã sale hỏi giá, mặt hàng."""
    domain = [
        ("quote_id.access_id", "=", access.id),
        ("quote_id.state", "in", VENDOR_VISIBLE_STATES),
        ("quote_id.submit_date", "!=", False),
        ("withdrawn", "=", False),
    ]
    start, end = day_range_utc(day_from, day_to)
    if start:
        domain.append(("quote_id.submit_date", ">=", start))
    if end:
        domain.append(("quote_id.submit_date", "<", end))
    if sale_code:
        domain.append(("quote_id.inquiry_id.sale_code", "=ilike", sale_code))
    if product_id:
        domain.append(("product_id", "=", product_id))
    if q:
        domain += ["|", "|", "|", ("product_id.default_code", "ilike", q), ("product_id.name", "ilike", q),
                   ("name", "ilike", q), ("quote_id.name", "ilike", q)]
    return domain


def search_lines(env, domain):
    """Dòng khớp bộ lọc, mới gửi trước; tối đa STAT_LINE_LIMIT. Trả (dòng, có bị cắt bớt không)."""
    QuoteLine = env["hlv.vendor.quote.line"].sudo()
    lines = QuoteLine.search(domain, order="id desc", limit=STAT_LINE_LIMIT + 1)
    return lines[:STAT_LINE_LIMIT].sorted(lambda l: (l.quote_id.submit_date, l.id), reverse=True), len(lines) > STAT_LINE_LIMIT


def line_facts(lines, vendor, requester):
    """Mỗi dòng → dict cho bảng lịch sử + thống kê. vendor: công ty NCC (res.partner); requester(mã sale)
    → "Tên – SĐT" người hỏi (có cache)."""
    facts = []
    for line in lines:
        orders = _vendor_orders(line, vendor)
        outcome = line_outcome(line.unavailable, bool(orders), line.selected, _decided(line))
        quote = line.quote_id
        facts.append({
            "line_id": line.id,
            "quote_id": quote.id,
            "quote_name": quote.name,
            "at": quote.submit_date,
            "sale": requester(quote.inquiry_id.sale_code),
            "product_id": line.product_id.id,
            "code": line.product_id.default_code or "",
            "product": line.name or line.product_id.display_name,
            "qty": line.product_qty,
            "uom": line.product_uom_id.name or "",
            "price_incl": price_incl_vat(line.price_unit, line.tax_rate) if not line.unavailable else 0.0,
            "outcome": outcome,
            "order_ids": set(orders.ids),
            "order_names": orders.mapped("name"),
        })
    return facts


def _vendor_orders(line, vendor):
    """Đơn mua đã xác nhận của chính NCC này có mặt hàng của dòng (qua dòng YCMH của mặt hàng)."""
    return line._hlv_product_request_lines().purchase_lines.filtered(
        lambda l: l.product_qty > 0 and l.order_id.state in CONFIRMED_STATES
        and l.order_id.partner_id.commercial_partner_id == vendor
    ).order_id


def _decided(line):
    """Bên mua đã quyết cho mặt hàng này chưa: báo giá đã đóng, phiếu đã lên YCMH / đóng / huỷ, hoặc đã chọn
    NCC khác (luồng phiếu hỏi giá) / đã chốt NCC trên dòng YCMH (luồng hỏi từ YCMH)."""
    if line.quote_id.state == "done":
        return True
    inquiry_line = line.inquiry_line_id
    if inquiry_line:
        return inquiry_line.inquiry_id.state in DECIDED_INQUIRY_STATES or bool(inquiry_line.chosen_line_ids - line)
    return bool(line.request_line_id.actual_supplier_id)


def summarize(facts):
    """Chỉ số tổng: số lần báo giá (báo giá khác nhau), lượt mặt hàng được hỏi / có giá, được chọn hoặc lên
    đơn, tỉ lệ thành công, số đơn mua khác nhau."""
    won = sum(1 for f in facts if f["outcome"] in WON_OUTCOMES)
    lost = sum(1 for f in facts if f["outcome"] == "lost")
    orders = set()
    for f in facts:
        orders |= f["order_ids"]
    return {
        "quotes": len({f["quote_id"] for f in facts}),
        "asked": len(facts),
        "priced": sum(1 for f in facts if f["outcome"] != "na"),
        "won": won,
        "rate": success_rate(won, lost),
        "orders": len(orders),
    }


def sale_options(access, requester):
    """[(mã sale, "Tên – SĐT")] các sale từng hỏi giá NCC này — cho ô lọc "theo sale"."""
    codes = sorted({code.upper() for code in access.quote_ids.inquiry_id.mapped("sale_code") if code})
    return [(code, requester(code) or code) for code in codes]
