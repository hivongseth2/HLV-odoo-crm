# Chạy lại ô tìm của /hoi-gia-ncc cho một mã sale + một chuỗi tìm, từng bước như controller
# (hlv_vendor_quotation/controllers/sale_page.py api_inquiries → _scoped_search_domain), để biết vì sao
# sale tìm số đơn mua mà không ra phiếu.
# Ca 04/11/2026: NGUYỄN THỊ TRÂM gõ "24670" không ra.
#
# In ra:
#   1. mã sale của các tài khoản tên có TRAM (đúng mã trang đang gửi lên chưa);
#   2. đơn mua khớp chuỗi tìm → dòng YCMH → "Người yêu cầu" của YCMH → dòng phiếu hỏi giá → phiếu + mã sale phiếu;
#   3. kết quả _purchase_order_inquiry_ids (lọc theo người yêu cầu) và cả không lọc;
#   4. domain cuối cùng + số phiếu từng tab như trang hiện, và kiểm mở phiếu (_inquiry_in_scope).
#
# CHỈ ĐỌC — không ghi gì.
# CÁCH CHẠY: sửa CẤU HÌNH, copy TOÀN BỘ file dán vào `odoo-bin shell` (notebook Odoo-shell).
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
SALE_CODE = "NGUYENTHITRAM"   # mã sale trang /hoi-gia-ncc gửi lên (ô "Sale" đang chọn)
SEARCH = "24670"
NAME_HINT = "TRAM"            # tìm tài khoản có mã sale chứa chữ này, để đối chiếu SALE_CODE
# ─────────────────────────────────────────────────────────────────────────────

from odoo.osv import expression
from odoo.addons.hlv_vendor_quotation.controllers import sale_page as sp
from odoo.addons.hlv_vendor_quotation.controllers.sale_page_common import SalePageMixin
from odoo.addons.hlv_vendor_quotation.services import sale_scope

Inquiry = env["hlv.vendor.inquiry"].sudo()
PRL = env["purchase.request.line"].sudo()
PO = env["purchase.order"].sudo()
REQ_FIELD = "request_id.x_misa_requested_by"


