# -*- coding: utf-8 -*-
"""Khai báo các tool Claude được dùng: MISA, tra cứu Odoo (chỉ đọc), bảng trình bày.

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
    # Không ghi gì vào MISA; gọi lại cùng từ khoá trong một lượt thì khỏi mở trang lần nữa.
    "show_in_search_page",
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
    {
        "name": "show_in_search_page",
        "description": (
            "Mở trang tra tồn mà người dùng đang xem, tìm đúng từ khoá này, để họ thấy ngay tồn kho "
            "và giá. Dùng khi hàng người dùng hỏi / muốn tạo ĐÃ CÓ sẵn (kết luận trùng), hoặc khi "
            "họ hỏi hàng có sẵn không: truyền MÃ hàng đã có (đúng như kết quả search). Không tạo / "
            "sửa gì. Vẫn trả lời bằng chữ như bình thường; gọi tối đa một lần mỗi lượt."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Mã hàng (ưu tiên) hoặc vài từ khoá chính"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


# =============================================================================
# Tra cứu Odoo (chỉ đọc) + bảng trình bày
# =============================================================================
_CODE_ARG = {"type": "string", "description": "Mã hàng (ưu tiên, đúng như Odoo / kết quả search) hoặc tên"}
_WAREHOUSE_ARG = {"type": "string", "description": "Mã hoặc tên kho để lọc; chuỗi rỗng = mọi kho"}


def _query_tool(name, description, properties=None, required=("code",)):
    props = {"code": _CODE_ARG}
    props.update(properties or {})
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object", "properties": props,
            "required": list(required), "additionalProperties": False,
        },
    }


QUERY_TOOLS = [
    _query_tool(
        "xem_ton_kho",
        "Tồn kho hiện tại của một mã theo từng kho: thực tế, khả dụng, đang giữ (ai giữ), dự báo, "
        "SL đặt mua / đặt bán chưa về / chưa xuất. Combo: tồn theo từng mã con. Đúng số trang tra tồn.",
        {"warehouse": _WAREHOUSE_ARG}, ("code", "warehouse"),
    ),
    _query_tool(
        "xem_gia",
        "Giá hiện tại của một mã: giá bán, giá web, giá TMĐT, giá niêm yết, giá thương mại, giá vốn.",
    ),
    _query_tool(
        "xem_thanh_phan_combo",
        "Combo gồm những mã con nào, mỗi bộ cần bao nhiêu, tồn từng mã con và ráp được mấy bộ.",
    ),
    _query_tool(
        "xem_du_bao",
        "Chi tiết số dự báo: phiếu nhập từ đơn mua đang về (PO, NCC, ngày về), phiếu xuất cho đơn "
        "bán chưa giao (SO, khách), chuyển kho nội bộ đang chạy.",
        {"warehouse": _WAREHOUSE_ARG}, ("code", "warehouse"),
    ),
    _query_tool(
        "xem_vi_tri",
        "Tồn theo từng vị trí / kệ trong kho của một mã.",
        {"warehouse": _WAREHOUSE_ARG}, ("code", "warehouse"),
    ),
    _query_tool(
        "xem_dang_giu",
        "Ai đang giữ hàng của một mã: phiếu giữ hàng đã duyệt (sale, khách, dự án, hạn giữ, kho) và "
        "đơn bán đang giữ chỗ hàng trong kho.",
    ),
    _query_tool(
        "xem_lich_su_xuat_nhap",
        "Lịch sử xuất nhập (phiếu kho đã xong) của một mã trong khoảng ngày: tồn đầu / cuối kỳ, nhập "
        "mua, bán, chuyển kho, theo từng kho.",
        {
            "date_from": {"type": "string", "description": "Từ ngày YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "Đến ngày YYYY-MM-DD; rỗng = hôm nay"},
        },
        ("code", "date_from", "date_to"),
    ),
    _query_tool(
        "xem_lich_su_gia_ban",
        "Lịch sử giá bán thực tế: các dòng đơn bán gần nhất của mã (ngày, số đơn, khách, sale, SL, "
        "đơn giá, chiết khấu), mới nhất trước.",
        {"limit": {"type": "integer", "description": "Số dòng, 1-50 (mặc định 20)"}},
        ("code", "limit"),
    ),
    _query_tool(
        "xem_gia_nhap",
        "Giá nhập theo từng NCC: các lần đã mua (đơn mua đã xác nhận) và báo giá NCC gần nhất.",
    ),
]
QUERY_TOOL_NAMES = frozenset(tool["name"] for tool in QUERY_TOOLS)
# Kết quả ngắn: gọi thẳng rẻ hơn giao người khác đọc. Còn lại kết quả dài — ở chế độ Claude
# API giao model rẻ (giao_viec_tra_cuu) đọc rồi tóm tắt, model chính chỉ đọc bản tóm tắt.
LIGHT_QUERY_TOOLS = frozenset({"xem_ton_kho", "xem_gia", "xem_thanh_phan_combo"})
HEAVY_QUERY_TOOLS = QUERY_TOOL_NAMES - LIGHT_QUERY_TOOLS
READ_ONLY_TOOLS = READ_ONLY_TOOLS | QUERY_TOOL_NAMES

PANEL_TOOL = {
    "name": "show_panel",
    "description": (
        "Hiện một BẢNG nổi trên trang của người dùng (đè lên bảng tra tồn, họ kéo đi / đóng được) "
        "với HTML em tự dựng: bảng so sánh, thẻ số liệu, biểu đồ cột vẽ bằng SVG... Dùng khi dữ "
        "liệu nhiều dòng / nhiều cột, đọc trong khung chat bất tiện. Chỉ HTML + CSS inline, KHÔNG "
        "script (bị chặn), không ảnh ngoài. Gọi lại là thay nội dung bảng. Vẫn tóm tắt kết luận "
        "bằng chữ trong câu trả lời."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Tiêu đề ngắn của bảng"},
            "html": {"type": "string", "description": "Nội dung HTML (phần thân, có thể kèm <style>)"},
        },
        "required": ["title", "html"],
        "additionalProperties": False,
    },
}

TOOLS = TOOLS + [PANEL_TOOL] + QUERY_TOOLS

# Chỉ có ở chế độ Claude API (Odoo tự chạy vòng model phụ); máy agent không thấy tool này.
DELEGATE_TOOL = {
    "name": "giao_viec_tra_cuu",
    "description": (
        "Giao một việc TRA CỨU cho trợ lý phụ (model nhanh, rẻ). Trợ lý phụ có các tool "
        + ", ".join(sorted(QUERY_TOOL_NAMES)) + " — tự gọi bao nhiêu cũng được — rồi trả bản tóm "
        "tắt kèm số liệu chính. Dùng cho câu hỏi cần lịch sử / nhiều truy vấn / kết quả dài (lịch sử "
        "xuất nhập, lịch sử giá bán, ai đang giữ, hàng đang về, vị trí, giá nhập). Câu hỏi tồn kho "
        "/ giá hiện tại / thành phần combo thì tự gọi tool trực tiếp, nhanh hơn. Viết nhiệm vụ rõ: "
        "mã hàng, khoảng ngày, cần số liệu gì, có cần dạng bảng không."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "nhiem_vu": {"type": "string", "description": "Việc cần tra, đủ mã / ngày / yêu cầu đầu ra"},
        },
        "required": ["nhiem_vu"],
        "additionalProperties": False,
    },
}

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)
