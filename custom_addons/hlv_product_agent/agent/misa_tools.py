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
    "so_sanh_thong_so",
    "xem_thong_so_da_luu",
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
            "Sửa một trường (tên/mã/mô tả) của hàng ĐÃ CÓ trên MISA. Sửa TÊN thì hệ thống đổi "
            "luôn tên sản phẩm Odoo cùng hàng (truyền code = mã hàng từ kết quả search để tìm "
            "đúng sản phẩm Odoo); kết quả có 'odoo' cho biết phía Odoo đã đổi hay chưa. Cần người dùng xác nhận "
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
                "code": {"type": "string", "description": "Mã hàng hiện tại (từ kết quả search), để sửa cả Odoo"},
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
    {
        "name": "so_sanh_thong_so",
        "description": (
            "Hiện BẢNG SO SÁNH THÔNG SỐ 2-5 mã trong khung nổi trên trang của người dùng (món gốc + "
            "mã thay thế, hoặc các mẫu đang tư vấn). Em tự tìm thông số trước (mô tả Odoo / MISA, "
            "TÌM WEB trang chính hãng / nhà phân phối), rồi đưa DỮ LIỆU — hệ thống tự dựng bảng, tô "
            "các dòng khác nhau. Chọn 5-12 thông số quyết định việc chọn mua (công suất, lực, điện "
            "áp / pin, tốc độ, kích thước, trọng lượng, phụ kiện kèm, bảo hành...). Không chắc giá trị "
            "thì ghi '—', đừng đoán. Gọi lại là thay bảng. Câu trả lời trong chat vẫn chỉ ý chính."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tieu_de": {"type": "string", "description": "Tiêu đề ngắn, vd 'GDS 18V-350 và mã thay thế'"},
                "san_pham": {
                    "type": "array", "minItems": 2, "maxItems": 5,
                    "description": "Các mã, món gốc đứng đầu",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ten": {"type": "string", "description": "Tên / model ngắn"},
                            "ma": {"type": "string", "description": "Mã hàng (rỗng nếu chưa có)"},
                            "gia": {"type": "number", "description": "Giá bán (đồng); 0 nếu chưa biết"},
                            "ton": {"type": "number", "description": "Tồn khả dụng; -1 nếu không áp dụng"},
                            "anh": {"type": "string", "description": "Link ảnh https (rỗng nếu không có)"},
                            "nguon": {"type": "string", "description": "Link trang lấy thông số (rỗng nếu không có)"},
                            "ghi_chu": {"type": "string", "description": "Nhãn ngắn: 'món gốc', 'rẻ hơn 300k'..."},
                        },
                        "required": ["ten"],
                        "additionalProperties": False,
                    },
                },
                "thong_so": {
                    "type": "array", "minItems": 1, "maxItems": 25,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ten": {"type": "string", "description": "Tên thông số, kèm đơn vị"},
                            "gia_tri": {"type": "array", "items": {"type": "string"},
                                        "description": "Giá trị theo đúng thứ tự san_pham"},
                        },
                        "required": ["ten", "gia_tri"],
                        "additionalProperties": False,
                    },
                },
                "ket_luan": {"type": "string", "description": "1-2 câu: chọn mã nào khi nào (có thể rỗng)"},
            },
            "required": ["tieu_de", "san_pham", "thong_so"],
            "additionalProperties": False,
        },
    },
]


# =============================================================================
# Tra cứu Odoo (chỉ đọc) + bảng trình bày
# =============================================================================
_CODE_ARG = {"type": "string", "description": "Mã hàng (ưu tiên, đúng như Odoo / kết quả search) hoặc tên"}
_WAREHOUSE_ARG = {"type": "string", "description": "Mã hoặc tên kho để lọc; chuỗi rỗng = mọi kho"}


_PRODUCT_ID_ARG = {
    "type": "integer",
    "description": "ID sản phẩm Odoo lấy từ danh sách 'candidates' khi tool báo ambiguous; "
                   "có product_id thì code chỉ để đọc cho dễ, không dùng để tìm.",
}


