# -*- coding: utf-8 -*-
"""Dựng request Claude API và đọc kết quả, cho chế độ Odoo tự gọi Claude bằng API key.

Util thuần: vào dict / chuỗi, ra dict / chuỗi. Không đụng ``self.env``, không gọi mạng.
"""
import hashlib
import json

from ..agent.misa_tools import DELEGATE_TOOL, HEAVY_QUERY_TOOLS, QUERY_TOOLS, TOOLS as MISA_TOOLS

MODEL_CHOICES = [
    ('claude-haiku-5-5', "Claude Haiku 5.5 (nhanh, rẻ nhất, $0.10/$0.50 mỗi triệu token)"),
    ('claude-sonnet-5-5', "Claude Sonnet 5.5 (kỹ hơn, $2/$10)"),
    ('claude-opus-5-5', "Claude Opus 5.5 (giỏi nhất, $4/$20)"),
]
# Haiku: việc ở đây là tra MISA + áp quy tắc có sẵn, không cần suy luận sâu; chốt chặn
# dữ liệu (đề xuất trước, quét trùng) nằm ở Odoo nên model nhẹ cũng không tạo bừa được.
DEFAULT_MODEL = 'claude-haiku-5-5'
EFFORT_CHOICES = [('low', "Thấp"), ('medium', "Vừa"), ('high', "Cao")]
DEFAULT_EFFORT = 'medium'
# Model phụ đi tra cứu (giao_viec_tra_cuu): đọc kết quả dài rồi tóm tắt — việc của model rẻ.
DEFAULT_WORKER_MODEL = 'claude-haiku-5-5'
WORKER_MAX_TOKENS = 8000
WORKER_EFFORT = 'low'
WORKER_SYSTEM = """Em là trợ lý TRA CỨU kho của công ty Hoàng Long Vũ, làm việc cho trợ lý chính.

Nhận một nhiệm vụ tra cứu, dùng các tool tra cứu Odoo (chỉ đọc) để lấy đủ số liệu, rồi trả lời
trợ lý chính bằng tiếng Việt, NGẮN và ĐỦ SỐ:
- Chỉ nói số liệu tool trả về; không đoán, không bịa. Tool lỗi / không có dữ liệu thì nói rõ.
- Tool báo 'ambiguous' (nhiều mã khớp): chọn mã khớp nhiệm vụ nhất và gọi lại; không chắc thì
  liệt kê các mã ứng viên để trợ lý chính hỏi người dùng.
- Gom thành ý chính + bảng số liệu dạng dòng (mỗi dòng một kho / một phiếu / một đơn), ghi rõ
  đơn vị và ngày. Danh sách dài thì giữ các dòng quan trọng nhất và ghi tổng còn lại.
- Nhiệm vụ "ai đang giữ" (xem_dang_giu): báo ĐỦ phiếu giữ hàng, đơn bán VÀ phiếu kho khác
  (chuyển kho, trả hàng...) — kèm số phiếu, loại, kho, SL, ngày dự kiến.
- Nhiệm vụ gợi ý giá mua (xem_gia_nhap): ưu tiên báo giá còn dùng được và lần mua gần (6-12
  tháng, không bị trả hàng); nêu mức giá nên chốt, NCC nào, giao bao lâu, và link_tra_gia.
- Không chào hỏi, không giải thích cách em tra."""

# Đủ chỗ cho phần suy nghĩ + câu trả lời: suy nghĩ cũng tính vào max_tokens.
MAX_TOKENS = 16000
# Chặn chi phí đọc web trong một request: trang sản phẩm lạ có thể rất dài. So sánh / tư vấn nhiều
# mã cần tra từng mã (tài liệu Anthropic: so nhiều món thường 10 lần tìm trở lên) — 5 lần là hết
# giữa chừng, bảng so sánh toàn "—". Mỗi lần tìm 0,01 USD; kết quả đã được lọc gọn (dynamic filtering).
WEB_SEARCH_MAX_USES = 12
WEB_FETCH_MAX_USES = 6
WEB_FETCH_MAX_CONTENT_TOKENS = 20000
# Không đặt user_location: web_search từ chối mã quốc gia VN (lỗi 400, hỏng mọi lượt). Ưu tiên
# trang Việt Nam nằm ở prompt (truy vấn tiếng Việt + danh sách trang bán dụng cụ trong nước).

# Prompt sửa trên Odoo viết cho Claude Code (tool WebFetch / WebSearch / Read). Ở chế độ
# API các tool đó mang tên khác và ảnh nằm ngay trong tin, nên nói rõ thay vì bắt người
# quản lý sửa prompt theo từng chế độ.
API_MODE_NOTE = """==================================================
GHI CHÚ CHẾ ĐỘ CHẠY
==================================================

Tool đọc trang web ở đây tên là `web_fetch` (chính là WebFetch nói ở trên), tìm trên web là
`web_search` (chính là WebSearch). Không có tool Read: ảnh người dùng đính kèm nằm ngay trong
tin nhắn, xem trực tiếp. Mọi quy tắc khác giữ nguyên."""

