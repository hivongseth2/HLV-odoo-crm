# -*- coding: utf-8 -*-
"""Chữ báo tiến độ từng bước của trợ lý ("Đang tìm khách 'Việt Hưng'...").

Util thuần: vào tên tool + dict tham số, ra chuỗi. Không đụng ``self.env``.
"""
THINKING = "Đang suy nghĩ..."
MAX_DETAIL = 60

# Tool -> (chữ, khoá tham số đưa vào chữ). Tool không có ở đây dùng chữ chung kèm tên tool.
_LABELS = {
    'crm_tim_khach': ("Tìm khách", 'keyword'),
    'crm_xem_khach': ("Xem khách ID", 'id'),
    'crm_tim_hang': ("Tìm hàng trên MISA", 'keyword'),
    'crm_gia_cho_khach': ("Tra giá cho khách", None),
    'crm_danh_muc_co_hoi': ("Lấy danh mục giai đoạn / nguồn cơ hội", None),
    'crm_tim_co_hoi': ("Tìm cơ hội", 'keyword'),
    'crm_xem_hang_co_hoi': ("Xem hàng cơ hội ID", 'id'),
    'crm_danh_muc_bao_gia': ("Lấy danh mục tình trạng báo giá", None),
    'crm_tim_bao_gia': ("Tìm báo giá", 'keyword'),
    'crm_xem_hang_bao_gia': ("Xem hàng báo giá ID", 'id'),
    'crm_tim_don_hang': ("Tìm đơn hàng", 'keyword'),
    'crm_xem_hang_don_hang': ("Xem hàng đơn ID", 'id'),
    'crm_tao_co_hoi': ("Tạo cơ hội trên MISA", None),
    'crm_sua_co_hoi': ("Sửa cơ hội ID", 'id'),
    'crm_tao_bao_gia': ("Tạo báo giá trên MISA", None),
    'crm_tao_bao_gia_tu_co_hoi': ("Tạo báo giá từ cơ hội ID", 'opportunity_id'),
    'crm_sua_bao_gia': ("Sửa báo giá ID", 'id'),
    'search_product_misa': ("Tìm hàng trên MISA", 'name'),
    'create_product_misa': ("Tạo mã hàng", 'code'),
    'create_combo_misa': ("Tạo combo", 'code'),
    'get_combo_misa': ("Xem combo", 'code'),
    'update_combo_misa': ("Sửa combo", 'code'),
    'update_product_misa': ("Sửa hàng trên MISA", 'new_value'),
    'get_category_info': ("Xem nhóm hàng", 'category_id'),
    'search_category_misa': ("Tìm nhóm hàng", 'name'),
    'so_sanh_thong_so': ("Dựng bảng so sánh", 'tieu_de'),
    'xem_ton_kho': ("Xem tồn kho", 'code'),
    'xem_gia': ("Xem giá", 'code'),
    'xem_thanh_phan_combo': ("Xem thành phần combo", 'code'),
    'tim_hang_tuong_tu': ("Tìm hàng tương tự", 'tu_khoa'),
    'tim_ncc_dong_hang': ("Tìm NCC", 'tu_khoa'),
    'giao_viec_tra_cuu': ("Giao trợ lý phụ tra cứu", 'nhiem_vu'),
    'ghi_nho': ("Ghi nhớ", 'noi_dung'),
    'sua_ghi_nho': ("Sửa ghi nhớ #", 'id'),
    'quen': ("Quên ghi nhớ #", 'id'),
    'tim_cuoc_chat_cu': ("Tìm trong cuộc chat cũ", 'tu_khoa'),
    'doc_cuoc_chat_cu': ("Đọc cuộc chat cũ #", 'session_id'),
    'web_search': ("Tìm trên web", 'query'),
    'web_fetch': ("Đọc trang web", 'url'),
}


def server_steps(content):
    """Các bước chạy phía Anthropic trong một phản hồi (tìm / đọc web): list chữ, theo thứ tự.

    Nhận: list content block của một phản hồi. Biên: không có bước nào -> [].
    """
    return [step_label(block.get('name'), block.get('input'))
            for block in content or [] if block.get('type') == 'server_tool_use']


def step_label(name, args):
    """Chữ cho một bước gọi tool.

    Nhận: tên tool, dict tham số (có thể None / sai kiểu). Trả: vd "Tìm khách “Việt Hưng”".
    Biên: tool lạ -> "Chạy <tên>"; tham số dài -> cắt còn MAX_DETAIL ký tự + "…"; nhiều dòng hàng ->
        kèm số dòng.
    """
    label, key = _LABELS.get(name, ("Chạy %s" % name, None))
    args = args if isinstance(args, dict) else {}
    detail = args.get(key) if key else None
    if detail not in (None, ""):
        text = " ".join(str(detail).split())
        if len(text) > MAX_DETAIL:
            text = text[:MAX_DETAIL].rstrip() + "…"
        label = "%s %s" % (label, text) if label.endswith(("ID", "#")) else "%s “%s”" % (label, text)
    if isinstance(args.get('lines'), list):
        label += " (%s dòng hàng)" % len(args['lines'])
    return label
