# -*- coding: utf-8 -*-
"""Dựng yêu cầu cho Claude đề xuất MẪU FILE của một NCC (dòng tiêu đề, cột nào là gì, tiền tố mã, hãng, giá theo nghìn
đồng, dòng tiêu đề nhóm) từ vài chục dòng đầu file, và đọc kết quả.

Util thuần: vào list / chuỗi, ra chuỗi / dict. Không đụng env, không gọi mạng.

Chỉ gọi khi cần đề xuất mẫu (lần đầu nhận file của NCC, NCC đổi khung) — các file sau đọc thẳng theo mẫu.
Người bên mình vẫn xem lại mẫu một lần; AI chỉ thay phần đoán theo từ khoá (import_utils.propose_roles).
"""

import json

from ..models.import_utils import ROLE_STOCK, ROLES, cell_text, column_letter

# Bấy nhiêu dòng đầu đủ thấy tiêu đề thư, dòng tiêu đề và vài dòng dữ liệu; ô dài cắt bớt.
SAMPLE_ROWS = 40
CELL_MAX = 60
MAX_TOKENS = 8000
NOTE_MAX = 300
ROLE_KEYS = [key for key, _label in ROLES]

SYSTEM_PROMPT = """Bạn giúp phòng thu mua của một công ty thương mại dụng cụ / thiết bị đọc file Excel nhà cung cấp (NCC) gửi: file tồn kho hoặc bảng giá, mỗi NCC một khung riêng (tiếng Việt / Anh / Trung, có thể có tiêu đề thư, logo, ghi chú ở đầu file).

Bạn nhận vài chục dòng đầu của một sheet: mỗi dòng ghi số dòng Excel và các ô theo chữ cái cột. Hãy cho biết:
- header_row: số dòng Excel của dòng tiêu đề cột (dòng ngay trên dữ liệu hàng hoá). header_rows: 2 nếu tiêu đề hai tầng (dòng trên là nhóm — vd tên kho — dòng ngay dưới là cột con), còn lại 1.
- columns: vai trò từng cột có dữ liệu. role là một trong:
  "code" mã hàng của NCC; "name" tên hàng (ưu tiên cột tên tiếng Việt); "name_alt" tên phụ (tên tiếng Trung / Anh, tên gốc); "uom" đơn vị tính; "stock" số tồn của MỘT kho (mỗi kho một cột — warehouse là tên kho ngắn gọn, ưu tiên phần chữ Latin, vd "KHO BN"); "price" đơn giá CHƯA VAT; "price_incl" đơn giá SAU VAT (cột ghi gồm VAT / sau thuế / 含税); "vat" % VAT; "ignore" bỏ qua (STT, thành tiền, ghi chú, quy cách…).
  Chỉ một cột "price" và một cột "price_incl". Nhiều cột giá (giá sỉ / lẻ / đại lý / niêm yết): chọn cột là giá NCC bán cho công ty (giá đại lý / giá sỉ; chỉ có giá niêm yết thì lấy giá niêm yết), các cột giá khác "ignore", và nói rõ trong note. Cột giá không ghi gì về VAT → "price".
- code_prefixes: phần chữ NCC tự thêm đều đặn trước mã hãng (vd mã SC03200, SC97813 trong khi mã hãng là 03200, 97813 → "SC"). Không chắc → "".
- brand: hãng nếu file gần như chỉ một hãng (vd SATA). Nhiều hãng / không rõ → "".
- price_in_thousands: true nếu giá trong file ghi theo NGHÌN đồng (tiêu đề ghi "nghìn đồng", "x1000", "(1.000đ)", hoặc số quá nhỏ so với mặt hàng — vd 310 cho máy hàn 60W). Không có cột giá → false.
- skip_group_rows: true nếu vùng dữ liệu có dòng tiêu đề nhóm xen giữa (tên nhóm hàng, không có ĐVT, không có số tồn / giá) cần bỏ qua.
- note: một hai câu tiếng Việt nói điểm đáng chú ý cho người xem lại (cột giá đã chọn vì sao, giá theo nghìn đồng, dòng nhóm…). Không có gì → "".
Không đoán bừa: không chắc vai trò một cột thì "ignore"."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "header_row": {"type": "integer"},
        "header_rows": {"type": "integer", "enum": [1, 2]},
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "role": {"type": "string", "enum": ROLE_KEYS},
                    "warehouse": {"type": "string"},
                },
                "required": ["column", "role", "warehouse"],
                "additionalProperties": False,
            },
        },
        "code_prefixes": {"type": "string"},
        "brand": {"type": "string"},
        "price_in_thousands": {"type": "boolean"},
        "skip_group_rows": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["header_row", "header_rows", "columns", "code_prefixes", "brand", "price_in_thousands",
                 "skip_group_rows", "note"],
    "additionalProperties": False,
}


def template_message(vendor, sheet_names, sheet_name, grid):
    """Tin gửi Claude: tên NCC, các sheet, rồi SAMPLE_ROWS dòng đầu dạng "Dòng 4: A=STT | B=MS | …".

    Nhận: tên NCC; tên các sheet; sheet đang đọc; lưới (xlsx_grid.read_grid). Dòng trống bỏ qua (vẫn giữ số dòng
    Excel thật); ô dài cắt còn CELL_MAX ký tự. Lưới rỗng → chỉ phần giới thiệu.
    """
    lines = ["NCC: %s." % vendor, "Các sheet: %s. Đang đọc: %s." % (", ".join(sheet_names), sheet_name or sheet_names[0])]
    for index, row in enumerate(grid[:SAMPLE_ROWS]):
        cells = ["%s=%s" % (column_letter(col), _short(value)) for col, value in enumerate(row) if cell_text(value)]
        if cells:
            lines.append("Dòng %s: %s" % (index + 1, " | ".join(cells)))
    return "\n".join(lines)


def _short(value):
    text = " ".join(cell_text(value).split())
    return text if len(text) <= CELL_MAX else text[:CELL_MAX - 1] + "…"


def column_index(letter):
    """Chữ cái cột Excel → chỉ số từ 0: "A" → 0, "AA" → 26. Không phải chữ cái → None."""
    letter = (letter or "").strip().upper()
    if not letter.isalpha() or not letter.isascii():
        return None
    index = 0
    for char in letter:
        index = index * 26 + ord(char) - 64
    return index - 1


def parse_template(text, row_count, width):
    """Đọc JSON Claude trả, giữ phần hợp lệ.

    Nhận: chuỗi JSON theo OUTPUT_SCHEMA; số dòng của lưới; số cột lớn nhất của lưới.
    Trả: dict ``{"header_row" (từ 1), "header_rows" (1|2), "roles": {chỉ số cột: (vai trò, tên kho)}, "code_prefixes",
    "brand", "price_in_thousands", "skip_group_rows", "note"}``. Cột ngoài lưới / vai trò lạ bị bỏ; vai trò chỉ được
    một cột (trừ tồn — mỗi kho một cột) thì giữ cột đầu, cột sau thành "ignore". Lỗi: ``ValueError`` khi không phải
    JSON đúng dạng hoặc dòng tiêu đề nằm ngoài lưới.
    """
    data = json.loads(text)
    header_row = int(data["header_row"])
    if not 1 <= header_row <= row_count:
        raise ValueError("header_row ngoài lưới")
    roles, seen = {}, set()
    for item in data["columns"]:
        index = column_index(item.get("column"))
        role = item.get("role")
        if index is None or index >= width or role not in ROLE_KEYS or index in roles:
            continue
        if role != ROLE_STOCK and role != "ignore" and role in seen:
            role = "ignore"
        seen.add(role)
        roles[index] = (role, " ".join(str(item.get("warehouse") or "").split())[:64] if role == ROLE_STOCK else "")
    return {
        "header_row": header_row,
        "header_rows": 2 if data.get("header_rows") == 2 else 1,
        "roles": roles,
        "code_prefixes": " ".join(str(data.get("code_prefixes") or "").split())[:64],
        "brand": " ".join(str(data.get("brand") or "").split())[:64],
        "price_in_thousands": bool(data.get("price_in_thousands")),
        "skip_group_rows": bool(data.get("skip_group_rows")),
        "note": " ".join(str(data.get("note") or "").split())[:NOTE_MAX],
    }
