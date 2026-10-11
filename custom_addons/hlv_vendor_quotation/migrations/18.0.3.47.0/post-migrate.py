# -*- coding: utf-8 -*-
"""Chọn nhiều NCC cho một sản phẩm (phiếu hỏi giá) — chuyển dữ liệu cũ (một NCC / sản phẩm):

1. SL cần mua (need_qty) = SL hỏi.
2. Liên kết YCMH chuyển từ dòng phiếu (cột cũ request_line_id, field đã bỏ) sang dòng báo giá của NCC:
   NCC đang chọn đã trỏ sẵn; dòng YCMH không NCC nào trỏ (NCC bị bỏ chọn khi YCMH bị từ chối) thì gắn
   vào dòng báo giá của đúng NCC trên dòng YCMH — để vẫn thấy YCMH nào bị từ chối.
3. NCC đang chọn: SL mua = SL trên dòng YCMH của NCC (không quá SL hỏi — dòng YCMH có thể gộp hàng phiếu
   khác), chưa lên YCMH thì = SL hỏi. Sản phẩm đã lên YCMH: SL cần mua = tổng SL mua (luồng cũ chưa có
   "còn thiếu" — sửa SL khi lên YCMH, hỏi 10 mua 5, nghĩa là khách chỉ mua 5).
4. YCMH lên từ trang hỏi giá chỉ có cột thu mua (actual_*) — điền bù bộ cột "sale đề xuất" (NCC / giá /
   thuế) từ giá sale đã chọn, chỉ dòng còn trống để không đè số ai đã sửa tay.
5. Tính lại tình trạng phiếu (thêm "Lên YCMH một phần").
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("UPDATE hlv_vendor_inquiry_line SET need_qty = product_qty WHERE need_qty IS NULL")
    env.invalidate_all()
    _relink_request_lines(env)
    QuoteLine = env["hlv.vendor.quote.line"]
    chosen = QuoteLine.search([("selected", "=", True), ("inquiry_line_id", "!=", False), ("chosen_qty", "=", 0)])
    for line in chosen:
        asked = line.inquiry_line_id.product_qty
        request_line = line._hlv_live_request_lines()[:1]
        line.chosen_qty = min(request_line.product_qty, asked) if request_line else asked
    for inquiry_line in chosen.inquiry_line_id.filtered(lambda l: l._hlv_live_request_lines()):
        inquiry_line.need_qty = inquiry_line._hlv_chosen_total()
    for line in QuoteLine.search([
        ("selected", "=", True),
        ("inquiry_line_id", "!=", False),
        ("request_line_id.request_id.hlv_from_quote_page", "=", True),
        ("request_line_id.sale_proposed_supplier_id", "=", False),
        ("request_line_id.misa_price_before_tax", "=", 0),
    ]):
        line.request_line_id.write(line._request_line_proposal_vals())
    inquiries = env["hlv.vendor.inquiry"].search([])
    env.add_to_compute(inquiries._fields["sale_status"], inquiries)
    inquiries.flush_recordset(["sale_status"])


def _relink_request_lines(env):
    cr = env.cr
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'hlv_vendor_inquiry_line' AND column_name = 'request_line_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("SELECT id, request_line_id FROM hlv_vendor_inquiry_line WHERE request_line_id IS NOT NULL")
    for inquiry_line_id, request_line_id in cr.fetchall():
        line = env["hlv.vendor.inquiry.line"].browse(inquiry_line_id).exists()
        request_line = env["purchase.request.line"].browse(request_line_id).exists()
        if not line or not request_line or request_line in line.quote_line_ids._hlv_own_request_lines():
            continue
        vendor = request_line.actual_supplier_id.commercial_partner_id
        target = line.quote_line_ids.filtered(
            lambda q: not q.request_line_id and q.partner_id.commercial_partner_id == vendor
        )[:1]
        if target:
            target.request_line_id = request_line
