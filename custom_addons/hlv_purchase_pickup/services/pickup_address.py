"""Đọc địa chỉ từ liên hệ Odoo thành chuỗi đưa cho Google tra toạ độ.

Tách riêng vì cả điểm nhận hàng lẫn wizard xếp đơn vào chuyến đều cần: nếu mỗi chỗ tự ghép
địa chỉ theo cách riêng thì cùng một nhà cung cấp sẽ được tra ra hai toạ độ khác nhau.
"""


def partner_address_text(partner):
    """Địa chỉ một dòng của một liên hệ.

    **Có ``street`` thì chỉ lấy ``street``.** Dữ liệu của hệ này lưu TOÀN BỘ chuỗi địa chỉ
    vào ``street`` ("108 Nguyễn Công Trứ, Phường Sài Gòn, TP Hồ Chí Minh, Việt Nam"), nên
    ghép thêm city/state/country vào sau sẽ ra chuỗi lặp hai lần phường và thành phố.

    Chỉ khi ``street`` trống mới ghép từ các field còn lại — để liên hệ nào nhập theo kiểu
    tách field chuẩn của Odoo vẫn ra được địa chỉ dùng được.

    partner: recordset ``res.partner`` (1 bản ghi) hoặc bất cứ đối tượng có các thuộc tính
    tương ứng. Không có gì để lấy thì trả chuỗi rỗng.
    """
    if not partner:
        return ''
    street = (partner.street or '').strip()
    if street:
        return street
    parts = [
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
