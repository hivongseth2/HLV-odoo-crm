# -*- coding: utf-8 -*-
from odoo import http
from .partners import Partners


class Users(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def get_user_name(self, user_id, *, email=False):
        user_name = None
        if bool(user_id):
            user = self.request.env["res.users"].sudo().search([("id", "=", int(user_id))])
            if bool(user):
                user_email = user[-1].login
                partner_id = user[-1].partner_id[0].id
                if bool(partner_id):
                    partners = Partners(company_id=self.company_id, user_id=self.user_id)
                    partner_name = partners.get_partner_name(partner_id)
                    if bool(email):
                        partner_name = partner_name + " <" + user_email + ">"
                    user_name = partner_name
        return user_name
