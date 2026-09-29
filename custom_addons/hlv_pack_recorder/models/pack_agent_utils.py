# -*- coding: utf-8 -*-
"""Hàm thuần dùng chung cho phần agent ghi hình.

Không đụng self.env, không đọc file, không gọi mạng — nhận gì trả nấy, để chỗ
nào cần cũng dùng được và test được mà không cần dựng Odoo.
"""
import re

# Khớp đúng dòng khai ở đầu file agent: AGENT_VERSION = '2.1.0'
_VERSION_RE = re.compile(r"""^AGENT_VERSION\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)


def parse_agent_version(source):
    """Lấy số phiên bản khai trong mã nguồn agent.

    source: nội dung file hlv_pack_agent.py (str), hoặc None.
    Trả: chuỗi phiên bản, ví dụ '2.1.0'.
        Biên: không tìm thấy dòng khai, hoặc source rỗng/None -> trả ''.
    """
    match = _VERSION_RE.search(source or '')
    return match.group(1) if match else ''


def needs_agent_update(reported, latest):
    """Bàn này có đang chạy bản agent cũ hơn bản Odoo đang phục vụ không.

    reported: phiên bản agent tự báo lên, '' nếu chưa bao giờ báo.
    latest: phiên bản Odoo đang phục vụ, '' nếu không đọc được file.

    Trả: True khi hai bên khác nhau và cả hai đều biết rõ.
        Biên: thiếu một trong hai -> False. CỐ Ý không đoán: không đọc được
        file agent mà vẫn bảo "cần cập nhật" thì mọi bàn sẽ tải về một thứ
        Odoo không chắc là gì.
    """
    if not reported or not latest:
        return False
    return reported.strip() != latest.strip()
