# -*- coding: utf-8 -*-
"""Bộ tool và system prompt của trợ lý quản trị.

Util thuần: vào chuỗi / tên model, ra list dict / chuỗi. Không đụng ``self.env``.
"""
import hashlib
import json

from odoo.addons.hlv_product_agent.services.claude_api_payload import client_tools, server_tools

from .crm_tools import CRM_TOOLS
from .personal import PERSONAL_TOOLS

# Tool của trợ lý tạo mã chỉ có nghĩa trên trang tra tồn (mở trang đúng mã) — trang này không có.
EXCLUDED_PRODUCT_TOOLS = frozenset({"show_in_search_page"})

_BAR = "=================================================="

# Lịch sử API giữ lâu hơn trợ lý tạo mã: một báo giá dựng qua nhiều lượt (tìm khách, chọn hàng,
# chỉnh giá) và phải nhớ ID đã tra. Ngưỡng token tính cả system prompt (đã có nguyên prompt trợ lý
# tạo mã làm phụ lục), nên cao hơn ngưỡng 40k của trợ lý tạo mã.
MAX_HISTORY_TURNS = 20
MAX_PROMPT_TOKENS = 120000
# Nghỉ lâu hơn thì cache 1 giờ đã hết: gửi lại lịch sử là trả giá ghi cache cho cả lịch sử.
HISTORY_IDLE_MINUTES = 60


def admin_tools(model):
    """Toàn bộ tool cho một request: tool trợ lý tạo mã (kể cả giao việc tra cứu) + MISA CRM + ghi nhớ /
    cuộc chat cũ + web.

    Nhận: tên model Claude (bản web tool tuỳ model). Trả: list tool theo định dạng Messages API.
    Thứ tự cố định: đổi thứ tự là mất cache prompt.
    """
    product = [tool for tool in client_tools() if tool["name"] not in EXCLUDED_PRODUCT_TOOLS]
    return product + CRM_TOOLS + PERSONAL_TOOLS + server_tools(model)


def admin_system_text(core, product_prompt):
    """System prompt: luật của trợ lý quản trị, rồi nguyên prompt trợ lý tạo mã làm phụ lục.

    Nhận: phần lõi (sửa trên Odoo), prompt hoàn chỉnh của trợ lý tạo mã. Trả: chuỗi.
    Biên: phần nào rỗng thì bỏ phần đó (kể cả tiêu đề).
    """
    parts = [(core or "").strip()]
    if (product_prompt or "").strip():
        parts.append("%s\nPHỤ LỤC — TRỢ LÝ TẠO MÃ HÀNG & TRA CỨU KHO\n%s\n\n%s" % (
            _BAR, _BAR, product_prompt.strip()))
    return "\n\n".join(part for part in parts if part) + "\n"


def history_expired(history, last_prompt_tokens=0, idle_minutes=0):
    """Có nên bỏ lịch sử API, mở lại từ các tin chữ gần nhất không.

    Nhận: lịch sử (list message), số token prompt của request gần nhất (0 nếu chưa biết), số phút
    từ lượt API trước (0 nếu chưa biết).
    Trả True khi quá số lượt người dùng gõ, quá dài, hoặc nghỉ quá lâu.
    """
    turns = sum(1 for message in history if message.get("role") == "user" and _is_typed_turn(message))
    return (turns >= MAX_HISTORY_TURNS
            or (last_prompt_tokens or 0) > MAX_PROMPT_TOKENS
            or (idle_minutes or 0) > HISTORY_IDLE_MINUTES)


def _is_typed_turn(message):
    # Tin role user chứa tool_result là kết quả tool, không phải một lượt người dùng gõ.
    content = message.get("content")
    if isinstance(content, str):
        return True
    return not any(block.get("type") == "tool_result" for block in content or [])


def admin_context_key(model, system_text):
    """Vân tay model + prompt + tool: đổi một trong ba là lịch sử API cũ không dùng tiếp được.

    Trả: 16 ký tự hex.
    """
    raw = json.dumps([model, system_text, admin_tools(model)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