def head(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


# ── 1. Mã sale ───────────────────────────────────────────────────────────────
head("1. TÀI KHOẢN CÓ MÃ SALE CHỨA %r" % NAME_HINT)
for user in env["res.users"].sudo().with_context(active_test=False).search([("x_misa_saler_codes", "ilike", NAME_HINT)]):
    print("  %s (login %s, active=%s): x_misa_saler_codes=%r" % (user.name, user.login, user.active, user.x_misa_saler_codes))
code = SALE_CODE.strip()
print("  → test với mã: %r" % code)

# ── 2. Đơn mua khớp → YCMH → phiếu ───────────────────────────────────────────
head("2. ĐƠN MUA tên chứa %r → dòng YCMH → người yêu cầu → phiếu hỏi giá" % SEARCH)
print("  khớp regex số đơn mua (DMH/PO/P0): %s   khớp 'chỉ số' (>=3 chữ số): %s"
      % (bool(sp.PURCHASE_ORDER_NUMBER.match(SEARCH)), bool(sp.NUMBER_ONLY.match(SEARCH))))
orders = PO.search([("name", "ilike", SEARCH)], limit=20)
if not orders:
    print("  !! Không có đơn mua nào tên chứa %r" % SEARCH)
match_dom = sale_scope.requester_scope_domain(code, "x_misa_requested_by")
print("  domain người yêu cầu: %s" % match_dom)
for order in orders:
    print("\n  %s  NCC=%s  state=%s  origin=%s" % (order.name, order.partner_id.display_name, order.state, order.origin or "-"))
    req_lines = order.order_line.purchase_request_lines
    if not req_lines:
        print("     !! dòng đơn mua KHÔNG gắn dòng YCMH nào → ô tìm không bao giờ ra (đi qua dòng YCMH)")
    for rl in req_lines:
        req = rl.request_id
        hit = bool(env["purchase.request"].sudo().search_count([("id", "=", req.id)] + match_dom))
        inq_lines = env["hlv.vendor.inquiry.line"].sudo().search([("request_line_ids", "in", rl.id)])
        print("     dòng YCMH %s  %s  YCMH=%s  người yêu cầu=%r  → khớp mã %s: %s"
              % (rl.id, rl.product_id.default_code or rl.name, req.name, req.x_misa_requested_by, code,
                 "CÓ" if hit else "KHÔNG"))
        if not inq_lines:
            print("        !! dòng YCMH không nằm trên dòng phiếu hỏi giá nào (request_line_ids) → không có phiếu để hiện")
        for il in inq_lines:
            print("        phiếu %s (id %s)  mã sale phiếu=%r  state=%s  sale_status=%s"
                  % (il.inquiry_id.name, il.inquiry_id.id, il.inquiry_id.sale_code, il.inquiry_id.state,
                     il.inquiry_id.sale_status))

# ── 3. _purchase_order_inquiry_ids ───────────────────────────────────────────
head("3. _purchase_order_inquiry_ids (như controller)")
rl_dom = [("purchase_lines.order_id.name", "ilike", SEARCH)] + sale_scope.requester_scope_domain(code, REQ_FIELD)
po_ids = Inquiry.search([("line_ids.request_line_ids", "any", rl_dom)]).ids
print("  lọc theo người yêu cầu %r: %s" % (code, Inquiry.browse(po_ids).mapped("name")))
no_filter = Inquiry.search([("line_ids.request_line_ids", "any", [("purchase_lines.order_id.name", "ilike", SEARCH)])])
print("  KHÔNG lọc người yêu cầu:   %s" % ["%s(%s)" % (i.name, i.sale_code) for i in no_filter])

# ── 4. Domain cuối + tab ─────────────────────────────────────────────────────
head("4. DOMAIN CUỐI + SỐ PHIẾU TỪNG TAB")
scope_dom = sale_scope.scope_domain(code)
if sp.PURCHASE_ORDER_NUMBER.match(SEARCH) and po_ids:
    domain = [("id", "in", po_ids)]
else:
    texts = [[("name", "ilike", SEARCH)], [("opportunity_ref", "ilike", SEARCH)], [("sale_code", "ilike", SEARCH)],
             [("sale_order_id.name", "ilike", SEARCH)], [("request_id.name", "ilike", SEARCH)],
             [("line_ids.product_id", "ilike", SEARCH)], [("quote_ids.partner_id", "ilike", SEARCH)]]
    domain = expression.AND([scope_dom, expression.OR(texts)])
    if sp.NUMBER_ONLY.match(SEARCH):
        domain = expression.OR([domain, [("id", "in", po_ids)]])
print("  domain: %s" % domain)
# Trang chạy search theo quyền sale (không sudo) — ở đây sudo, nên nếu ra mà trang không ra thì là chuyện quyền.
for key, label in sp.STATUS_TABS:
    if key == sp.PRICE_TODO_TAB:
        status_dom = [("id", "in", env["hlv.po.price.proposal"]._sale_todo_inquiry_ids())]
    elif key == "all":
        status_dom = []  # đang tìm thì "Tất cả" gồm cả phiếu đóng / huỷ
    else:
        status_dom = [("sale_status", "=", key)]
    found = Inquiry.search(domain + status_dom)
    print("  tab %-22s %s  %s" % (label, len(found), found.mapped("name")[:10]))

head("5. MỞ PHIẾU (_inquiry_in_scope)")
for inquiry in Inquiry.browse(po_ids) | no_filter:
    print("  %s (mã phiếu %r): mở được với mã %r → %s"
          % (inquiry.name, inquiry.sale_code, code, SalePageMixin._inquiry_in_scope(inquiry, code)))
''')
