# analyze_amis_callback_log.py — CHỈ ĐỌC, không ghi gì vào database.
# Đọc N callback MISA gần nhất (amis.callback.log): loại callback, ModelState,
# khớp Đơn mua / đề nghị chi / phiếu kho nào, trạng thái MISA hiện tại của PO.
# Mục đích chính: xem MISA gửi gì khi kế toán xóa đề nghị/chứng từ trên MISA.
#
# Cách dùng: sửa 5 dòng cấu hình bên dưới, rồi copy TOÀN BỘ file dán vào
# odoo-bin shell (Odoo.sh) và Enter. Phần chạy được bọc trong exec(...) để dán
# vào REPL không bị vỡ bởi dòng trống trong vòng lặp/hàm.

LIMIT = 50          # số callback đọc
DATA_TYPE = None    # None = mọi loại; hoặc 2, 22, 1, 18 ...
PO_NAME = "DMH23526"  # chỉ lấy callback dính tới PO này (kể cả org_refid cũ); "" = mọi PO
SHOW_RAW = False    # True = in thêm data_payload (cắt 1500 ký tự)
QUIET = False       # True = bỏ chi tiết từng callback, chỉ in tổng hợp (khi LIMIT lớn)


exec(r'''
from collections import Counter

RAW_MAX = 1500
DATA_TYPE_LABELS = {
    1: "save đề nghị",
    2: "xóa đề nghị (DELETE)",
    3: "save đề nghị (3)",
    18: "sinh chứng từ từ đề nghị",
    22: "chứng từ MISA đẩy về",
}
MODEL_STATE_LABELS = {
    1: "Thêm", 2: "Sửa", 3: "XÓA", 7: "Ghi sổ", 8: "Bỏ ghi sổ",
}
SEP = "=" * 78
SEP2 = "-" * 78

Log = env["amis.callback.log"].sudo()
PurchaseOrder = env["purchase.order"].sudo().with_context(active_test=False)
PaymentRequest = env["amis.payment.request"].sudo()
Picking = env["stock.picking"].sudo()


def detail(text):
    if not QUIET:
        print(text)


def section(title):
    print("\n%s\n  %s\n%s" % (SEP, title, SEP))


def label(mapping, value):
    return "%s (%s)" % (value, mapping[value]) if value in mapping else str(value)


def as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def po_refids(po):
    """Mọi org_refid từng gửi của PO: hiện tại + đã thu hồi."""
    refids = {(po.misa_purchase_order_org_refid or "").strip()}
    refids.update(
        value.strip()
        for value in (po.misa_purchase_order_previous_org_refids or "").splitlines()
    )
    refids.discard("")
    return refids


def find_po(org_refid):
    """Trả (PO, "hiện tại"|"cũ") hoặc (None, "") nếu không khớp."""
    po = PurchaseOrder.search([("misa_purchase_order_org_refid", "=", org_refid)], limit=1)
    if po:
        return po, "hiện tại"
    po = PurchaseOrder.search(
        [("misa_purchase_order_previous_org_refids", "ilike", org_refid)], limit=1
    )
    if po:
        return po, "cũ"
    return None, ""


def describe_target(org_refid, refno):
    po, which = find_po(org_refid)
    if po:
        return "PO %s [refid %s] state=%s synced=%s replace_pending=%s rev=%s" % (
            po.name, which, po.misa_purchase_order_state,
            po.misa_purchase_order_synced,
            po.misa_purchase_order_replacement_pending,
            po.misa_purchase_order_revision,
        )
    payment = PaymentRequest.search([("org_refid", "=", org_refid)], limit=1)
    if payment:
        return "Đề nghị chi %s state=%s" % (payment.name, payment.state)
    picking = Picking.search([("misa_inward_org_refid", "=", org_refid)], limit=1)
    if not picking and refno:
        picking = Picking.search([("name", "=", refno)], limit=1)
    if picking:
        return "Phiếu kho %s" % picking.name
    return "KHÔNG KHỚP bản ghi Odoo nào"


# ── Chọn callback ──────────────────────────────────────────────
domain = []
if DATA_TYPE:
    domain.append(("data_type", "=", int(DATA_TYPE)))

target_po = None
if PO_NAME:
    target_po = PurchaseOrder.search([("name", "=", PO_NAME)], limit=1)
    if not target_po:
        raise RuntimeError("Không tìm thấy Đơn mua %s." % PO_NAME)
    refids = sorted(po_refids(target_po))
    if not refids:
        raise RuntimeError("Đơn mua %s chưa từng gửi MISA (không có org_refid)." % PO_NAME)
    domain += ["|"] * (len(refids) - 1) + [
        ("data_payload", "ilike", refid) for refid in refids
    ]

logs = Log.search(domain, limit=LIMIT)

section("AMIS CALLBACK LOG — %d bản ghi gần nhất%s%s" % (
    len(logs),
    " | data_type=%s" % DATA_TYPE if DATA_TYPE else "",
    " | PO=%s" % PO_NAME if PO_NAME else "",
))
if target_po:
    print("  PO %s: state=%s, org_refid hiện tại=%s" % (
        target_po.name, target_po.misa_purchase_order_state,
        target_po.misa_purchase_order_org_refid,
    ))
    print("  org_refid cũ: %s" % (
        ", ".join(sorted(po_refids(target_po) - {target_po.misa_purchase_order_org_refid}))
        or "(không có)"
    ))

summary = Counter()
deletion_events = []
unmatched = []
failed = []

# ── Chi tiết từng callback ─────────────────────────────────────
for log in logs.sorted(lambda r: (r.received_at, r.id)):
    data_type = log.data_type or 0
    detail("\n%s" % SEP2)
    detail("%s | %s | data_type=%s | state=%s | chữ ký=%s" % (
        log.name, log.received_at, label(DATA_TYPE_LABELS, data_type),
        log.state, "OK" if log.signature_valid else "SAI",
    ))
    if not log.input_success or log.input_error_code:
        detail("  input: success=%s error=%s %s" % (
            log.input_success, log.input_error_code or "", log.input_error_message or "",
        ))

    items = [item for item in Log._parse_data_items(log.data_payload) if isinstance(item, dict)]
    if not items:
        detail("  (không parse được item nào từ data_payload)")
        summary[(data_type, None, None)] += 1
    for index, item in enumerate(items, start=1):
        org_refid = (item.get("org_refid") or item.get("refid") or "").strip()
        refno = (item.get("org_refno") or item.get("refno") or "").strip()
        voucher_type = as_int(item.get("voucher_type"))
        model_state = as_int(item.get("_misa_model_state"))
        success = item.get("success")
        is_request = bool(voucher_type) and not refno
        target = describe_target(org_refid, refno) if org_refid else "(không có org_refid)"

        summary[(data_type, voucher_type, model_state or None)] += 1
        detail("  [%d] voucher_type=%s refno=%s %s" % (
            index, voucher_type or "-", refno or "-",
            "(callback đề nghị)" if is_request else "",
        ))
        detail("      org_refid=%s success=%s%s" % (
            org_refid or "-", success,
            " ModelState=%s" % label(MODEL_STATE_LABELS, model_state) if model_state else "",
        ))
        if item.get("error_code") or item.get("error_message"):
            detail("      LỖI: %s %s %s" % (
                item.get("error_code") or "", item.get("error_message") or "",
                item.get("error_call_back_message") or "",
            ))
        detail("      → %s" % target)

        if data_type == 2 or model_state == 3:
            deletion_events.append((log, data_type, model_state, voucher_type, success,
                                    item.get("error_code"), target))
        if org_refid and target.startswith("KHÔNG KHỚP"):
            unmatched.append((log.name, data_type, voucher_type, org_refid, refno))
        if success is False:
            failed.append((log.name, data_type, item.get("error_code"), item.get("error_message")))

    if SHOW_RAW:
        raw = log.data_payload or ""
        if len(raw) > RAW_MAX:
            raw = raw[:RAW_MAX] + " …(cắt)"
        detail("  data_payload: %s" % raw)

# ── Chẩn đoán khóa sửa của PO ──────────────────────────────────
if target_po:
    section("KHÓA SỬA CỦA %s" % target_po.name)
    module = env["ir.module.module"].sudo().search([("name", "=", "amis_callback")], limit=1)
    print("  amis_callback cài bản: %s" % module.latest_version)
    print("  state=%s synced=%s locked=%s can_revoke=%s replace_pending=%s rev=%s" % (
        target_po.misa_purchase_order_state, target_po.misa_purchase_order_synced,
        target_po.misa_purchase_order_locked, target_po.misa_purchase_order_can_revoke,
        target_po.misa_purchase_order_replacement_pending, target_po.misa_purchase_order_revision,
    ))
    print("  cập nhật trạng thái MISA lúc: %s" % target_po.misa_purchase_order_state_updated_at)
    for model_name in ("purchase.order", "purchase.order.line"):
        chain = [
            cls.__module__ for cls in type(env[model_name]).__mro__
            if "write" in vars(cls) and cls.__module__.startswith("odoo.addons.")
        ]
        print("  %s.write đi qua: %s" % (model_name, " > ".join(chain)))
    print("  Lịch sử thay đổi (chatter):")
    messages = env["mail.message"].sudo().search([
        ("model", "=", "purchase.order"), ("res_id", "=", target_po.id),
    ], order="id")
    for message in messages:
        for tracking in message.tracking_value_ids:
            print("    %s %s | %s: %s → %s" % (
                message.date, message.author_id.name, tracking.field_id.field_description,
                tracking.old_value_char or tracking.old_value_float or tracking.old_value_integer,
                tracking.new_value_char or tracking.new_value_float or tracking.new_value_integer,
            ))

# ── Job hàng đợi của PO: ai/khi nào đẩy hoặc thu hồi ───────────
if target_po:
    section("JOB HÀNG ĐỢI MISA CỦA %s" % target_po.name)
    jobs = env["amis.sync.job"].sudo().search(
        [("purchase_order_id", "=", target_po.id)], order="id"
    )
    if not jobs:
        print("  Không có job nào.")
    for job in jobs:
        print("  #%s %-22s %-8s retry=%s | tạo %s bởi %s | xử lý %s | sửa cuối %s bởi %s" % (
            job.id, job.direction, job.status, job.retry_count,
            job.create_date, job.create_uid.name, job.processed_at,
            job.write_date, job.write_uid.name,
        ))
        if job.error_msg:
            print("      lỗi: %s" % job.error_msg[:300].replace("\n", " "))

# ── Tổng hợp ───────────────────────────────────────────────────
section("TỔNG HỢP: data_type × voucher_type × ModelState")
for (data_type, voucher_type, model_state), count in sorted(
    summary.items(), key=lambda kv: tuple(x or 0 for x in kv[0])
):
    print("  data_type=%-28s voucher_type=%-4s ModelState=%-14s : %d" % (
        label(DATA_TYPE_LABELS, data_type), voucher_type if voucher_type is not None else "-",
        label(MODEL_STATE_LABELS, model_state) if model_state else "-", count,
    ))

section("CALLBACK XÓA (data_type=2 hoặc ModelState=3)")
if not deletion_events:
    print("  Không có callback xóa nào trong %d bản ghi này." % len(logs))
    print("  → Nếu kế toán vừa xóa đề nghị trên MISA mà không thấy ở đây, có thể MISA")
    print("    không gửi callback khi xóa đề nghị từ giao diện. Thử LIMIT lớn hơn / PO_NAME.")
for log, data_type, model_state, voucher_type, success, error_code, target in deletion_events:
    print("  %s %s data_type=%s ModelState=%s voucher_type=%s success=%s %s" % (
        log.name, log.received_at, data_type, model_state or "-", voucher_type or "-",
        success, error_code or "",
    ))
    print("      → %s" % target)

section("CALLBACK BÁO LỖI")
if not failed:
    print("  Không có.")
for name, data_type, error_code, error_message in failed:
    print("  %s data_type=%s %s %s" % (name, data_type, error_code or "", error_message or ""))

section("org_refid KHÔNG KHỚP BẢN GHI ODOO NÀO")
if not unmatched:
    print("  Không có.")
for name, data_type, voucher_type, org_refid, refno in unmatched:
    print("  %s data_type=%s voucher_type=%s org_refid=%s refno=%s" % (
        name, data_type, voucher_type or "-", org_refid, refno or "-",
    ))

print("\n%s\n  XONG (chỉ đọc, không ghi gì).\n%s" % (SEP, SEP))
''')
