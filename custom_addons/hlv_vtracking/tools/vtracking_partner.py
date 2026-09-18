"""Cách gọi tên đối tác trên màn bản đồ — hàm thuần, vào gì ra nấy.

Không đụng ``self.env``, không ghi gì, không gọi mạng.
"""


def root_partner_name(partner):
    """Tên liên hệ gốc (pháp nhân) của một đối tác.

    Dùng thay ``display_name`` ở mọi chỗ hiển thị ngắn. ``display_name`` của một liên hệ
    con là "Công ty, Tên liên hệ", mà dữ liệu thật rất hay có liên hệ giao hàng đặt TRÙNG
    TÊN công ty mẹ — ra chuỗi lặp đúng một cái tên hai lần, chiếm hết dòng trong popup mà
    không thêm thông tin nào.

    :param partner: recordset ``res.partner`` MỘT bản ghi, hoặc recordset rỗng
    :returns: tên pháp nhân gốc, đã trim. Đối tác rỗng hoặc chưa có tên trả về "".
    """
    if not partner:
        return ''
    return (partner.commercial_partner_id.name or partner.name or '').strip()
