# -*- coding: utf-8 -*-
"""Chèn link "Hỏi giá NCC" vào navbar của trang /sale_plan.

/sale_plan của hlv_sale_delivery_planning là chuỗi HTML trong Python; cách các module khác
(hlv_vtracking, hlv_delivery_dispatch) chèn link là kế thừa controller rồi thay chuỗi tại
comment neo ``<!-- HLV_NAV_EXT -->``. Làm y như vậy.

Nhập MỀM: không có module kia thì file này không làm gì. Không thấy neo cũng vậy — sale vẫn
vào /hoi-gia-ncc bằng URL.
"""

from odoo.http import request

from ..models.vendor_quote_access import SALE_PAGE_ROUTE as PAGE_ROUTE
from .sale_page_common import PAGE_GROUP

ANCHOR = "<!-- HLV_NAV_EXT -->"
NAV_LINK = (
    '<li class="nav-item">'
    f'<a class="nav-link" href="{PAGE_ROUTE}" title="Hỏi giá nhà cung cấp">'
    '<i class="fa fa-tags me-1"></i>Hỏi giá NCC</a></li>'
)

try:
    from odoo.addons.hlv_sale_delivery_planning.controllers import sale_plan_controller
except ImportError:  # trang /sale_plan không có trên bản cài này
    sale_plan_controller = None


if sale_plan_controller:

    class SalePlanVendorQuoteNav(sale_plan_controller.SalePlanPublicController):

        def sale_plan_page(self, **kwargs):
            response = super().sale_plan_page(**kwargs)
            user = request.env.user
            if user.share or not user.has_group(PAGE_GROUP):
                return response
            try:
                body = response.get_data(as_text=True)
            except Exception:  # noqa: BLE001 — phản hồi không phải HTML thì bỏ qua
                return response
            if ANCHOR in body:
                response.set_data(body.replace(ANCHOR, NAV_LINK + ANCHOR, 1))
            return response
