"""Dựng action trả về cho giao diện Odoo — hàm thuần, chỉ tạo dict.

Tách ra vì cả chuyến và điểm nhận đều cần bật thông báo sau khi chạy một tác vụ hàng loạt.
Viết hai lần cùng một dict là hai chỗ để lệch nhau khi cần đổi cách hiển thị.
"""


def notification(message, kind='success', title='Đi nhận hàng'):
    """Action bật thông báo góc màn hình.

    kind: 'success' | 'warning' | 'danger' | 'info'.
    Thông báo không phải 'success' được ghim lại (sticky) vì nó thường kèm việc cần làm tiếp
    — loại tin đó trôi đi sau 3 giây là mất luôn.
    """
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': title,
            'message': message,
            'type': kind,
            'sticky': kind != 'success',
        },
    }
