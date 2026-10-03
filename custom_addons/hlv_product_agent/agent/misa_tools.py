# -*- coding: utf-8 -*-
"""Khai báo các tool MISA mà Claude được dùng.

Chỉ là schema: tool thật chạy trên Odoo (nơi giữ tài khoản MISA). MCP server nhận
lệnh gọi từ Claude rồi chuyển nguyên tên + tham số lên Odoo.
"""

# Tool chỉ đọc: gọi lại cùng tham số là vô hại nên được cache trong một lượt.
# Tool ghi không nằm ở đây vì gọi lại là tạo/sửa trùng dữ liệu trên MISA.
READ_ONLY_TOOLS = frozenset({
    "search_product_misa",
    "get_combo_misa",
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
        "name": "create_combo_misa",
        "description": (
            "Tạo COMBO (bộ gồm nhiều hàng con) trên MISA. Luật riêng của combo: "
            "(1) MỌI mã con phải đã có trên MISA — tra từng mã bằng search_product_misa, lấy "
            "đúng mã MISA trả về; mã con chưa có thì phải tạo hàng thường trước (luồng bình "
            "thường), không được bịa mã con. "
            "(2) Quét trùng combo như hàng thường (mã + tên combo). "
            "(3) Đề xuất phải liệt kê ĐỦ: tên combo, mã combo, nhóm, ĐVT, giá, và từng dòng "
            "'mã con — tên con — số lượng'. Mã combo, tên combo và MỌI mã con phải có nguyên "
            "văn trong đề xuất, không thì trả 'need_confirmation'. "
            "(4) CHỈ GỌI sau khi người dùng xác nhận OK cho đúng đề xuất đó. "
            "Trả 'duplicate' nghĩa là mã/tên đã có, không được tạo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mã combo (viết liền, in hoa, không dấu)"},
                "name": {"type": "string", "description": "Tên combo chuẩn hóa đầy đủ"},
                "components": {
                    "type": "array",
                    "description": "Hàng con trong combo, mỗi mã một dòng",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Mã con ĐÚNG như MISA trả về khi search"},
                            "quantity": {"type": "number", "description": "Số lượng con trong 1 combo (> 0)"},
                        },
                        "required": ["code", "quantity"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
                "price": {"type": "number", "description": "Giá bán lẻ combo (VNĐ). Không có thì 0."},
                "price_pu": {"type": "number", "description": "Giá nhập combo (VNĐ). Không có thì 0."},
                "tax": {"type": "number", "description": "Thuế GTGT (%). Không có thì 8."},
                "unit": {"type": "string", "description": "ĐVT combo, thường là 'Bộ'"},
                "category_id": {
                    "type": "integer",
                    "description": "ID nhóm hàng. Phải lấy từ search_category_misa, không tự bịa.",
                },
                "description": {"type": "string", "description": "Mô tả / ghi chú thêm, có thể rỗng"},
            },
            "required": ["code", "name", "components", "price", "price_pu", "tax", "unit",
                         "category_id", "description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_combo_misa",
        "description": (
            "Xem THÀNH PHẦN hiện tại của một combo trên MISA (mã con, tên, số lượng). Bắt "
            "buộc gọi trước khi đề xuất sửa combo — search_product_misa không trả thành phần."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Mã combo"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_combo_misa",
        "description": (
            "Sửa combo ĐÃ CÓ trên MISA: thêm / bỏ / đổi số lượng mã con, đổi tên, đổi giá. "
            "components là danh sách thành phần MỚI ĐẦY ĐỦ — mã nào không có trong danh sách "
            "là bị XOÁ khỏi combo; không đổi thành phần thì truyền lại nguyên danh sách hiện "
            "tại. Trước đó: gọi get_combo_misa, rồi đề xuất theo mẫu C3 (thành phần sau khi "
            "sửa + nêu rõ thêm/bỏ/đổi gì). Mã combo, mọi mã con và tên mới (nếu đổi) phải có "
            "nguyên văn trong đề xuất, không thì trả 'need_confirmation'. CHỈ GỌI sau khi "
            "người dùng OK. Trả 'no_change' nghĩa là combo đã đúng như vậy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mã combo cần sửa"},
                "components": {
                    "type": "array",
                    "description": "Thành phần MỚI ĐẦY ĐỦ sau khi sửa",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Mã con đúng như MISA"},
                            "quantity": {"type": "number", "description": "Số lượng (> 0)"},
                        },
                        "required": ["code", "quantity"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
                "name": {"type": "string", "description": "Tên combo mới; bỏ trống nếu giữ nguyên"},
                "price": {"type": "number", "description": "Giá bán mới; không truyền nếu giữ nguyên"},
                "price_pu": {"type": "number", "description": "Giá nhập mới; không truyền nếu giữ nguyên"},
            },
            "required": ["code", "components"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_product_misa",
        "description": (
            "Sửa một trường (tên/mã/mô tả) của hàng ĐÃ CÓ trên MISA. Cần người dùng xác nhận "
            "như tạo mới: new_value phải có nguyên văn trong đề xuất ở câu trả lời trước, không "
            "thì trả 'need_confirmation'. misa_id và old_value lấy từ kết quả search_product_misa. "
            "Đổi MÃ (field=code): hệ thống đổi CẢ MISA lẫn sản phẩm Odoo cùng mã và ghi lịch sử "
            "đổi mã; đề xuất phải ghi rõ 'Mã: <mã cũ> → <mã mới>' (cả hai mã nguyên văn). Trả "
            "'duplicate' = mã mới đã thuộc hàng khác, không đổi gì; kết quả có odoo_updated=false "
            "thì báo người dùng mã Odoo chưa đổi."
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
