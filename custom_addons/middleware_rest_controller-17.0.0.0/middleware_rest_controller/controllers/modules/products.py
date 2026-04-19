# -*- coding: utf-8 -*-
from odoo import http


class Products(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def get_product_name_id(self, *, p_name=None, p_code=None, p_id=None, raise_exception=True):
        _res = None
        if bool(p_name):
            pid = None
            data = self.request.env["product.product"].sudo().search(
                [("company_id", "=", int(self.company_id)), ("name", "ilike", p_name)])
            if bool(data):
                for each in data:
                    pid = each.id
            _res = pid

        if bool(p_code):
            pid = None
            data = self.request.env["product.product"].sudo().search(
                [("company_id", "=", int(self.company_id)), ("barcode", "=", p_code)])
            if bool(data):
                for each in data:
                    pid = each.id
            _res = pid

        if bool(p_id):
            p_name = None
            data = self.request.env["product.product"].sudo().search(
                [("company_id", "=", int(self.company_id)), ("id", "=", int(p_id))])
            if bool(data):
                for each in data:
                    p_name = each.name
            _res = p_name
        if raise_exception and not bool(_res):
            raise Exception("Product not found!")
        return _res

    def get_barcode(self, p_id):
        barcode = None
        p_name = None
        query = """SELECT PP.id, PP.barcode, PT.name FROM product_product AS PP INNER JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PT.company_id = %d AND PP.id = %d""" % (int(self.company_id), int(p_id))
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for each in records:
            barcode = str(each["barcode"]) if bool(each["barcode"]) else each["barcode"]
            p_name = str(each["name"]["en_US"]) 
        return barcode, p_name

    def get_active_products_list(self, inputs):
        _tuple_list = list()
        _query = """SELECT PP.id, PP.barcode, PT.name FROM product_product AS PP INNER JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PT.company_id = %d AND PP.barcode IS NOT NULL"""
        _tuple_list.append(int(self.company_id))

        if "product_name" in inputs and bool(inputs["product_name"]):
            _p_name = str(inputs["product_name"])
            _p_name = "%" + _p_name.lower() + "%"
            _query += """ AND LOWER(PT.name ->> 'en_US') LIKE '%s'"""
            _tuple_list.append(_p_name)

        if "product_code" in inputs and bool(inputs["product_code"]):
            _p_code = str(inputs["product_code"])
            _query += """ AND PP.barcode = '%s'"""
            _tuple_list.append(_p_code)

        _query += """ ORDER BY PP.id ASC LIMIT %d OFFSET %d"""
        _tuple_list.append(int(inputs["limit"]))
        _tuple_list.append(int(inputs["offset"]))

        query = _query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _records = list()
        for _row in records:
            _tmp = dict()
            _tmp["id"] = _row["id"]
            _tmp["product_code"] = _row["barcode"]
            _tmp["name"] = _row["name"]["en_US"]
            _records.append(_tmp)
        return _records

    def product_creation(self, inputs):
        res = dict()
        is_ready = True
        payload = dict()
        payload["company_id"] = int(self.company_id)
        for key, val in inputs.items():
            if key not in ["attributes", "suppliers"]:
                payload[key] = val

        if "attributes" in inputs and bool(inputs["attributes"]):
            attribute_line_ids = list()
            for each in inputs["attributes"]:
                attribute_temp = dict()
                for key, val in each.items():
                    attribute_exists = self.request.env["product.attribute"].sudo().search([("name", "ilike", key)])
                    if bool(attribute_exists):
                        attribute_id = attribute_exists[-1].id
                        attribute_temp["attribute_id"] = attribute_id
                        attribute_value_ids = list()
                        for _v in val:
                            attribute_value_exists = self.request.env["product.attribute.value"].sudo().search(
                                [("attribute_id", "=", attribute_id), ("name", "ilike", _v)])
                            if bool(attribute_value_exists):
                                attribute_value_id = attribute_value_exists[-1].id
                                attribute_value_ids.append(attribute_value_id)
                        if bool(attribute_value_ids):
                            attribute_temp["value_ids"] = [(6, False, attribute_value_ids)]
                        else:
                            raise Exception("Attribute value does not exist!")
                    else:
                        raise Exception("Attribute does not exist!")
                if bool(attribute_temp):
                    attribute_line_ids.append((0, 0, attribute_temp))
            if bool(attribute_line_ids):
                payload["attribute_line_ids"] = attribute_line_ids

        if "suppliers" in inputs and bool(inputs["suppliers"]):
            payload["seller_ids"] = [(0, False, supplier) for supplier in inputs["suppliers"]]

        if is_ready:
            product_created = self.request.env["product.template"].sudo().create(payload)
            if bool(product_created):
                product = self.request.env["product.product"].sudo().search(
                    [("product_tmpl_id", "=", int(product_created[-1].id))])
                update_product_expiry = product.sudo().write(
                    {"use_expiration_date": True if payload["tracking"] != "none" else False})
                if bool(update_product_expiry):
                    res["product_id"] = product[-1].id
                    res["product_tracking"] = product[-1].tracking
                    res["product_code"] = product[-1].barcode
            else:
                raise Exception("Unable to create the product!")
        return res

    def link_suppliers_to_product(self, inputs):
        res = dict()
        product_id = int(inputs["product_id"])
        product = self.request.env["product.product"].sudo().search([("id", "=", product_id)])
        if bool(product):
            pass
        else:
            raise Exception("Product not found!")
        return res

    def check_if_product_exists(self, inputs):
        res = dict()
        product = self.request.env["product.product"].sudo().search([("barcode", "=", inputs["product_code"])])
        if bool(product):
            product.sudo().write(
                {"tracking": inputs["product_tracking"] if inputs["product_tracking"] != "none" else "none",
                 "use_expiration_date": True if inputs["product_tracking"] != "none" else False})
            res["product_id"] = product[-1].id
            res["product_tracking"] = inputs["product_tracking"]
        else:
            raise Exception("Product does not exist!")
        return res

    def get_product_by_scan(self, inputs):
        # _res = dict()
        # products = self.request.env["product.product"].sudo().search([("barcode", "=", inputs["product_code"])])
        # if bool(products):
        #     for _p in products:
        #         _res["id"] = _p.id
        #         _res["name"] = _p.name
        # else:
        #     raise Exception("No products found!")
        # return _res
        ##
        res = list()
        products = self.request.env["product.product"].sudo().search([("barcode", "in", inputs["product_codes"])])
        if bool(products):
            for _p in products:
                _res = dict()
                _res["id"] = _p.id
                _res["barcode"] = _p.barcode
                _res["name"] = _p.name
                res.append(_res)
        else:
            raise Exception("No products found!")
        return res
