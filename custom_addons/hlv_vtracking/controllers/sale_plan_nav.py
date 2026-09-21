"""Chèn link "Kế hoạch giao" vào navbar của trang /sale_plan.

Trang /sale_plan do ``hlv_sale_delivery_planning`` dựng bằng một chuỗi HTML trong Python,
nên cách duy nhất chèn thêm mà không sửa file của module đó là bám vào comment neo
``<!-- HLV_NAV_EXT -->`` rồi thay chuỗi trong phản hồi.

Nhập MỀM: module kia không có mặt thì file này im lặng không làm gì, và ``hlv_vtracking``
vẫn cài được một mình. Không tìm thấy neo cũng vậy — sale vẫn vào /giao-hang bằng URL.
"""

import logging

from odoo.http import request

_logger = logging.getLogger(__name__)

ANCHOR = '<!-- HLV_NAV_EXT -->'
NAV_LINK = (
    '<li class="nav-item">'
    '<a class="nav-link" href="/giao-hang" title="Kế hoạch giao hàng và vị trí xe">'
    '<i class="fa fa-truck me-1"></i>Kế hoạch giao</a></li>'
)

_warned = False

try:
    from odoo.addons.hlv_sale_delivery_planning.controllers import sale_plan_controller
except ImportError:  # module trang sale không có trên bản cài này
    sale_plan_controller = None


if sale_plan_controller:

    class SalePlanNavExtension(sale_plan_controller.SalePlanPublicController):

        def sale_plan_page(self, **kwargs):
            response = super().sale_plan_page(**kwargs)
            if request.env.user.share:
                return response
            return self._inject_nav_link(response)

        @staticmethod
        def _inject_nav_link(response):
            global _warned
            try:
                body = response.get_data(as_text=True)
            except Exception:  # noqa: BLE001 — phản hồi không phải HTML thì bỏ qua
                return response
            if ANCHOR not in body:
                if not _warned:
                    _warned = True
                    _logger.info('Không thấy neo %s trong /sale_plan — bỏ qua link "Kế hoạch '
                                 'giao". Vào thẳng /giao-hang vẫn được.', ANCHOR)
                return response
            response.set_data(body.replace(ANCHOR, NAV_LINK + ANCHOR, 1))
            return response
