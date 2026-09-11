"""Chèn link "Kế hoạch giao" vào navbar của trang /sale_plan.

Trang /sale_plan của hlv_sale_delivery_planning là một chuỗi HTML dài nằm trong Python.
Module này KHÔNG sửa file đó; nó kế thừa controller và chèn thêm một mục navbar vào
chuỗi trả về, bám vào comment neo ``<!-- HLV_NAV_EXT -->``.

Nếu không tìm thấy neo (module cũ đổi navbar), link đơn giản là không xuất hiện — trang
/sale_plan vẫn chạy bình thường, và sale vẫn vào được /delivery_plan bằng URL.
"""

import logging

from odoo.addons.hlv_sale_delivery_planning.controllers import sale_plan_controller
from odoo.http import request

_logger = logging.getLogger(__name__)

ANCHOR = '<!-- HLV_NAV_EXT -->'

NAV_LINK = (
    '<li class="nav-item">'
    '<a class="nav-link" href="/delivery_plan" title="Kế hoạch chuyến giao hàng">'
    '<i class="fa fa-truck me-1"></i>Kế hoạch giao</a></li>'
)

_warned = False


class SalePlanNavExtension(sale_plan_controller.SalePlanPublicController):

    def sale_plan_page(self, **kwargs):
        response = super().sale_plan_page(**kwargs)
        if not request.env.user.has_group('hlv_delivery_dispatch.group_dispatch_sale'):
            return response
        return self._inject_nav_link(response)

    def _inject_nav_link(self, response):
        global _warned
        try:
            body = response.get_data(as_text=True)
        except Exception:
            return response
        if ANCHOR not in body:
            if not _warned:
                _warned = True
                _logger.info(
                    'Không tìm thấy neo %s trong trang /sale_plan — bỏ qua link "Kế hoạch giao". '
                    'Thêm comment neo đó vào navbar của hlv_sale_delivery_planning để hiện link.',
                    ANCHOR,
                )
            return response
        response.set_data(body.replace(ANCHOR, NAV_LINK + ANCHOR, 1))
        return response
