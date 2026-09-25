# -*- coding: utf-8 -*-
"""Ghép system prompt gửi cho Claude từ các phần cấu hình trên Odoo.

Util thuần: vào chuỗi / list dict, ra chuỗi. Không đụng ``self.env``.
"""
import hashlib

_BAR = "=================================================="


def _section(title, body):
    return "%s\n%s\n%s\n\n%s" % (_BAR, title, _BAR, body.strip())


def _rule_block(index, rule):
    """Một quy tắc riêng, mỗi mục một dòng; mục trống thì bỏ."""
    lines = ["%d. %s" % (index, rule.get('name') or "(không tên)")]
    for label, key in (
        ("Áp dụng khi", 'match'),
        ("Tên hàng", 'name_rule'),
        ("Mã hàng", 'code_rule'),
        ("Ghi chú", 'note'),
    ):
        value = (rule.get(key) or '').strip()
        if value:
            lines.append("   %s: %s" % (label, value.replace("\n", "\n      ")))
    example = [
        part for part in (
            'người dùng gõ "%s"' % rule['example_input'] if rule.get('example_input') else '',
            'Tên: %s' % rule['example_name'] if rule.get('example_name') else '',
            'Mã: %s' % rule['example_code'] if rule.get('example_code') else '',
        ) if part
    ]
    if example:
        lines.append("   Ví dụ đúng: %s" % " -> ".join(example))
    return "\n".join(lines)


def render_special_rules(rules):
    """Phần "QUY TẮC RIÊNG THEO DÒNG HÀNG".

    Nhận: list dict ``{'name', 'match', 'name_rule', 'code_rule', 'note',
        'example_input', 'example_name', 'example_code'}`` theo thứ tự ưu tiên.
    Trả: chuỗi section. Biên: list rỗng -> "" (không chèn section rỗng vào prompt).
    """
    if not rules:
        return ""
    intro = (
        "Các quy tắc dưới đây do quản lý cấu hình cho từng dòng hàng. Khi hàng thuộc đúng "
        "dòng, quy tắc riêng THẮNG tài liệu A ở những điểm nó nói tới; điểm nào nó không "
        "nói thì vẫn theo tài liệu A. Không tự suy rộng quy tắc riêng sang dòng hàng khác."
    )
    blocks = [_rule_block(index, rule) for index, rule in enumerate(rules, start=1)]
    return _section("QUY TẮC RIÊNG THEO DÒNG HÀNG (ƯU TIÊN HƠN TÀI LIỆU A)",
                    intro + "\n\n" + "\n\n".join(blocks))


def build_system_prompt(core, naming, category, special_rules_text=""):
    """Ghép luật lõi + tài liệu A + quy tắc riêng + tài liệu B thành một khối.

    Quy tắc riêng đứng ngay sau tài liệu A để Claude đọc ngoại lệ sát với luật chung.
    Biên: phần nào rỗng thì bỏ phần đó (kể cả tiêu đề).
    """
    parts = [(core or "").strip()]
    if (naming or "").strip():
        parts.append(_section("TÀI LIỆU A — QUY TẮC ĐẶT TÊN VÀ MÃ HÀNG HLV", naming))
    if special_rules_text:
        parts.append(special_rules_text)
    if (category or "").strip():
        parts.append(_section("TÀI LIỆU B — QUY TẮC PHÂN NHÓM HÀNG HÓA HLV", category))
    return "\n\n".join(part for part in parts if part) + "\n"


def prompt_version(text):
    """Dấu vân tay của prompt để agent biết khi nào phải tải lại.

    Trả: 16 ký tự hex đầu của sha256. Biên: None -> vân tay của chuỗi rỗng.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
