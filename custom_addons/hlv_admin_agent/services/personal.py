# -*- coding: utf-8 -*-
"""Cá nhân hoá trợ lý quản trị: tool ghi nhớ / tìm cuộc chat cũ, và khối "về người dùng" trong prompt.

Util thuần: vào chuỗi / list dict, ra list dict / chuỗi. Không đụng ``self.env``.
"""
from odoo.addons.hlv_product_agent.services.permission_marker import ADMIN_MARKER

MEMORY_KINDS = [
    ('preference', "Sở thích / cách làm việc"),
    ('customer', "Khách hàng"),
    ('rule', "Quy ước nghiệp vụ"),
    ('other', "Khác"),
]
MEMORY_MAX_CHARS = 500

_KIND_PROP = {"type": "string", "enum": [code for code, _label in MEMORY_KINDS],
              "description": "preference: cách người dùng muốn làm việc; customer: điều về một khách; "
                             "rule: quy ước nghiệp vụ; other: khác"}

PERSONAL_TOOLS = [
    {
        "name": "ghi_nho",
        "description": (
            "Ghi nhớ LÂU DÀI một điều về người dùng / khách / quy ước, dùng cho mọi cuộc chat sau của "
            "người này. Người dùng bảo 'nhớ là...' thì ghi luôn. Em tự thấy điều đáng nhớ thì HỎI trước "
            "(nút [[Nhớ giúp em]]), không tự ghi. Một điều một lần gọi, câu ngắn tự hiểu được (ghi rõ "
            "tên khách, mã...). Không ghi thứ chỉ đúng trong cuộc này, không ghi số liệu sẽ đổi (tồn, giá "
            f"hôm nay). Tối đa {MEMORY_MAX_CHARS} ký tự."
        ),
        "input_schema": {"type": "object", "properties": {
            "noi_dung": {"type": "string", "description": "Điều cần nhớ"},
            "loai": _KIND_PROP,
        }, "required": ["noi_dung", "loai"]},
    },
    {
        "name": "sua_ghi_nho",
        "description": "Sửa một ghi nhớ đã có (id trong mục GHI NHỚ của prompt) khi nó đã cũ / sai.",
        "input_schema": {"type": "object", "properties": {
            "id": {"type": "integer"}, "noi_dung": {"type": "string"},
        }, "required": ["id", "noi_dung"]},
    },
    {
        "name": "quen",
        "description": "Xoá một ghi nhớ (id trong mục GHI NHỚ) khi người dùng bảo quên / bỏ điều đó.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "tim_cuoc_chat_cu",
        "description": (
            "Tìm trong các cuộc chat TRƯỚC của chính người dùng này (không gồm cuộc hiện tại) theo từ "
            "khoá: tên khách, mã hàng, số BG/CH... Dùng khi người dùng nhắc 'hôm trước', 'lần trước', "
            "'như cũ'. Trả các đoạn khớp kèm session_id để đọc kỹ bằng doc_cuoc_chat_cu."
        ),
        "input_schema": {"type": "object", "properties": {
            "tu_khoa": {"type": "string", "description": "Từ khoá ngắn (kiểu 'chứa')"},
        }, "required": ["tu_khoa"]},
    },
    {
        "name": "doc_cuoc_chat_cu",
        "description": "Đọc nội dung một cuộc chat cũ của người dùng (session_id từ tim_cuoc_chat_cu).",
        "input_schema": {"type": "object", "properties": {"session_id": {"type": "integer"}},
                         "required": ["session_id"]},
    },
]
PERSONAL_TOOL_NAMES = frozenset(tool["name"] for tool in PERSONAL_TOOLS)


def personal_block(user_name, instructions, memories):
    """Khối "về người dùng" nạp sau system prompt chung (không cache: mỗi người mỗi khác).

    Nhận: tên người dùng, hướng dẫn riêng (chuỗi, có thể rỗng), list ``{'id', 'kind', 'content'}``.
    Trả: chuỗi. Biên: không có hướng dẫn lẫn ghi nhớ -> vẫn có tên và câu "chưa có ghi nhớ" để Claude
        biết là chưa có, không phải bị thiếu.
    """
    labels = dict(MEMORY_KINDS)
    lines = ["==================================================",
             "VỀ NGƯỜI DÙNG: %s" % (user_name or "?"),
             "=================================================="]
    if (instructions or "").strip():
        lines += ["", "HƯỚNG DẪN RIÊNG (người dùng tự viết — theo, trừ khi trái luật ghi dữ liệu ở mục I):",
                  instructions.strip()]
    lines += ["", "GHI NHỚ (id — loại — nội dung; dùng id khi sửa / quên):"]
    if memories:
        lines += ["- #%s — %s — %s" % (mem["id"], labels.get(mem["kind"], mem["kind"]), mem["content"])
                  for mem in memories]
    else:
        lines.append("(chưa có ghi nhớ nào)")
    return "\n".join(lines)


def snippet(text, keyword, radius=120):
    """Đoạn trích quanh lần khớp đầu tiên của ``keyword`` trong ``text`` (không phân biệt hoa thường).

    Trả: chuỗi một dòng, có "…" ở đầu / cuối nếu bị cắt. Biên: không khớp -> ``radius * 2`` ký tự đầu.
    """
    flat = " ".join((text or "").split())
    pos = flat.casefold().find((keyword or "").casefold()) if keyword else -1
    start = max(pos - radius, 0) if pos >= 0 else 0
    end = min((pos + len(keyword) + radius) if pos >= 0 else radius * 2, len(flat))
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def with_summary(prompt, summary):
    """Chèn bản tóm tắt phần đầu cuộc chat vào nội dung lượt, NGAY SAU marker quyền.

    Marker phải đứng đầu tin (phụ lục trợ lý tạo mã chỉ tin marker ở đầu). Nhận: nội dung lượt dựng
    bởi build_turn_prompt, tóm tắt (có thể rỗng). Trả: chuỗi. Biên: tóm tắt rỗng -> trả nguyên prompt.
    """
    summary = (summary or "").strip()
    if not summary:
        return prompt
    note = "(Tóm tắt phần đầu cuộc chat này — các tin cũ hơn không còn trong ngữ cảnh:)\n%s\n" % summary
    if prompt.startswith(ADMIN_MARKER):
        return "%s %s\n%s" % (ADMIN_MARKER, note, prompt[len(ADMIN_MARKER):].lstrip())
    return "%s\n%s" % (note, prompt)
