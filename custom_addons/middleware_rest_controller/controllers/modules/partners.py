# -*- coding: utf-8 -*-
from odoo import http


class Partners(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def create_partner(self, inputs):
        res = dict()
        payload = {
            "name": inputs["name"],
            "is_company": inputs["is_company"],
            "active": inputs["active"],
            "email": inputs["email"],
            "mobile": inputs["mobile"],
            "phone": inputs["phone"],
            "street": inputs["street"],
            "city": inputs["city"],
            "state_id": int(inputs["state_id"]),
            "zip": inputs["zip"],
            "country_id": int(inputs["country_id"])
        }

        if "supplier_rank" in inputs:
            payload["supplier_rank"] = int(inputs["supplier_rank"])
        if "customer_rank" in inputs:
            payload["customer_rank"] = int(inputs["customer_rank"])

        supplier_created = self.request.env["res.partner"].sudo().create(payload)
        if bool(supplier_created):
            res["partner_id"] = supplier_created[-1].id
        else:
            raise Exception("Unable to create the partner!")
        return res

    def check_if_partner_exists(self, inputs):
        res = dict()
        _conds = list()
        _conds.append(("name", "=", inputs["name"]))
        partner = self.request.env["res.partner"].sudo().search(_conds)
        if bool(partner):
            res["partner_id"] = partner[-1].id
        else:
            raise Exception("No such partner exists!")
        return res

    def get_partner_name(self, partner_id, *, email=False):
        partner_name = None
        if bool(partner_id):
            partner = self.request.env["res.partner"].sudo().search([("id", "=", int(partner_id))])
            if bool(partner):
                partner_name = partner[-1].name
                if bool(email) and bool(partner[-1].email):
                    partner_name = partner_name + " <" + partner[-1].email + ">"
        return partner_name

    def list_customers(self, inputs):
        res = list()
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit
        customers = self.request.env["res.partner"].sudo().search([("company_id", "in", [int(self.company_id), False]), ("active", "=", True), ("customer_rank", ">", 0)], limit=int(_limit), offset=int(_offset))
        if "customer_name" in inputs and bool(inputs["customer_name"]):
            cust_name = str(inputs["customer_name"])
            customers = self.request.env["res.partner"].sudo().search([("name", "ilike", cust_name.lower()), ("company_id", "in", [int(self.company_id), False]), ("active", "=", True), ("customer_rank", ">", 0)], limit=int(_limit), offset=int(_offset))
        if bool(customers):
            for each in customers:
                temp = dict()
                temp["id"] = each.id
                temp["name"] = each.name
                res.append(temp)
        return res

    def list_suppliers(self, inputs):
        res = list()
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit
        suppliers = self.request.env["res.partner"].sudo().search([("company_id", "in", [int(self.company_id), False]), ("active", "=", True), ("supplier_rank", ">", 0)], limit=int(_limit), offset=int(_offset))
        if "supplier_name" in inputs and bool(inputs["supplier_name"]):
            supp_name = str(inputs["supplier_name"])
            suppliers = self.request.env["res.partner"].sudo().search([("name", "ilike", supp_name.lower()), ("company_id", "in", [int(self.company_id), False]), ("active", "=", True), ("supplier_rank", ">", 0)], limit=int(_limit), offset=int(_offset))
        if bool(suppliers):
            for each in suppliers:
                temp = dict()
                temp["id"] = each.id
                temp["name"] = each.name
                res.append(temp)
        return res
