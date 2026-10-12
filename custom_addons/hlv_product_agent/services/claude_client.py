# -*- coding: utf-8 -*-
"""Client Claude API dùng chung: trợ lý tạo mã hàng và các module khác gọi Claude bằng API key của
module này (Cài đặt → Tồn kho → Trợ lý tạo mã hàng) — một chỗ cấu hình, một chỗ né lỗi brotli.

Không đụng ``self.env``: key / model do bên gọi đưa vào.
"""


def load_anthropic():
    """Thư viện anthropic, hoặc None nếu Odoo chưa cài.

    Import muộn: chế độ máy văn phòng không cần thư viện này, thiếu nó không được làm hỏng
    cả module. Bên gọi tự báo lỗi bằng lời của mình.
    """
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic


def make_client(anthropic, api_key, **options):
    """Client Claude API chỉ nhận câu trả lời nén gzip.

    httpx2 thấy có module brotli là xin nén brotli, rồi gọi API của brotli >= 1.2. Máy
    chủ Odoo có sẵn brotli cũ: giải nén lỗi TypeError, SDK báo thành "không kết nối được"
    và thử lại mãi vẫn hỏng. Xin gzip thì không phụ thuộc bản brotli nào.
    """
    return anthropic.Anthropic(
        api_key=api_key, default_headers={'Accept-Encoding': 'gzip, deflate'}, **options)


def connection_cause(error):
    """Lỗi gốc bên dưới APIConnectionError (chuỗi ≤ 150 ký tự), để biết là mạng hay lỗi khác bị gói lại."""
    cause = error.__cause__ or error.__context__
    return ("%s: %s" % (type(cause).__name__, cause))[:150] if cause else str(error)


def api_error_message(anthropic, error):
    """Câu tiếng Việt cho người dùng đọc từ một lỗi SDK (anthropic.APIError).

    Nhận: module anthropic (để so lớp lỗi), lỗi bắt được. Trả: chuỗi, không có dấu chấm cuối để bên gọi
    ghép tiếp. Lỗi lạ → "Claude API lỗi <mã>, thử lại sau".
    """
    if isinstance(error, anthropic.BadRequestError):
        return "Claude API không nhận yêu cầu (%s)" % str(error)[:200]
    if isinstance(error, anthropic.AuthenticationError):
        return "API key Claude sai hoặc đã bị thu hồi"
    if isinstance(error, anthropic.PermissionDeniedError):
        return "API key Claude không có quyền dùng model này"
    if isinstance(error, anthropic.RateLimitError):
        return "Claude API đang hết hạn mức, thử lại sau ít phút"
    if isinstance(error, anthropic.APIConnectionError):
        return "không kết nối được Claude API (%s)" % connection_cause(error)
    return "Claude API lỗi %s, thử lại sau" % getattr(error, 'status_code', '?')