INLINE_IMAGE_NOTE = "(Ảnh đính kèm ngay trong tin này: %s)"

# Model chạy được bản web tool có lọc kết quả động; Haiku dùng bản cơ bản.
_BASIC_WEB_TOOL_PREFIXES = ('claude-haiku',)
# Server-side fallback khi bộ lọc an toàn từ chối nhầm. Haiku 5.5 không có.
_FALLBACK_BETA = 'server-side-fallback-2026-07-01'
_NO_FALLBACK_PREFIXES = ('claude-haiku',)

# Lịch sử API lưu nguyên khối (kể cả kết quả tool, thinking) để lượt sau Claude nhớ kết quả
# tra cứu như Claude Code --resume. Quá ngưỡng thì mở lại từ 12 tin chữ gần nhất.
# Giữ NGẮN: sale để một cuộc chat chạy cả tuần (hàng trăm tin), mỗi món hàng là một việc
# riêng — nhớ kết quả tra MISA của món từ hai chục tin trước không giúp gì, nhưng mỗi lần
# gọi API (4-6 lần một lượt) phải gửi lại hết, vừa chậm vừa tốn.
MAX_PROMPT_TOKENS = 40000
MAX_HISTORY_TURNS = 12
# Nghỉ lâu hơn ngần này thì cache đã hết hạn: gửi lại lịch sử là trả giá ghi cache cho cả
# lịch sử, đắt hơn mở lại từ tin chữ.
HISTORY_IDLE_MINUTES = 60
# Cache 1 giờ thay vì 5 phút: sale trả lời sau vài phút tới nửa tiếng là chuyện thường, cache
# 5 phút thì lượt nào cũng ghi lại cả prompt. System prompt + tool giống nhau cho mọi cuộc
# nên cache 1 giờ còn dùng chung giữa các sale.
CACHE_CONTROL = {'type': 'ephemeral', 'ttl': '1h'}


def _api_tool(tool):
    """Một tool theo định dạng Messages API (input_schema thay cho inputSchema của MCP)."""
    return {'name': tool['name'], 'description': tool['description'], 'input_schema': tool['inputSchema']}


def client_tools():
    """Tool của model chính: như máy agent, trừ tra cứu nặng (giao model phụ) + tool giao việc.

    Tra cứu nặng trả kết quả dài: model chính đọc trực tiếp thì tính token giá model chính,
    giao model phụ đọc rồi tóm tắt thì rẻ hơn nhiều lần.
    """
    return ([_api_tool(tool) for tool in MISA_TOOLS if tool['name'] not in HEAVY_QUERY_TOOLS]
            + [_api_tool(DELEGATE_TOOL)])


def worker_tools():
    """Tool của model phụ (giao_viec_tra_cuu): chỉ các tra cứu Odoo chỉ đọc."""
    return [_api_tool(tool) for tool in QUERY_TOOLS]


def server_tools(model):
    """web_search / web_fetch chạy trên máy chủ Anthropic, đúng phiên bản model hỗ trợ."""
    basic = (model or '').startswith(_BASIC_WEB_TOOL_PREFIXES)
    return [
        {'type': 'web_search_20250305' if basic else 'web_search_20260209',
         'name': 'web_search', 'max_uses': WEB_SEARCH_MAX_USES},
        {'type': 'web_fetch_20250910' if basic else 'web_fetch_20260209',
         'name': 'web_fetch', 'max_uses': WEB_FETCH_MAX_USES,
         'max_content_tokens': WEB_FETCH_MAX_CONTENT_TOKENS},
    ]


def build_tools(model):
    """Toàn bộ tool cho một request. Thứ tự cố định: đổi thứ tự là mất cache prompt."""
    return client_tools() + server_tools(model)


def build_system(prompt_text):
    """System prompt dạng khối, đặt điểm cache ở cuối (prompt dài, gần như không đổi)."""
    return [{
        'type': 'text',
        'text': (prompt_text or '').rstrip() + "\n\n" + API_MODE_NOTE + "\n",
        'cache_control': CACHE_CONTROL,
    }]


def request_extras(model):
    """Tham số beta theo model. Trả dict ``{'betas': [...], 'fallbacks': ...}`` hoặc ``{}``.

    Fallback "default": bộ lọc an toàn từ chối nhầm thì Anthropic chạy lại trên model
    thay thế ngay trong cùng request, sale không thấy lỗi.
    """
    if (model or '').startswith(_NO_FALLBACK_PREFIXES):
        return {}
    return {'betas': [_FALLBACK_BETA], 'fallbacks': 'default'}


