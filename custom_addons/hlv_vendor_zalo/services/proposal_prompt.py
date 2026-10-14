# -*- coding: utf-8 -*-
"""Dựng yêu cầu cho Claude đọc hội thoại nhóm Zalo với NCC và soạn giá / tồn kho cho các báo giá đang mở; đọc kết quả.

Util thuần: vào dict / list, ra chuỗi / dict. Không đụng env, không gọi mạng.

Bối cảnh: sale lập phiếu hỏi giá trên /hoi-gia-ncc rồi hỏi NCC trong nhóm Zalo ("A27: 10S @NCC có hàng k ạ"). NCC trả lời
gom nhiều câu một lúc, theo mã hàng, không bấm trả lời từng tin ("A27 đủ 10s / C86 còn 9s / XPZ737 chưa có mã"); có NCC
báo giá thẳng ("GIÁ 1.818.000 GIẢM 13% SẴN HÀNG"), có NCC chỉ báo tồn kho (giá theo bảng giá riêng).
"""

import json
import re

STATUS_OFFERED = "offered"        # có giá (kèm hoặc không kèm tồn kho)
STATUS_STOCK_ONLY = "stock_only"  # chỉ báo tồn kho / hẹn ngày, không có giá
STATUS_UNAVAILABLE = "unavailable"  # hết hàng / không có mã / không kinh doanh
STATUSES = (STATUS_OFFERED, STATUS_STOCK_ONLY, STATUS_UNAVAILABLE)
PRICE_BASES = ("incl_vat", "excl_vat", "unknown")
VAT_CODES = ("0", "5", "8", "10", "kct")
CONFIDENCES = ("high", "low")
MAX_TOKENS = 16000
EVIDENCE_MAX = 300
NOTE_MAX = 200
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = """Bạn giúp sale của một công ty thương mại dụng cụ / thiết bị đọc tin nhắn nhóm Zalo giữa sale và một nhà cung cấp (NCC), rồi soạn giá / tình trạng hàng cho các BÁO GIÁ ĐANG MỞ của NCC đó.

Bạn nhận: danh sách báo giá đang mở (mỗi báo giá có các dòng: line_id, mã hàng, tên hàng, số lượng hỏi, đơn vị) và đoạn hội thoại nhóm (mỗi tin có số #, giờ, người gửi + vai trò NCC / NV (nhân viên công ty) / ?, tin được trích nếu là trả lời). Có thể kèm ảnh NCC gửi (bảng giá, ảnh sản phẩm).

Việc cần làm: với từng dòng báo giá mà NCC ĐÃ NÓI tới trong hội thoại, ghi lại NCC nói gì. Dòng NCC chưa nói tới thì BỎ, không đoán.

Ghép tin với dòng báo giá:
- NCC hay trả lời gom nhiều câu hỏi trong một tin, theo mã hàng, không trích tin. Ghép theo mã / tên hàng và theo câu sale hỏi trước đó. Mã NCC dùng có thể khác mã của công ty một chút (thiếu tiền tố hãng, khác cách viết) — chỉ ghép khi chắc là cùng mặt hàng.
- Tin trả lời có trích tin khác thì nói về hàng trong tin được trích.
- Chỉ lấy điều NCC nói (vai trò NCC, hoặc ? mà rõ ràng là bên bán). Câu của NV là câu hỏi, không phải câu trả lời.
- Nhiều lần NCC nói về cùng một dòng thì lấy lần SAU CÙNG.

Mỗi dòng ghi:
- status: "offered" (NCC báo giá cho dòng này), "stock_only" (chỉ báo còn / hết bao nhiêu, ngày về, không có giá), "unavailable" (hết hàng hẳn, "chưa có mã", không kinh doanh, ngừng).
- price: đơn giá cho MỘT đơn vị đúng như NCC báo (số, đồng). Không có giá → 0. "1tr8" = 1800000, "45k" = 45000. Giá NCC báo là giá TRƯỚC chiết khấu khi có "giảm x%".
- price_basis: "incl_vat" nếu NCC nói đã gồm VAT / giá sau thuế, "excl_vat" nếu nói chưa VAT / chưa thuế (kể cả nói một lần cho cả nhóm hàng, vd "dây Vbelt báo giá chưa VAT"), "unknown" nếu không nói.
- vat: "0", "5", "8", "10", "kct" nếu NCC nói % VAT, không nói → "".
- discount_pct: % chiết khấu NCC cho ("giảm 13%", "CK 10") — không có → 0.
- available_qty: số lượng NCC có sẵn khi NCC nói CÓ ÍT HƠN số hỏi ("còn 9s" khi hỏi 10). Có đủ / không nói số → -1.
- backorder_date: ngày NCC hẹn giao phần thiếu, dạng YYYY-MM-DD (tính từ ngày của tin: "thứ 5 về", "tuần sau", "3 ngày nữa"). Không có → "".
- delivery_days: số ngày giao NCC nói ("2 ngày có hàng") — không nói → 0.
- note: ghi chú ngắn cần cho sale (hàng thay thế, xuất xứ, điều kiện) — không có → "".
- evidence_msg_ids: số # các tin làm căn cứ. evidence: trích nguyên văn phần tin NCC nói về dòng này (ngắn).
- confidence: "high" khi chắc chắn ghép đúng dòng và đọc đúng số; "low" khi phải đoán (mã gần giống, ghép theo thứ tự, số mơ hồ, giá không rõ cho đơn vị nào).

Viết tắt hay gặp: "s" = sợi, "c" = cái, "b" = bộ; "đủ" = có đủ số hỏi; "chưa có mã" = không có hàng. summary: một câu tiếng Việt ngắn tóm tắt NCC đã trả lời gì."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "integer"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_id": {"type": "integer"},
                                "status": {"type": "string", "enum": list(STATUSES)},
                                "price": {"type": "number"},
                                "price_basis": {"type": "string", "enum": list(PRICE_BASES)},
                                "vat": {"type": "string", "enum": [""] + list(VAT_CODES)},
                                "discount_pct": {"type": "number"},
                                "available_qty": {"type": "number"},
                                "backorder_date": {"type": "string"},
                                "delivery_days": {"type": "integer"},
                                "note": {"type": "string"},
                                "evidence_msg_ids": {"type": "array", "items": {"type": "integer"}},
                                "evidence": {"type": "string"},
                                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                            },
                            "required": ["line_id", "status", "price", "price_basis", "vat", "discount_pct", "available_qty",
                                         "backorder_date", "delivery_days", "note", "evidence_msg_ids", "evidence",
                                         "confidence"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["quote_id", "lines"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "quotes"],
    "additionalProperties": False,
}


def conversation_text(messages):
    """Hội thoại → chữ cho Claude. messages: [{id, at (chuỗi "HH:MM dd/mm/YYYY"), sender, role ("NCC" | "NV" | "?"),
    text, quote_id (số # tin được trích, 0 nếu không), quote_text, attachment ("" hoặc "ảnh" / "file <tên>")}],
    cũ trước. Tin rỗng (sticker…) vẫn ghi để giữ mạch."""
    lines = []
    for m in messages:
        head = f"#{m['id']} {m['at']} · {m['sender']} ({m['role']})"
        if m.get("quote_id") or m.get("quote_text"):
            head += f" trả lời #{m['quote_id']}" if m.get("quote_id") else " trả lời"
            if m.get("quote_text"):
                head += f' «{_one_line(m["quote_text"])[:160]}»'
        body = (m.get("text") or "").strip()
        if m.get("attachment"):
            body = f"[{m['attachment']}] {body}".strip()
        lines.append(f"{head}: {body or '[không có chữ]'}")
    return "\n".join(lines)


def quotes_text(quotes):
    """Báo giá đang mở → chữ cho Claude. quotes: [{id, name, inquiry, sale, lines: [{id, code, name, qty, uom,
    current}]}] — current: chữ mô tả giá NCC đã báo trên trang (để Claude biết dòng nào đã có giá), "" nếu chưa."""
    blocks = []
    for q in quotes:
        rows = [f"  - line_id {l['id']}: [{l['code'] or '-'}] {l['name']} · SL hỏi {_num(l['qty'])} {l['uom']}"
                + (f" · đã báo: {l['current']}" if l.get("current") else "") for l in q["lines"]]
        blocks.append(f"Báo giá quote_id {q['id']} ({q['name']}, phiếu {q['inquiry']}, sale {q['sale'] or '?'}):\n"
                      + "\n".join(rows))
    return "\n\n".join(blocks)


def user_message(vendor_name, today, quotes, messages):
    """Nội dung tin gửi Claude (phần chữ; ảnh nối thêm ở nơi gọi)."""
    return (f"NCC: {vendor_name}. Hôm nay: {today}.\n\nCÁC BÁO GIÁ ĐANG MỞ CỦA NCC NÀY\n{quotes_text(quotes)}\n\n"
            f"HỘI THOẠI NHÓM ZALO (cũ trước)\n{conversation_text(messages)}")


def parse_result(text, quotes):
    """Đọc JSON Claude trả. Chỉ nhận quote_id / line_id có trong quotes (Claude bịa id thì bỏ); số âm / sai kiểu về mặc
    định. Trả (summary, {quote_id: [dòng đã làm sạch]}). JSON hỏng → ValueError."""
    data = json.loads(text)
    allowed = {q["id"]: {l["id"] for l in q["lines"]} for q in quotes}
    result = {}
    for item in data.get("quotes") or []:
        quote_id = item.get("quote_id")
        if quote_id not in allowed:
            continue
        seen, rows = set(), []
        for raw in item.get("lines") or []:
            line_id = raw.get("line_id")
            if line_id not in allowed[quote_id] or line_id in seen or raw.get("status") not in STATUSES:
                continue
            seen.add(line_id)
            rows.append(clean_line(raw))
        if rows:
            result[quote_id] = rows
    return str(data.get("summary") or "")[:500], result


def clean_line(raw):
    """Một dòng Claude trả → giá trị đã kiểm kiểu / khoảng. Không đụng ý nghĩa (status, giá) — chỉ chặn số vô lý."""
    def number(key, minimum=0.0):
        try:
            value = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            return minimum
        return value if value >= minimum else minimum

    discount = number("discount_pct")
    backorder = str(raw.get("backorder_date") or "")
    available = raw.get("available_qty")
    try:
        available = float(available)
    except (TypeError, ValueError):
        available = -1.0
    return {
        "line_id": raw["line_id"],
        "status": raw["status"],
        "price": number("price"),
        "price_basis": raw.get("price_basis") if raw.get("price_basis") in PRICE_BASES else "unknown",
        "vat": raw.get("vat") if raw.get("vat") in VAT_CODES else "",
        "discount_pct": discount if discount < 100 else 0.0,
        "available_qty": available if available >= 0 else -1.0,
        "backorder_date": backorder if DATE_RE.match(backorder) else "",
        "delivery_days": int(number("delivery_days")),
        "note": str(raw.get("note") or "")[:NOTE_MAX],
        "evidence_msg_ids": [i for i in raw.get("evidence_msg_ids") or [] if isinstance(i, int)],
        "evidence": str(raw.get("evidence") or "")[:EVIDENCE_MAX],
        "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCES else "low",
    }


def price_incl(price, basis, vat_rate):
    """Giá NCC báo → giá sau VAT (trước CK). basis "excl_vat": cộng VAT; "incl_vat" / "unknown": giữ nguyên (thói
    quen báo giá sau VAT — sale thấy cờ "không rõ VAT" và sửa nếu sai). Làm tròn đồng."""
    if not price:
        return 0.0
    return round(price * (1 + (vat_rate or 0) / 100.0)) if basis == "excl_vat" else round(price)


def _one_line(text):
    return " ".join((text or "").split())


def _num(value):
    return f"{value:g}" if isinstance(value, float) else str(value)