def _query_tool(name, description, properties=None, required=("code",)):
    props = {"code": _CODE_ARG, "product_id": _PRODUCT_ID_ARG}
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
        "Ai đang giữ hàng của một mã: phiếu giữ hàng đã duyệt (sale, khách, dự án, hạn giữ, kho), "
        "đơn bán đang giữ chỗ, và phiếu kho khác đang giữ chỗ (chuyển kho, trả hàng, phiếu tay: số "
        "phiếu, loại, đối tác, nguồn). Cột 'Giữ' trên trang tra tồn là tổng của cả ba.",
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
        "Dữ liệu trang hỏi / tra giá NCC của một mã: tóm tắt theo NCC (mua gần nhất / thấp nhất, "
        "báo giá gần nhất / thấp nhất), các lần mua đã nhập kho và báo giá NCC gần nhất (giá SAU VAT, "
        "thời gian giao, còn hiệu lực không), kèm link_tra_gia. Dùng để GỢI Ý GIÁ MUA khi cần mua "
        "hàng / hỏi NCC. Tài khoản chưa có quyền hỏi giá NCC thì tool từ chối.",
    ),
]
QUERY_TOOLS += [
    {
        "name": "tim_hang_tuong_tu",
        "description": (
            "Lấy danh sách hàng CÒN TỒN: mã, tên, nhóm, mô tả bán hàng, tồn, khả dụng, giá, số đã bán "
            "180 ngày (xếp mã bán chạy trước). Dùng để (1) tìm mã THAY THẾ món gốc, (2) TƯ VẤN khi sale "
            "hỏi chung một loại hàng — code rỗng, tu_khoa = loại hàng + hãng (vd 'may siet bu long "
            "bosch'), tu_khoa_khac = các cách gọi khác của cùng loại máy (sale và tên trong kho hay gọi "
            "khác nhau). Tool KHÔNG chấm độ giống / độ hợp — em phải xét bằng THÔNG SỐ (công năng, nguồn "
            "điện / điện áp, kích thước lắp, tải, chuẩn...), chưa rõ thì tìm web theo mã. Mặc định cùng "
            "nhóm hàng với món gốc; nhóm quá rộng / sai thì truyền nhom khác hoặc tu_khoa để khoanh lại."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mã món gốc nếu Odoo có; chuỗi rỗng nếu không"},
                "product_id": _PRODUCT_ID_ARG,
                "nhom": {"type": "string", "description": "Tên nhóm hàng Odoo để tìm (thay nhóm của món gốc); rỗng = dùng nhóm món gốc"},
                "tu_khoa": {"type": "string", "description": "Từ khoá loại hàng + hãng (so không dấu, mọi từ phải có; KHÔNG đưa thuộc tính như 'pin', 'cầm tay' — tên hàng hay không ghi); rỗng = không lọc"},
                "tu_khoa_khac": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                                 "description": "Các cách gọi khác của cùng loại hàng (vd 'khoan bua bosch' cho 'khoan be tong bosch'); khớp tu_khoa HOẶC một cách gọi là lấy"},
                "cung_nhom": {"type": "boolean", "description": "Giới hạn trong nhóm hàng của món gốc (mặc định true)"},
            },
            "required": ["code", "tu_khoa"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tim_ncc_dong_hang",
        "description": (
            "Tìm NCC đã từng bán cho mình dòng hàng này (theo đơn mua đã xác nhận): số lần mua, lần "
            "mua cuối, vài mặt hàng mẫu, mức khớp (tu_khoa_va_nhom > cung_nhom > tu_khoa). Dùng khi "
            "hàng không có trong kho lẫn MISA: tư vấn sale nên hỏi giá NCC nào. Truyền code của một món "
            "CÙNG DÒNG đã có (vd mã tương tự vừa tìm) để lấy đúng nhóm hàng, kèm từ khoá ngắn: hãng + "
            "dòng / loại hàng (vd 'MILWAUKEE M18', 'phốt viton')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tu_khoa": {"type": "string", "description": "2-4 từ khoá (so không dấu); rỗng nếu chỉ dùng code"},
                "code": {"type": "string", "description": "Mã một món cùng dòng để lấy nhóm hàng; rỗng nếu không có"},
                "product_id": _PRODUCT_ID_ARG,
            },
            "required": ["tu_khoa", "code"],
            "additionalProperties": False,
        },
    },
]
QUERY_TOOL_NAMES = frozenset(tool["name"] for tool in QUERY_TOOLS)
# Kết quả ngắn: gọi thẳng rẻ hơn giao người khác đọc. Còn lại kết quả dài — ở chế độ Claude
# API giao model rẻ (giao_viec_tra_cuu) đọc rồi tóm tắt, model chính chỉ đọc bản tóm tắt.
LIGHT_QUERY_TOOLS = frozenset({
    "xem_ton_kho", "xem_gia", "xem_thanh_phan_combo", "tim_hang_tuong_tu", "tim_ncc_dong_hang",
})
HEAVY_QUERY_TOOLS = QUERY_TOOL_NAMES - LIGHT_QUERY_TOOLS
READ_ONLY_TOOLS = READ_ONLY_TOOLS | QUERY_TOOL_NAMES