def context_key(model, prompt_version):
    """Vân tay những thứ phải giữ nguyên thì lịch sử cũ mới dùng tiếp được.

    Đổi model, prompt hay danh sách tool mà vẫn gửi lịch sử cũ là API từ chối khối thinking
    cũ (thinking gắn với đúng model và đúng phần đầu hội thoại) — phải mở lại lịch sử.
    Trả: 16 ký tự hex.
    """
    raw = json.dumps([model, prompt_version, build_tools(model)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def user_content(text, images):
    """Nội dung một tin user: ảnh trước, chữ sau.

    Nhận: text, images = list dict ``{'filename', 'mimetype', 'data'}`` (data base64 str).
    Trả: list content block. Biên: không có ảnh -> chỉ một khối chữ.
    """
    blocks = []
    for image in images or []:
        blocks.append({'type': 'text', 'text': image['filename']})
        blocks.append({'type': 'image', 'source': {
            'type': 'base64', 'media_type': image['mimetype'], 'data': image['data'],
        }})
    blocks.append({'type': 'text', 'text': text or '(trống)'})
    return blocks


def history_content(content):
    """Khối assistant để lưu / gửi lại ở request sau.

    Bỏ khối ``fallback``: chỉ là mốc đánh dấu đổi model, không mang nội dung.
    """
    return [block for block in content or [] if block.get('type') != 'fallback']


def reply_text(content):
    """Chữ trả lời cho sale: nối các khối text. Biên: không có khối text -> ''."""
    return "\n\n".join(
        block['text'].strip() for block in content or []
        if block.get('type') == 'text' and (block.get('text') or '').strip()
    )


# Tool chỉ hiện thứ lên màn hình, không đem về dữ liệu mới: Claude hay viết xong câu trả lời rồi
# gọi chúng cùng bước, bước sau chỉ còn "Trang đã mở...". Chữ của bước đó là câu trả lời thật.
DISPLAY_TOOLS = frozenset({'show_in_search_page', 'so_sanh_thong_so'})


def turn_reply(step_contents):
    """Chữ trả lời cho sale của cả lượt.

    Nhận: list content của từng bước Claude trong lượt, theo thứ tự (bước cuối là lúc dừng).
    Trả: chữ bước cuối, đứng sau chữ của các bước trước mà chỉ gọi tool hiển thị
        (DISPLAY_TOOLS). Chữ viết trước tool tra cứu là câu dạo đầu khi chưa có kết quả nên
        bỏ. Đoạn lặp y nguyên chỉ giữ một lần. Biên: list rỗng -> ''.
    """
    parts = []
    for index, content in enumerate(step_contents):
        calls = tool_uses(content)
        is_last = index == len(step_contents) - 1
        if not is_last and not (calls and all(call.get('name') in DISPLAY_TOOLS for call in calls)):
            continue
        text = reply_text(content)
        if text and text not in parts:
            parts.append(text)
    return "\n\n".join(parts)


def tool_uses(content):
    """Các lệnh gọi tool MISA (client tool) trong một phản hồi, theo thứ tự."""
    return [block for block in content or [] if block.get('type') == 'tool_use']


def tool_result(tool_use_id, result):
    """Khối tool_result từ dict kết quả handler (luôn có 'status')."""
    return {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': json.dumps(result, ensure_ascii=False, default=str),
        'is_error': (result or {}).get('status') == 'error',
    }


def load_history(raw):
    """Đọc lịch sử đã lưu. Biên: rỗng / hỏng / không phải list -> []."""
    try:
        history = json.loads(raw or '[]')
    except ValueError:
        return []
    return history if isinstance(history, list) else []


def history_too_long(history, last_prompt_tokens=0, idle_minutes=0):
    """Có nên bỏ lịch sử, mở lại từ tin chữ gần nhất không.

    Nhận: lịch sử, số token prompt của request gần nhất (API báo về; 0 nếu chưa biết), số
    phút từ lượt API trước (0 nếu chưa biết).
    Trả True khi quá số lượt, quá dài, hoặc nghỉ quá lâu.
    """
    turns = sum(1 for msg in history if msg.get('role') == 'user' and _is_sale_turn(msg))
    return (turns >= MAX_HISTORY_TURNS
            or (last_prompt_tokens or 0) > MAX_PROMPT_TOKENS
            or (idle_minutes or 0) > HISTORY_IDLE_MINUTES)


def _is_sale_turn(message):
    # Tin user chứa tool_result là kết quả tool, không phải một lượt sale gõ.
    content = message.get('content')
    if isinstance(content, str):
        return True
    return not any(block.get('type') == 'tool_result' for block in content or [])
