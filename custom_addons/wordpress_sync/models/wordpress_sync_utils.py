# -*- coding: utf-8 -*-
"""
Hàm thuần dùng chung cho việc đồng bộ web. Không đụng env, không gọi mạng.
"""


def chunked(items, size):
    """
    Chia list thành các đoạn liên tiếp dài tối đa size.

    Nhận: list, size > 0.
    Trả: list các list con; items rỗng trả [].
    """
    return [items[i:i + size] for i in range(0, len(items), size)]


def page_urls_to_purge(permalinks):
    """
    Đổi permalink sản phẩm web thành các URL trang cần xoá cache CDN.

    Biến thể có permalink dạng '<trang cha>?attribute_pa_x=y'. Khách thường xem trang cha
    không query, còn link có query thì CDN giữ thành một bản riêng — xoá cả hai.

    Nhận: iterable chuỗi permalink; phần tử rỗng/None/False bị bỏ qua.
    Trả: list URL không fragment, không trùng, giữ thứ tự gặp đầu tiên; đầu vào rỗng trả [].
    """
    urls = []
    for permalink in permalinks:
        url = (permalink or '').split('#', 1)[0]
        for candidate in (url, url.split('?', 1)[0]):
            if candidate and candidate not in urls:
                urls.append(candidate)
    return urls
