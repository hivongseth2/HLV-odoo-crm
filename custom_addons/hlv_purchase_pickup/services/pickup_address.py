"""Đọc địa chỉ từ liên hệ Odoo thành chuỗi đưa cho Google tra toạ độ.

Tách riêng vì cả điểm nhận hàng lẫn wizard xếp đơn vào chuyến đều cần: nếu mỗi chỗ tự ghép
địa chỉ theo cách riêng thì cùng một nhà cung cấp sẽ được tra ra hai toạ độ khác nhau.
"""


def partner_address_text(partner):
    """Địa chỉ một dòng của một liên hệ.

    partner: recordset ``res.partner`` (1 bản ghi).
    Trả về chuỗi đã bỏ phần rỗng và khoảng trắng thừa; liên hệ không khai gì trả chuỗi rỗng.
    """
    if not partner:
        return ''
    parts = [
        partner.street,
        partner.street2,
        partner.city,
        partner.state_id.name if partner.state_id else '',
        partner.country_id.name if partner.country_id else '',
    ]
    return ', '.join(part.strip() for part in parts if part and part.strip())


def partner_phone(partner):
    """Số điện thoại dùng được của liên hệ: ưu tiên ``phone``, không có thì ``mobile``.

    Trả về chuỗi rỗng khi không có số nào.
    """
    if not partner:
        return ''
    return (partner.phone or partner.mobile or '').strip()