PANEL_TOOL = {
    "name": "show_panel",
    "description": (
        "Hiện một BẢNG nổi trên trang của người dùng (đè lên bảng tra tồn, họ kéo đi / đóng được) "
        "với HTML em tự dựng: bảng so sánh, thẻ số liệu, biểu đồ cột vẽ bằng SVG... Dùng khi dữ "
        "liệu nhiều dòng / nhiều cột, đọc trong khung chat bất tiện. Chỉ HTML + CSS inline. KHÔNG "
        "dùng <script>, <canvas>, thư viện biểu đồ (Chart.js...) hay onclick: bảng khoá script, có "
        "là bị từ chối. Biểu đồ vẽ bằng SVG tĩnh, tự tính toạ độ. Không ảnh ngoài. Gọi lại là thay "
        "nội dung bảng. Vẫn tóm tắt kết luận bằng chữ trong câu trả lời."
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

# Tạm tắt vẽ bảng (10/2026): trợ lý chỉ trả lời bằng chữ. Bật lại: đổi True — handler, khung
# hiện bảng trên trang và kiểm HTML (panel_html) vẫn giữ nguyên.
PANEL_ENABLED = False
# Thông số đã tra web, lưu theo mã: nhiều sale hỏi cùng một món thì chỉ tìm web một lần.
SPEC_TOOLS = [
    {
        "name": "xem_thong_so_da_luu",
        "description": (
            "Thông số kỹ thuật em đã tra trên web và lưu lại cho các mã (kể cả mã chưa có trong "
            "Odoo). GỌI TRƯỚC khi tìm web thông số. con_dung=true: dùng luôn, khỏi tìm web. Quá hạn "
            "hoặc chưa lưu: tìm web rồi gọi luu_thong_so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "maxItems": 10,
                          "description": "Các mã cần xem (mã gốc + các mã ứng viên)"},
            },
            "required": ["codes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "luu_thong_so",
        "description": (
            "Lưu (hoặc ghi đè) thông số kỹ thuật của MỘT mã vừa tra được trên web, để lần sau khỏi "
            "tìm lại. Gọi ngay sau khi tra ra, mỗi mã một lần; cũng gọi khi sale báo / web cho thấy "
            "hàng đã đổi thông số. CHỈ thông số kỹ thuật — KHÔNG ghi giá. Không cần sale xác nhận."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mã hàng / model đúng như trong Odoo / MISA hoặc mã hãng"},
                "thong_so": {"type": "string", "description": "Các thông số chính, mỗi dòng 'tên: giá trị đơn vị' (vd 'Lực siết tối đa: 745 Nm')"},
                "nguon": {"type": "string", "description": "Link nguồn đã đọc, mỗi dòng một link; ghi (nước ngoài) nếu không phải web VN"},
            },
            "required": ["code", "thong_so", "nguon"],
            "additionalProperties": False,
        },
    },
]
TOOLS = TOOLS + ([PANEL_TOOL] if PANEL_ENABLED else []) + QUERY_TOOLS + SPEC_TOOLS

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
