from odoo import http
from odoo.http import request


class HlvMobileBarcodeLiteController(http.Controller):
    @http.route("/hlv_mobile_barcode_lite/app", type="http", auth="user", website=False)
    def mobile_barcode_app(self, **kwargs):
        user = request.env.user
        values = {
            "default_db": request.db or "",
            "default_login": user.login or "",
        }
        return request.render("hlv_mobile_barcode_lite.mobile_barcode_lite_page", values)
