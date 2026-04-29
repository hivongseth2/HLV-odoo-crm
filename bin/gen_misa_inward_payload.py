#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Odoo shell script - sinh payload phiếu nhập kho cho MISA (code-only, không GUID).

Chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/gen_misa_inward_payload.py

Hoặc copy-paste vào `odoo-bin shell` session đang mở.
"""
import json
from datetime import datetime

# ─────────────────────────── Tham số đầu vào ─────────────────────────────────
PICKING_NAME = "KBC/IN/09169"
PO_NAME      = "DMH18228"

APP_ID        = "cfd435c9-b5c9-484f-b86d-ddbba36dc0f4"
ORG_CODE      = "3R2PY2F4"
STOCK_CODE    = "HLV"           # mã kho bên MISA
DEBIT_ACC     = "1561"
CREDIT_ACC    = "331"
ORG_REFTYPE   = 2014

# Nếu muốn liên kết về đơn mua hàng gốc bên MISA, điền org_refid của PO nguồn.
# Để trống: chỉ tạo đề nghị nhập kho, không có liên kết chứng từ nguồn.
SOURCE_PO_ORG_REFID = ""
# Tùy chọn: loại chứng từ nguồn trên MISA (nếu khác mặc định).
# Để None sẽ giữ org_reftype như ORG_REFTYPE.
SOURCE_PO_REFTYPE = None
# ─────────────────────────────────────────────────────────────────────────────

picking = env["stock.picking"].sudo().search([("name", "=", PICKING_NAME)], limit=1)
if not picking:
    raise Exception("Không tìm thấy phiếu: %s" % PICKING_NAME)

# Tìm PO: ưu tiên theo tên truyền vào, fallback về origin của picking
po = env["purchase.order"].sudo().search([("name", "=", PO_NAME)], limit=1)
if not po and picking.origin:
    po = env["purchase.order"].sudo().search([("name", "=", picking.origin)], limit=1)

partner = picking.partner_id or (po.partner_id if po else env["res.partner"])

print("=" * 60)
print("Picking :", picking.name, "| state:", picking.state)
print("PO      :", po.name if po else "(không tìm thấy)")
print("Partner :", partner.display_name if partner else "(không có)")
print("=" * 60)

# ───────────────────────── Build detail lines ────────────────────────────────
detail   = []
total_am = 0.0
moves    = picking.move_ids_without_package.filtered(lambda m: m.quantity > 0)

for idx, move in enumerate(moves, start=1):
    product   = move.product_id
    qty       = float(move.quantity)
    price     = float(move.purchase_line_id.price_unit if move.purchase_line_id else 0.0)
    amount    = qty * price
    total_am += amount

    line = {
        # ── Không gửi các GUID ──────────────────────────────────────────────
        # "inventory_item_id": "...",   # bỏ
        # "unit_id":           "...",   # bỏ
        # "main_unit_id":      "...",   # bỏ
        # "stock_id":          "...",   # bỏ
        # "account_object_id": "...",   # bỏ
        # "ref_detail_id":     "...",   # bỏ
        # "refid":             "...",   # bỏ

        # ── Dùng mã (code) để MISA tự map ──────────────────────────────────
        "inventory_item_code": product.default_code or str(product.id),
        "inventory_item_name": product.display_name,
        "inventory_item_type": 0,
        "stock_code":          STOCK_CODE,
        "stock_name":          STOCK_CODE,
        "unit_name":           move.product_uom.name,
        "main_unit_name":      move.product_uom.name,
        "account_object_code": partner.ref or partner.name if partner else "",
        "account_object_name": partner.display_name if partner else "",
        "debit_account":       DEBIT_ACC,
        "credit_account":      CREDIT_ACC,

        # ── Số lượng / giá ──────────────────────────────────────────────────
        "quantity":                    qty,
        "main_quantity":               qty,
        "main_convert_rate":           1.0,
        "unit_price_finance":          price,
        "amount_finance":              amount,
        "unit_price_management":       price,
        "amount_management":           amount,
        "main_unit_price_finance":     price,
        "main_unit_price_management":  price,
        "amount_finance_oc":           amount,
        "amount_management_oc":        amount,

        # ── Meta ────────────────────────────────────────────────────────────
        "description":                     product.display_name,
        "sort_order":                      idx,
        "inventory_resale_type_id":        0,
        "un_resonable_cost":               False,
        "is_promotion":                    False,
        "is_follow_serial_number":         False,
        "is_allow_duplicate_serial_number": False,
        "exchange_rate_operator":          "*",
        "state":                           0,
    }
    detail.append(line)

    print("  [%d] %s | qty=%.2f | price=%.2f | amount=%.2f"
          % (idx, product.default_code or product.id, qty, price, amount))

# ──────────────────────────── Build voucher ──────────────────────────────────
ref_date  = (picking.date_done or datetime.utcnow()).strftime("%Y-%m-%d")
timestamp = int(datetime.utcnow().timestamp() * 1000)

voucher = {
    # ── Không gửi các GUID đầu phiếu ────────────────────────────────────
    # "org_refid":         "...",   # bỏ
    # "refid":             "...",   # bỏ
    # "branch_id":         "...",   # bỏ
    # "account_object_id": "...",   # bỏ

    # ── Metadata chứng từ ────────────────────────────────────────────────
    "voucher_type":       7,
    "is_get_new_id":      True,
    "org_refno":          picking.name,
    "org_reftype":        ORG_REFTYPE,
    "org_reftype_name":   "Phieu nhap kho",
    "reftype":            ORG_REFTYPE,
    "reftype_name":       "Nhap kho",
    "reforder":           timestamp,
    "refdate":            ref_date,
    "posted_date":        ref_date,
    "display_on_book":    0,
    "unit_price_method":  0,
    "act_voucher_type":   0,
    "is_allow_group":     False,
    "is_return_with_inward":              False,
    "is_created_sa_return_last_year":     False,
    "is_posted_finance":                  False,
    "is_posted_management":               False,
    "is_posted_inventory_book_finance":   False,
    "is_posted_inventory_book_management": False,
    "is_executed":        False,
    "is_adjust_value":    False,

    # ── Đối tác / tiền tệ (dùng code) ───────────────────────────────────
    "account_object_code":    partner.ref or partner.name if partner else "",
    "account_object_name":    partner.display_name if partner else "",
    "account_object_address": partner.contact_address_complete if partner else "",
    "currency_id":            (po.currency_id.name if po else "VND"),
    "exchange_rate":          1.0,

    # ── Tổng tiền ────────────────────────────────────────────────────────
    "total_amount":            total_am,
    "total_amount_finance":    total_am,
    "total_amount_management": total_am,

    "refno_finance":    "",
    "refno_management": "",
    "journal_memo":     "Nhap kho tu don mua %s (Odoo: %s)" % (
                            po.name if po else "", picking.name),
    "state":  0,
    "detail": detail,
}

if SOURCE_PO_ORG_REFID:
    voucher["org_refid"] = SOURCE_PO_ORG_REFID
    voucher["org_refno"] = po.name if po else (picking.origin or picking.name)
    if SOURCE_PO_REFTYPE is not None:
        voucher["org_reftype"] = int(SOURCE_PO_REFTYPE)

payload = {
    "app_id":           APP_ID,
    "org_company_code": ORG_CODE,
    "voucher":          [voucher],
    "dictionary":       [],
}

# ─────────────────────────── In kết quả ─────────────────────────────────────
print("\n" + "=" * 60)
print("PAYLOAD (copy vào Postman body):")
print("=" * 60)
print(json.dumps(payload, ensure_ascii=False, indent=2))
print("\n--- Tổng tiền: {:,.0f} VND ---".format(total_am))
if SOURCE_PO_ORG_REFID:
    print("--- Đang bật link PO gốc theo org_refid:", SOURCE_PO_ORG_REFID, "---")
else:
    print("--- Chưa link PO gốc: điền SOURCE_PO_ORG_REFID để thử ---")
