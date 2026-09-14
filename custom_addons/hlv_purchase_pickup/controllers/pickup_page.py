"""Trang /pickup cho người đi nhận hàng.

Tách khỏi file API vì hai việc khác nhau: file này trả HTML một lần lúc mở trang, file kia
trả JSON mỗi lần bấm nút.
"""

from odoo import http
from odoo.http import request

from ..services import pickup_maps

GROUP_RUNNER = 'hlv_purchase_pickup.group_pickup_runner'

_NO_ACCESS_HTML = """<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Đi nhận hàng</title></head>
<body style="font-family:system-ui;padding:40px;max-width:640px">
<h2>Chưa được cấp quyền</h2>
<p>Tài khoản của bạn chưa có quyền <b>Đi nhận hàng — Người đi nhận</b> nên chưa mở được
danh sách chuyến. Báo quản trị cấp quyền này.</p>
</body></html>"""


class PickupPageController(http.Controller):

    @http.route('/pickup', type='http', auth='user', methods=['GET'], csrf=False)
    def pickup_page(self, run=None, **kwargs):
        # Không có group thì mọi lời gọi API sau đó đều ném AccessError và trang trông như
        # hỏng. Trả lời thẳng bằng một câu người dùng hiểu được.
        if not request.env.user.has_group(GROUP_RUNNER):
            return request.make_response(
                _NO_ACCESS_HTML,
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )
        # Key JS đi thẳng vào HTML. Đây là key ĐÃ khoá theo referrer, khác key máy chủ —
        # xem ghi chú ở services/pickup_maps.py.
        return request.render('hlv_purchase_pickup.pickup_page', {
            'maps_js_key': pickup_maps.js_key(request.env),
            # Đến từ mã QR trên tờ lịch in: /pickup?run=123. Chỉ là gợi ý mở chuyến nào,
            # KHÔNG phải cấp quyền — API vẫn kiểm chuyến đó có phải của người quét không.
            'run_id': _positive_int(run),
        })


def _positive_int(value):
    """Số nguyên dương từ tham số URL, hoặc chuỗi rỗng khi không đọc được.

    Trả chuỗi rỗng thay vì 0 để QWeb in ra thuộc tính data rỗng, JS coi như không có.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ''
    return number if number > 0 else ''
