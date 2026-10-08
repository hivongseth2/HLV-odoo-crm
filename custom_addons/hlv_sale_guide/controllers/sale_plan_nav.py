# -*- coding: utf-8 -*-
"""Chèn link "Hướng dẫn" vào navbar của trang /sale_plan — nơi sale mở hằng ngày.

/sale_plan của hlv_sale_delivery_planning là chuỗi HTML dựng trong Python; các module khác
(hlv_vtracking, hlv_vendor_quotation) chèn link bằng cách kế thừa controller rồi thay chuỗi
tại comment neo ``<!-- HLV_NAV_EXT -->``. Làm y như vậy.

Nhập MỀM: không có module kia, hoặc không thấy neo, thì không làm gì — vẫn vào /huong-dan bằng URL.
"""

from odoo.http import request

from ..models.sale_guide import GUIDE_ROUTE

ANCHOR = "<!-- HLV_NAV_EXT -->"
NAV_LINK = (
    '<li class="nav-item">'
    f'<a class="nav-link" href="{GUIDE_ROUTE}" title="Hướng dẫn sử dụng">'
    '<i class="fa fa-book me-1"></i>Hướng dẫn</a></li>'
)

try:
    from odoo.addons.hlv_sale_delivery_planning.controllers import sale_plan_controller
except ImportError:  # trang /sale_plan không có trên bản cài này
    sale_plan_controller = None


if sale_plan_controller:

    class SalePlanGuideNav(sale_plan_controller.SalePlanPublicController):

        def sale_plan_page(self, **kwargs):
            response = super().sale_plan_page(**kwargs)
            if request.env.user.share:
                return response
            try:
                body = response.get_data(as_text=True)
            except Exception:  # noqa: BLE001 — phản hồi không phải HTML thì bỏ qua
                return response
            if ANCHOR in body:
                response.set_data(body.replace(ANCHOR, NAV_LINK + ANCHOR, 1))
            return response
