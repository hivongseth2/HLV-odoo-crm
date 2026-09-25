# -*- coding: utf-8 -*-
"""Khai báo các tool MISA mà Claude được dùng.

Chỉ là schema: tool thật chạy trên Odoo (nơi giữ tài khoản MISA). MCP server nhận
lệnh gọi từ Claude rồi chuyển nguyên tên + tham số lên Odoo.
"""

# Tool chỉ đọc: gọi lại cùng tham số là vô hại nên được cache trong một lượt.
# Tool ghi không nằm ở đây vì gọi lại là tạo/sửa trùng dữ liệu trên MISA.
READ_ONLY_TOOLS = frozenset({
    "search_product_misa",
    "search_category_misa",
    "get_category_info",
})

TOOLS = [
    {
        "name": "search_product_misa",
        "description": (
            "Tìm hàng hóa đã có trong MISA theo tên hoặc mã. LUÔN gọi trước khi tạo mới. "
            "MISA tìm theo kiểu 'chứa nguyên cụm', nên từ khóa ngắn (mã model, 2-3 từ chính) "
            "cho kết quả tốt hơn cả câu dài."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tên hoặc từ khóa cần tìm (VD: Khoan FPD3, Bulong M12). Chuỗi rỗng nếu chỉ tìm theo mã.",
                },
                "code": {
                    "type": "string",
                    "description": "Mã hàng cần tìm. Chuỗi rỗng nếu chỉ tìm theo tên.",
                },
            },
            "required": ["name", "code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_product_misa",
        "description": (
            "Tạo hàng hóa mới trong MISA. CHỈ GỌI KHI NGƯỜI DÙNG ĐÃ XÁC NHẬN 'OK' / 'ĐỒNG Ý' "
            "cho đúng bộ dữ liệu đang gửi. Mã và tên phải có nguyên văn trong đề xuất ở câu "
            "trả lời trước, không thì trả 'need_confirmation'. Hệ thống kiểm trùng lần cuối "
            "trước khi tạo; 'duplicate' nghĩa là đã có hàng trùng, không được tạo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mã hàng (viết liền, in hoa, không dấu)"},
                "name": {"type": "string", "description": "Tên hàng chuẩn hóa đầy đủ"},
                "price": {"type": "number", "description": "Giá bán lẻ (VNĐ). Không có thì 0."},
                "price_pu": {"type": "number", "description": "Giá nhập (VNĐ). Không có thì 0."},
                "tax": {"type": "number", "description": "Thuế GTGT (%). Không có thì 0."},
                "unit": {"type": "string", "description": "Đơn vị tính (Cái, Bộ, Hộp, Chai...)"},
                "category": {"type": "string", "description": "Tên nhóm hàng"},
                "category_id": {
                    "type": "integer",
                    "description": "ID nhóm hàng. Phải lấy từ search_category_misa, không tự bịa.",
                },
                "type": {
                    "type": "string",
                    "enum": ["goods", "service", "finished_product"],
                    "description": "Loại hàng hóa, mặc định 'goods'",
                },
                "description": {
                    "type": "string",
                    "description": 'Mô tả/thông số trên MISA, có thể là chuỗi JSON, VD: {"Vật liệu": "Thép"}',
                },
            },
            "required": [
                "code", "name", "price", "price_pu", "tax",
                "unit", "category", "category_id", "type", "description",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_product_misa",
        "description": (
            "Sửa một trường (tên/mã/mô tả) của hàng ĐÃ CÓ trên MISA. Cần người dùng xác nhận "
            "như tạo mới: new_value phải có nguyên văn trong đề xuất ở câu trả lời trước, không "
            "thì trả 'need_confirmation'. misa_id và old_value lấy từ kết quả search_product_misa."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "misa_id": {"type": "string", "description": "MISA ID lấy từ kết quả search"},
                "field": {
                    "type": "string",
                    "enum": ["name", "code", "Description"],
                    "description": "name=tên, code=mã, Description=mô tả",
                },
                "new_value": {"type": "string", "description": "Giá trị mới"},
                "old_value": {"type": "string", "description": "Giá trị cũ, lấy từ kết quả search"},
            },
            "required": ["misa_id", "field", "new_value", "old_value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_category_info",
        "description": "Lấy tên thật của nhóm hàng từ ID, dùng khi nghi ngờ một ID nhóm.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category_id": {"type": "string", "description": "ID nhóm hàng (VD: 52)"},
            },
            "required": ["category_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_category_misa",
        "description": "Tìm ID thật của nhóm hàng theo tên. Bắt buộc gọi trước khi tạo hàng.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên nhóm cần tìm (VD: Bảo hộ lao động)"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)
