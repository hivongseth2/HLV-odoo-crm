# -*- coding: utf-8 -*-
"""Khai báo tool gửi kèm mỗi lần gọi OpenAI Responses API.

Util thuần: không đụng ``self.env``, không side effect. Vào cấu hình, ra schema.
"""

# Vector store mặc định (chứa category.json). Có thể ghi đè trong cấu hình.
DEFAULT_VECTOR_STORE_IDS = ["vs_69328ab5789081918759b56def1c641a"]

# Tool chỉ đọc: gọi lại cùng tham số là vô hại nên được cache trong một lượt.
# Tool ghi (create/update) không nằm ở đây vì gọi lại là tạo/sửa trùng dữ liệu.
READ_ONLY_TOOLS = frozenset({
    "search_product_misa",
    "search_category_misa",
    "get_category_info",
})

FUNCTION_TOOLS = [
    {
        "type": "function",
        "name": "search_product_misa",
        "description": (
            "Tìm sản phẩm đã có trong MISA theo tên hoặc mã. LUÔN gọi trước khi tạo mới. "
            "Nếu không thấy, hãy thử lại với từ khóa ngắn hơn (ví dụ chỉ mã model) "
            "trước khi kết luận là chưa có."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tên hoặc từ khóa cần tìm (VD: Khoan FPD3, Bulong M12)",
                },
                "code": {
                    "type": "string",
                    "description": "Mã sản phẩm cần tìm. Để chuỗi rỗng nếu chỉ tìm theo tên.",
                },
            },
            "required": ["name", "code"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_product_misa",
        "description": (
            "Tạo sản phẩm mới trong MISA. "
            "CHỈ GỌI KHI NGƯỜI DÙNG ĐÃ XÁC NHẬN 'OK' HOẶC 'ĐỒNG Ý'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Mã sản phẩm (viết liền, in hoa, không dấu. VD: MAYKHOAN01)",
                },
                "name": {
                    "type": "string",
                    "description": "Tên sản phẩm chuẩn hóa đầy đủ (VD: Máy khoan Pin Milwaukee FPD3)",
                },
                "price": {"type": "number", "description": "Giá bán đề xuất (VNĐ). Mặc định 0."},
                "price_pu": {"type": "number", "description": "Giá mua (VNĐ). Mặc định 0."},
                "tax": {"type": "number", "description": "Thuế VAT (thường là 8 hoặc 10)"},
                "unit": {"type": "string", "description": "Đơn vị tính (Cái, Bộ, Hộp, Chai...)"},
                "category": {"type": "string", "description": "Tên nhóm hàng"},
                "category_id": {
                    "type": "integer",
                    "description": (
                        "ID nhóm hàng. Phải lấy từ search_category_misa hoặc get_category_info, "
                        "không được tự bịa."
                    ),
                },
                "type": {
                    "type": "string",
                    "enum": ["goods", "service", "finished_product"],
                    "description": "Loại hàng hóa (mặc định 'goods')",
                },
                "Description": {
                    "type": "string",
                    "description": 'Mô tả trên MISA CRM. Có thể là chuỗi JSON, VD: {"Vật liệu": "Thép"}',
                },
            },
            "required": [
                "code", "name", "price", "price_pu", "tax",
                "unit", "category", "category_id", "type", "Description",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_product_misa",
        "description": "Cập nhật một trường của sản phẩm trên MISA CRM. Cần misa_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "misa_id": {
                    "type": "string",
                    "description": "MISA product ID (VD: 77449), lấy từ cột misa_id của kết quả search",
                },
                "field": {
                    "type": "string",
                    "enum": ["name", "code", "Description"],
                    "description": "Trường cần cập nhật: name=tên, code=mã, Description=mô tả",
                },
                "new_value": {"type": "string", "description": "Giá trị mới"},
                "old_value": {
                    "type": "string",
                    "description": "Giá trị cũ để đối chứng, lấy từ kết quả search trước đó",
                },
            },
            "required": ["misa_id", "field", "new_value", "old_value"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_category_info",
        "description": "Lấy tên chính xác của nhóm sản phẩm từ ID, dùng để double check ID nhóm.",
        "parameters": {
            "type": "object",
            "properties": {
                "category_id": {"type": "string", "description": "ID của nhóm sản phẩm (VD: 52)"},
            },
            "required": ["category_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_category_misa",
        "description": "Tìm ID nhóm sản phẩm theo tên. Dùng trước khi tạo sản phẩm để lấy category_id đúng.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tên nhóm cần tìm (VD: Vật tư khí nén, Bảo hộ lao động)",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def parse_vector_store_ids(raw):
    """Tách chuỗi cấu hình thành danh sách vector store id.

    Nhận: chuỗi các id ngăn bởi dấu phẩy/xuống dòng, hoặc None.
    Trả: list[str] đã bỏ khoảng trắng và phần tử rỗng.
    Biên: None / chuỗi rỗng / toàn dấu phẩy -> [].
    """
    if not raw:
        return []
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def build_tools_schema(vector_store_ids=None, enable_web_search=True):
    """Dựng danh sách tool cho tham số ``tools`` của Responses API.

    Nhận: danh sách vector store id (None -> dùng mặc định), cờ bật web search.
    Trả: list[dict] schema tool, luôn có đủ các function tool.
    Biên: vector_store_ids rỗng -> bỏ hẳn tool file_search thay vì gửi list rỗng
    (OpenAI từ chối file_search không có store).
    """
    store_ids = DEFAULT_VECTOR_STORE_IDS if vector_store_ids is None else list(vector_store_ids)
    tools = [dict(tool) for tool in FUNCTION_TOOLS]
    if store_ids:
        tools.append({"type": "file_search", "vector_store_ids": store_ids})
    if enable_web_search:
        tools.append({"type": "web_search"})
    return tools
