# -*- coding: utf-8 -*-
from odoo import http


class Companies(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def get_company_name(self, company_id=None):
        company_name = None
        if bool(company_id):
            company = self.request.env["res.company"].sudo().search([("id", "=", int(company_id))])
            if bool(company):
                company_name = company[-1].name
        return company_name

    def is_email_sms_enabled(self):
        email_enabled = False
        sms_enabled = False
        if bool(self.company_id):
            company = self.request.env["res.company"].sudo().search([("id", "=", int(self.company_id))])
            if bool(company):
                email_enabled = bool(company[-1].stock_move_email_validation)
                sms_enabled = bool(company[-1].stock_move_sms_validation)
        return email_enabled, sms_enabled

    def handle_email_sms_notifications(self, email_enabled, sms_enabled, *, reset=False):
        if email_enabled or sms_enabled:
            company = self.request.env["res.company"].sudo().search([("id", "=", int(self.company_id))])
            if bool(company):
                if reset:
                    if email_enabled:
                        company.sudo().write({"stock_move_email_validation": True})
                    if sms_enabled:
                        company.sudo().write({"stock_move_sms_validation": True})
                else:
                    company.sudo().write({"stock_move_email_validation": False, "stock_move_sms_validation": False})
