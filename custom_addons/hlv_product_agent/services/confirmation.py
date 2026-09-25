# -*- coding: utf-8 -*-
"""Chốt chặn "đề xuất trước, tạo sau" không phụ thuộc prompt.

Util thuần: vào chuỗi, ra list. Không đụng ``self.env``.

Luật: lệnh tạo / sửa chỉ được chạy khi mọi giá trị quan trọng (mã, tên, giá trị mới)
đã có NGUYÊN VĂN trong câu trả lời trước của trợ lý — tức là sale đã thấy đúng thứ đó
và nhắn lại sau khi thấy. Prompt có bị sửa sai (hay bị hiểu sai, như quyền quản lý
"im lặng làm") thì trợ lý cũng không tạo được thứ chưa từng đưa cho sale xem.
"""
import re

_SPACES = re.compile(r"\s+")


def _normalize(text):
    return _SPACES.sub(" ", text or "").strip()


def missing_from_proposal(proposal_text, values):
    """Các giá trị KHÔNG có nguyên văn trong đề xuất trước.

    Nhận: nội dung câu trả lời trước của trợ lý (có thể None), list giá trị cần có.
    Trả: list giá trị bị thiếu, theo thứ tự truyền vào. So nguyên văn, phân biệt hoa
        thường (mã hàng khác hoa thường là mã khác), chỉ gộp khoảng trắng / xuống dòng.
    Biên: giá trị rỗng / None bị bỏ qua (không bắt buộc); không có đề xuất -> mọi giá
        trị khác rỗng đều thiếu.
    """
    proposal = _normalize(proposal_text)
    return [
        value for value in values
        if _normalize(value) and _normalize(value) not in proposal
    ]
