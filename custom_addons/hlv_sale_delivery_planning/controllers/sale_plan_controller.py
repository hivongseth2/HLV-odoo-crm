from odoo import http
from odoo.http import request

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan', type='http', auth='public', methods=['GET'])
    def sale_plan_redirect(self, **kwargs):
        conf_pw = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param(PW_PARAM_KEY, default="") or ""
        )
        if conf_pw and not request.session.get(SESSION_KEY_OK):
            return request.redirect('/search_stock')
        return request.redirect(
            '/web#action=hlv_sale_delivery_planning.action_delivery_planner_dashboard'
        )
