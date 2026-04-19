# -*- coding: utf-8 -*-
import json
import datetime
from odoo import http
from .locations import Locations
from .products import Products
from .inbounds import Inbounds
from .outbounds import Outbounds


class Inventories(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        self.is_inventory_audit = False
        self.is_no_tracking = False
        self.first_hit = True
        pass

    def get_allocation(self, product_id, location_id=None, lot_id=None):
        allocated_qty = 0
        if bool(lot_id):
            if self.get_tracking(product_id, lot_id) == "serial":
                return float(allocated_qty)

        _tuple_list = list()
        query = """SELECT * FROM stock_move_line WHERE reference LIKE '%s' AND company_id = %d AND product_id = %d"""
        _tuple_list.append("%/OUT/%")
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_id):
            query += """ AND location_id = %d"""
            _tuple_list.append(int(location_id))
        if bool(lot_id):
            query += """ AND lot_id = %d"""
            _tuple_list.append(int(lot_id))
        else:
            if self.is_inventory_audit or self.is_no_tracking:
                query += """ AND lot_id IS NULL"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        stock_move_ids = list()
        for each in records:
            stock_move_ids.append(str(each["move_id"]))
        if bool(stock_move_ids):
            move_ids = "'" + "', '".join(stock_move_ids) + "'"
            query = """SELECT * FROM stock_move WHERE state = 'done' AND id IN ({}) AND sale_line_id IS NOT NULL""".format(move_ids)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            sale_line_ids = list()
            for each in records:
                sale_line_ids.append(str(each["sale_line_id"]))
            if bool(sale_line_ids):
                so_line_ids = "'" + "', '".join(sale_line_ids) + "'"
                state = "'" + "', '".join(["cancel"]) + "'"
                query = """SELECT SOL.* FROM sale_order_line AS SOL INNER JOIN sale_order AS SO ON SOL.order_id = SO.id WHERE SOL.id IN (%s) AND SO.state NOT IN (%s)""" % (so_line_ids, state)
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    allocated_qty += float(each["product_uom_qty"]) - float(each["qty_delivered"])
        return float(allocated_qty)

    def get_quarantine(self, product_id, location_id=None, lot_id=None):
        quarantine = 0
        _tuple_list = list()
        query = """SELECT * FROM stock_location WHERE company_id = %d AND scrap_location = 't'"""
        _tuple_list.append(int(self.company_id))
        if bool(location_id):
            query += """ AND id = %d"""
            _tuple_list.append(int(location_id))

        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        if bool(records):
            quarantine_location_ids = list()
            for each in records:
                quarantine_location_ids.append(str(each["id"]))
            if bool(quarantine_location_ids):
                _ql_ids = "'" + "', '".join(quarantine_location_ids) + "'"
                query = """SELECT * FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id IS NULL GROUP BY id, lot_id, product_id, location_id""" % (int(self.company_id), int(product_id), _ql_ids)
                if bool(lot_id):
                    query = """SELECT * FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id = %d GROUP BY id, lot_id, product_id, location_id""" % (int(self.company_id), int(product_id), _ql_ids, int(lot_id))
                self.request.env.cr.execute(query)
                _records = self.request.env.cr.dictfetchall()
                for each in _records:
                    quarantine += float(each["quantity"])
        return float(quarantine)

    def get_lot_n_expiry(self, product_id, *, lot_id=None, lot_name=None):
        if bool(lot_id):
            lot_name = None
            expiry_date = None
            if lot_id != "x":
                query = """SELECT name, expiration_date FROM stock_lot WHERE id = %d AND company_id = %d AND product_id = %d""" % (int(lot_id), int(self.company_id), int(product_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _row in records:
                    lot_name = _row["name"]
                    expiry_date = _row["expiration_date"].strftime('%Y-%m-%d') if bool(
                        _row["expiration_date"]) and isinstance(_row["expiration_date"], datetime.datetime) else ""
            return lot_name, expiry_date
        if bool(lot_name):
            lot_id = None
            query = """SELECT id FROM stock_lot WHERE company_id = %d AND product_id = %d AND name = '%s'""" % (int(self.company_id), int(product_id), lot_name)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            for _row in records:
                lot_id = _row["id"]
            return lot_id

    def get_to_receive(self, location_ids, product_id, lot_id=None):
        _qty_ordered = 0
        query = """SELECT COALESCE(SUM(product_qty), 0) AS qty_ordered FROM purchase_order_line WHERE company_id = %d AND product_id = %d""" % (int(self.company_id), int(product_id))
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for each in records:
            if bool(each["qty_ordered"]):
                _qty_ordered += float(each["qty_ordered"])

        _qty_received = 0
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS qty_received FROM stock_move_line WHERE reference LIKE '%s' AND state = 'done' AND company_id = %d AND product_id = %d"""
        _tuple_list.append("%/IN/%")
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_ids):
            _l_ids = "'" + "', '".join(location_ids) + "'"
            query += """ AND location_dest_id IN (%s)"""
            _tuple_list.append(_l_ids)
        if bool(lot_id):
            query += """ AND lot_id = %d"""
            _tuple_list.append(int(lot_id))
        else:
            if self.is_inventory_audit or self.is_no_tracking:
                query += """ AND lot_id IS NULL"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for each in records:
            if bool(each["qty_received"]):
                _qty_received += float(each["qty_received"])
        return float(_qty_ordered - _qty_received)

    def get_stock(self, location_ids, product_id, lot_id=None):
        in_stock = 0
        available = 0
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity FROM stock_quant WHERE company_id = %d AND product_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_ids):
            query += """ AND location_id IN (%s)"""
            _loc_ids = "'" + "', '".join(location_ids) + "'"
            _tuple_list.append(_loc_ids)
        if bool(lot_id):
            query += """ AND lot_id = %d GROUP BY product_id, lot_id"""
            _tuple_list.append(int(lot_id))
        else:
            if self.is_inventory_audit or self.is_no_tracking:
                query += """ AND lot_id IS NULL"""
            query += """ GROUP BY product_id"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        if bool(records):
            for each in records:
                allocated = self.get_allocation(product_id, None, lot_id)
                quarantine = self.get_quarantine(product_id, None, lot_id)
                in_stock = float(each["quantity"])
                available = float(in_stock - float(each["reserved_quantity"]))
                to_receive = self.get_to_receive(location_ids, product_id, lot_id)
                return float(in_stock), float(available), float(allocated), float(quarantine), to_receive
        else:
            allocated = self.get_allocation(product_id, None, lot_id)
            quarantine = self.get_quarantine(product_id, None, lot_id)
            to_receive = self.get_to_receive(location_ids, product_id, lot_id)
            return float(in_stock), float(available), float(allocated), float(quarantine), float(to_receive)

    def get_stock_x(self, location_ids, p_name):
        _not_exist = 1
        in_stock = 0
        available = 0
        allocated = 0
        quarantine = 0
        to_be_received = 0

        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_name=p_name)
        if bool(product_id):
            _not_exist = 0
            allocated = self.get_allocation(product_id)
            quarantine = self.get_quarantine(product_id)
            to_be_received = self.get_to_receive(location_ids, product_id)
        return bool(_not_exist), float(in_stock), float(available), float(allocated), float(quarantine), float(to_be_received)

    def get_item_wise_inventory(self, inputs):
        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_codes = list()
        product_names = list()
        product_ids = list()
        if "products" in inputs and bool(inputs["products"]):
            _products = json.loads(inputs["products"])
            for each in _products:
                for key, val in each.items():
                    product_codes.append(key)
                    product_names.append(val)
            data = self.request.env["product.product"].sudo().search([("name", "in", product_names)])
            for each in data:
                if each.id not in product_ids:
                    product_ids.append(str(each.id))

        location_ids = list()
        if "location_name" in inputs and bool(inputs["location_name"]):
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            location_ids = locations.get_location_ids_including_all_child_locations(
                location_name=inputs["location_name"])

        _items = list()
        if bool(product_ids):
            query = """SELECT PP.id AS product_id FROM product_product AS PP WHERE PP.id IN ({})""".format(
                "'" + "', '".join(product_ids) + "'")
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if bool(records):
                _tmp_items = list()
                for each in records:
                    _tmp = dict()
                    _tmp["erp"] = "Odoo"
                    _tmp["not_exist"] = False
                    (_tmp["product_code"], _tmp["product_name"]) = products.get_barcode(each["product_id"])
                    (_tmp["in_stock"], _tmp["available"], _tmp["allocated"], _tmp["quarantined"], _tmp["to_receive"]) = self.get_stock(location_ids, each["product_id"])
                    _tmp.pop("quarantined", None)
                    _tmp_items.append(_tmp)
                if len(_tmp_items) > 0:
                    i = -1
                    for p_name in product_names:
                        i += 1
                        is_not_found = True
                        for _item in _tmp_items:
                            if p_name == _item["product_name"]:
                                is_not_found = False
                        if is_not_found:
                            _tmp = dict()
                            _tmp["erp"] = "Odoo"
                            _tmp["product_code"] = None if product_codes[i] == "None" else product_codes[i]
                            _tmp["product_name"] = p_name
                            (_tmp["not_exist"], _tmp["in_stock"], _tmp["available"], _tmp["allocated"],
                             _tmp["quarantined"], _tmp["to_receive"]) = self.get_stock_x(location_ids, p_name)
                            _tmp.pop("quarantined", None)
                            _items.append(_tmp)
                        else:
                            for _item in _tmp_items:
                                if p_name == _item["product_name"]:
                                    _items.append(_item)
        return _items

    def get_lot_stock(self, location_ids, product_id, lot_id):
        in_stock = 0
        available = 0
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity FROM stock_quant WHERE lot_id IS NOT NULL AND company_id = %d AND product_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_ids):
            query += """ AND location_id IN (%s)"""
            _loc_ids = "'" + "', '".join(location_ids) + "'"
            _tuple_list.append(_loc_ids)
        if bool(lot_id):
            query += """ AND lot_id = %d GROUP BY product_id, lot_id"""
            _tuple_list.append(int(lot_id))
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        if bool(records):
            for each in records:
                allocated = self.get_allocation(product_id, None, lot_id)
                quarantine = self.get_quarantine(product_id, None, lot_id)
                in_stock = float(each["quantity"])
                available = float(in_stock - float(each["reserved_quantity"]))
                to_receive = self.get_to_receive(location_ids, product_id, lot_id)
                return float(in_stock), float(available), float(allocated), float(quarantine), float(to_receive)
        else:
            allocated = self.get_allocation(product_id, None, lot_id)
            quarantine = self.get_quarantine(product_id, None, lot_id)
            to_receive = self.get_to_receive(location_ids, product_id, lot_id)
            return float(in_stock), float(available), float(allocated), float(quarantine), float(to_receive)

    def get_item_inventory_by_lots(self, inputs):
        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_code=inputs["product_code"])
        product_name = products.get_product_name_id(p_id=product_id)

        limit = inputs["limit"]
        offset = inputs["offset"]

        location_ids = list()
        if "location_name" in inputs:
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            location_ids = locations.get_location_ids_including_all_child_locations(
                location_name=inputs["location_name"])
        lot_id = None
        if "lot_name" in inputs and bool(inputs["lot_name"]):
            lot_id = self.get_lot_n_expiry(product_id, lot_name=inputs["lot_name"])
            if not bool(lot_id):
                raise Exception("The lot (" + inputs["lot_name"] + ") does not exist or it got expired in Odoo!")

        _tuple_list = list()
        query = """SELECT PP.id AS product_id, SL.id AS lot_id FROM product_product AS PP LEFT JOIN stock_lot AS SL ON PP.id = SL.product_id WHERE PP.id = %d AND SL.company_id = %d AND SL.id IN (SELECT lot_id FROM stock_move_line WHERE quantity > 0 AND company_id = %d AND product_id = %d AND lot_id IS NOT NULL GROUP BY id HAVING MAX(quantity) > 1)"""
        _tuple_list.append(int(product_id))
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(lot_id):
            query += """ AND SL.id = %d"""
            _tuple_list.append(int(lot_id))
        query += """ GROUP BY PP.id, SL.id ORDER BY PP.id DESC LIMIT %d OFFSET %d"""
        _tuple_list.append(int(limit))
        _tuple_list.append(int(offset))

        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _records = list()
        for each in records:
            _tmp = dict()
            _tmp["erp"] = "Odoo"
            _tmp["product_name"] = product_name
            (_tmp["lot_name"], _tmp["expiry_date"]) = self.get_lot_n_expiry(each["product_id"], lot_id=each["lot_id"])
            (_tmp["in_stock"], _tmp["available"], _tmp["allocated"], _tmp["quarantined"],
             _tmp["to_receive"]) = self.get_lot_stock(location_ids, each["product_id"], each["lot_id"])
            _tmp.pop("quarantined", None)
            _records.append(_tmp)
        return _records

    def get_location_stock(self, location_ids, product_id, limit, offset):
        products = Products(company_id=self.company_id, user_id=self.user_id)
        locations = Locations(company_id=self.company_id, user_id=self.user_id)

        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity, product_id, location_id FROM stock_quant WHERE company_id = %d AND product_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_ids):
            query += """ AND location_id IN (%s)"""
            _loc_ids = "'" + "', '".join(location_ids) + "'"
            _tuple_list.append(_loc_ids)
        query += """ GROUP BY product_id, location_id LIMIT %d OFFSET %d"""
        _tuple_list.append(int(limit))
        _tuple_list.append(int(offset))
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _records = list()
        if bool(records):
            for each in records:
                allocated = self.get_allocation(each["product_id"], each["location_id"])
                quarantine = self.get_quarantine(each["product_id"], each["location_id"])
                in_stock = float(each["quantity"])
                available = float(in_stock - float(each["reserved_quantity"]))
                to_receive = self.get_to_receive(location_ids, each["product_id"])
                _tmp = dict()
                _tmp["erp"] = "Odoo"
                _tmp["product_name"] = products.get_product_name_id(p_id=each["product_id"])
                _tmp["storage_location"] = locations.get_storage_location(each["location_id"])
                _tmp["in_stock"] = int(in_stock)
                _tmp["available"] = int(available)
                _tmp["allocated"] = int(allocated)
                # _tmp["quarantined"] = int(quarantine)
                _tmp["to_receive"] = int(to_receive)
                _tmp.pop("quarantined", None)
                _records.append(_tmp)
        return _records

    def get_item_inventory_by_locations(self, inputs):
        limit = inputs["limit"]
        offset = inputs["offset"]

        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_code=inputs["product_code"])

        location_ids = list()
        if "location_name" in inputs:
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            location_ids = locations.get_location_ids_including_all_child_locations(
                location_name=inputs["location_name"])
        return self.get_location_stock(location_ids, product_id, limit, offset)

    def get_tracking(self, product_id, lot_id):
        _tracking = None
        if bool(lot_id):
            query = """SELECT * FROM stock_move_line WHERE quantity > 0 AND company_id = %d AND product_id = %d AND lot_id = %d GROUP BY id HAVING MAX(quantity) > 1 LIMIT 1""" % (int(self.company_id), int(product_id), int(lot_id))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                _tracking = "lot"
            else:
                _tracking = "serial"
        return _tracking

    def filter_open_picking(self, data):
        revised_quantity = 0
        if bool(data):
            revised_quantity = float(data["quantity"])
            query = """SELECT * FROM middleware_open_picking WHERE status = 'in_progress'"""
            if "so_id" in data and bool(data["so_id"]):
                query = """SELECT * FROM middleware_open_picking WHERE status = 'in_progress' AND so_id = %d""" % (
                    int(data["so_id"]))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            for _row in records:
                _data = _row["lots_serials_nots_quantities"]
                try:
                    _data = json.loads(_row["lots_serials_nots_quantities"])
                except Exception as e:
                    print(e.__str__())
                    pass
                if isinstance(_data, dict) and bool(_data):
                    if data["lot_name"] in _data["lots"]:
                        _index = _data["lots"].index(data["lot_name"])
                        if _index > -1:
                            if _data["product_codes"][_index] == data["product_code"]:
                                revised_quantity -= float(_data["reserved_quantities"][_index])
        return float(revised_quantity)

    def list_suggestive_lots(self, inputs):
        _res = list()
        product = http.request.env["product.product"].sudo().search([("barcode", "=", inputs["product_code"])])
        if bool(product):
            location_ids = list()
            if "source" in inputs and bool(inputs["source"]):
                location_ids.append(str(inputs["source"]))
            else:
                locations = Locations(company_id=self.company_id, user_id=self.user_id)
                location_ids = locations.get_location_ids_including_all_child_locations(location_name=inputs["location_name"], only_warehouse=True)
            if bool(location_ids):
                _location_ids = "'" + "', '".join(location_ids) + "'"
                query = """SELECT * FROM stock_quant WHERE quantity > 0 AND location_id IN (%s) AND product_id = %d AND lot_id IS NOT NULL GROUP BY id, lot_id ORDER BY id DESC""" % (_location_ids, int(product[-1].id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _row in records:
                    if self.get_tracking(product[-1].id, _row["lot_id"]) == "lot":
                        (lot_name, expiry_date) = self.get_lot_n_expiry(product[-1].id, lot_id=_row["lot_id"])
                        if bool(lot_name) and bool(expiry_date):
                            if datetime.datetime.strptime(str(expiry_date), "%Y-%m-%d") > datetime.datetime.now():
                                available_quantity = _row["quantity"]
                                if "calculate_open_picking" in inputs and bool(inputs["calculate_open_picking"]):
                                    _params = {
                                        "product_code": inputs["product_code"],
                                        "lot_name": lot_name,
                                        "serial_name": "",
                                        "quantity": available_quantity
                                    }
                                    if "so_id" in inputs and bool(inputs["so_id"]):
                                        _params["so_id"] = int(inputs["so_id"])

                                    revised_qty = self.filter_open_picking(_params)
                                    if revised_qty > 0:
                                        available_quantity = revised_qty
                                if available_quantity > 0:
                                    _tmp = dict()
                                    _tmp["product_code"] = inputs["product_code"]
                                    _tmp["lot_name"] = lot_name
                                    _tmp["expiry_date"] = expiry_date
                                    _tmp["available_quantity"] = available_quantity
                                    _res.append(_tmp)
        return _res

    def get_lot_name(self, _p_id, _id):
        _lot_name = None
        _lot = self.request.env["stock.lot"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(_p_id))])
        if bool(_lot):
            _lot_name = _lot[-1].name
        return _lot_name

    def list_all_lots(self, inputs):
        _res = list()
        products = Products(company_id=self.company_id, user_id=self.user_id)
        _product_codes = "'" + "', '".join(inputs["product_codes"]) + "'"

        locations = Locations(company_id=self.company_id, user_id=self.user_id)
        location_ids = locations.get_location_ids_including_all_child_locations(location_name=inputs["location_name"])
        _location_ids = "'" + "', '".join(location_ids) + "'"

        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit

        _tuple_list = list()
        query = """SELECT SQ.product_id, SQ.lot_id, PP.barcode, COALESCE(SUM(SQ.quantity), 0) AS quantity FROM stock_quant AS SQ LEFT JOIN product_product AS PP ON SQ.product_id = PP.id WHERE SQ.quantity > 0 AND SQ.company_id = %d AND SQ.location_id IN (%s) AND PP.barcode IN (%s) AND SQ.lot_id IS NOT NULL GROUP BY SQ.product_id, SQ.lot_id, PP.barcode HAVING MAX(SQ.quantity) > 1 LIMIT %d OFFSET %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(_location_ids)
        _tuple_list.append(_product_codes)
        _tuple_list.append(int(_limit))
        _tuple_list.append(int(_offset))
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for _row in records:
            _tmp = dict()
            _tmp["product_code"] = _row["barcode"]
            _tmp["product_name"] = products.get_product_name_id(p_id=_row["product_id"])
            _tmp["lot_name"] = self.get_lot_name(_row["product_id"], _row["lot_id"])
            _tmp["quantity"] = _row["quantity"]
            _res.append(_tmp)
        return _res

    def handle_inventory_audit_session(self, inputs):
        _session = inputs["session"]
        if bool(_session):
            _model_names = ["Purchase Order", "Sales Order", "Product Moves (Stock Move Line)", "Quants"]
            _model_names_str = "'" + "', '".join(_model_names) + "'"
            _models = list()
            query = """SELECT id, name ->> 'en_US' AS name FROM ir_model WHERE name ->> 'en_US' IN ({})""".format(_model_names_str)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            for rec in records:
                _models.append(rec)
            if bool(_models):
                if _session == "start":
                    _exception_found = False
                    for _m in _models:
                        if not bool(_exception_found):
                            rule_exists = self.request.env["ir.rule"].sudo().search(
                                [("name", "like", "Middleware Inventory Audit"), ("model_id", "=", int(_m["id"]))])
                            if bool(rule_exists):
                                rule_exists.write(
                                    {"groups": [(6, False, [])], "domain_force": "[(0, '=', 1)]", "active": True,
                                     "perm_read": False, "perm_create": True, "perm_write": True, "perm_unlink": True})
                            else:
                                _rule_name = None
                                if _m["name"] == "Purchase Order":
                                    _rule_name = "Middleware Inventory Audit - Purchase Order"
                                elif _m["name"] == "Sales Order":
                                    _rule_name = "Middleware Inventory Audit - Sales Order"
                                elif _m["name"] == "Product Moves (Stock Move Line)":
                                    _rule_name = "Middleware Inventory Audit - Product Moves"
                                elif _m["name"] == "Quants":
                                    _rule_name = "Middleware Inventory Audit - Quants"
                                if not bool(_rule_name):
                                    _exception_found = True
                                else:
                                    payload = dict()
                                    payload["name"] = _rule_name
                                    payload["model_id"] = int(_m["id"])
                                    payload["groups"] = [(6, False, [])]
                                    payload["domain_force"] = "[(0, '=', 1)]"
                                    payload["perm_read"] = False
                                    payload["perm_create"] = True
                                    payload["perm_write"] = True
                                    payload["perm_unlink"] = True
                                    payload["active"] = True
                                    rule_created = self.request.env["ir.rule"].sudo().create(payload)
                                    if not bool(rule_created):
                                        _exception_found = True
                    if _exception_found:
                        for _model in _models:
                            rule_exists = self.request.env["ir.rule"].sudo().search(
                                [("name", "like", "Middleware Inventory Audit"), ("model_id", "=", int(_model["id"]))])
                            if bool(rule_exists):
                                rule_exists.unlink()
                        raise Exception("Unable to start the inventory audit session!")
                elif _session == "end":
                    c = 0
                    for _model in _models:
                        rule_exists = self.request.env["ir.rule"].sudo().search(
                            [("name", "like", "Middleware Inventory Audit"), ("model_id", "=", int(_model["id"]))])
                        if bool(rule_exists):
                            rule_exists.unlink()
                            c += 1
                    if c > 0 and c != len(_models):
                        # raise Exception("Unable to end the inventory audit session!")
                        pass

    @staticmethod
    def get_physical_qty(inputs, barcode, lot=None):
        physical_qty = 0
        for _item in inputs["items"]:
            if str(_item["product_code"]) == str(barcode):
                if bool(lot):
                    for _itm_lot in _item["lots"]:
                        if str(_itm_lot["lot_number"]) == str(lot):
                            physical_qty = _itm_lot["quantity"]
                else:
                    for _itm_lot in _item["lots"]:
                        if not bool(_itm_lot["lot_number"]) and not bool(_itm_lot["p_serials"]):
                            physical_qty = _itm_lot["quantity"]
        return float(physical_qty)

    def get_item_inventory_count(self, inputs, internal=False):
        self.is_inventory_audit = not bool(internal)
        self.is_no_tracking = False

        limit = inputs["limit"]
        offset = inputs["offset"]
        products = Products(company_id=self.company_id, user_id=self.user_id)
        _all_pids = list()

        tracking_product_ids = None
        tracking_product_ids_list = list()
        if "tracking_product_codes" in inputs and isinstance(inputs["tracking_product_codes"], list):
            for _p_code in inputs["tracking_product_codes"]:
                _p_id = products.get_product_name_id(p_code=_p_code, raise_exception=False)
                if bool(_p_id):
                    if str(_p_id) not in _all_pids:
                        _all_pids.append(str(_p_id))
                    tracking_product_ids_list.append(str(_p_id))
            if bool(tracking_product_ids_list) and isinstance(tracking_product_ids_list, list):
                tracking_product_ids = "'" + "', '".join(tracking_product_ids_list) + "'"

        no_tracking_product_ids = None
        no_tracking_product_ids_list = list()
        if "no_tracking_product_codes" in inputs and isinstance(inputs["no_tracking_product_codes"], list):
            for _p_code in inputs["no_tracking_product_codes"]:
                _p_id = products.get_product_name_id(p_code=_p_code, raise_exception=False)
                if bool(_p_id):
                    if str(_p_id) not in _all_pids:
                        _all_pids.append(str(_p_id))
                    no_tracking_product_ids_list.append(str(_p_id))
            if bool(no_tracking_product_ids_list) and isinstance(no_tracking_product_ids_list, list):
                no_tracking_product_ids = "'" + "', '".join(no_tracking_product_ids_list) + "'"

        location_ids = list()
        _loc_ids = None
        if "location_name" in inputs:
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            location_ids = locations.get_location_ids_including_all_child_locations(
                location_name=inputs["location_name"])
            if bool(location_ids) and isinstance(location_ids, list):
                _loc_ids = "'" + "', '".join(location_ids) + "'"

        lot_ids = None
        if "lots" in inputs and isinstance(inputs["lots"], list):
            lot_names = "'" + "', '".join(inputs["lots"]) + "'"
            query = """SELECT id FROM stock_lot WHERE company_id = %d AND name IN (%s) GROUP BY id, product_id""" % (int(self.company_id), lot_names)
            if bool(_all_pids):
                product_ids = "'" + "', '".join(_all_pids) + "'"
                query = """SELECT id FROM stock_lot WHERE company_id = %d AND product_id IN(%s) AND name IN (%s) GROUP BY id, product_id""" % (int(self.company_id), product_ids, lot_names)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            _tmp_lot_ids = list()
            for _row in records:
                _tmp_lot_ids.append(str(_row["id"]))
            if bool(_tmp_lot_ids):
                lot_ids = "'" + "', '".join(_tmp_lot_ids) + "'"

        _records = list()
        if bool(no_tracking_product_ids) or (bool(lot_ids) and bool(tracking_product_ids)):
            _tuple_list = list()
            query = """SELECT SML.product_id, SML.lot_id FROM stock_move_line AS SML LEFT JOIN stock_lot AS SL ON SML.lot_id = SL.id WHERE SML.company_id = %d"""
            _tuple_list.append(int(self.company_id))

            if bool(_loc_ids):
                query += """ AND SML.location_dest_id IN (%s)"""
                _tuple_list.append(_loc_ids)

            if bool(lot_ids):
                if bool(no_tracking_product_ids):
                    self.is_no_tracking = True
                    query += """ AND SML.product_id IN (%s) OR SML.lot_id IN (%s)"""
                    tracking_no_tracking_pids = "'" + "', '".join(list(set(tracking_product_ids_list + no_tracking_product_ids_list))) + "'"
                    _tuple_list.append(tracking_no_tracking_pids)
                    _tuple_list.append(lot_ids)
                else:
                    if bool(tracking_product_ids):
                        query += """ AND SML.product_id IN (%s) AND SML.lot_id IN (%s)"""
                        _tuple_list.append(tracking_product_ids)
                        _tuple_list.append(lot_ids)
            else:
                if bool(no_tracking_product_ids):
                    self.is_no_tracking = True
                    query += """ AND SML.product_id IN (%s) AND SML.lot_id IS NULL"""
                    _tuple_list.append(no_tracking_product_ids)
            query += """ GROUP BY SML.product_id, SML.lot_id ORDER BY SML.product_id ASC OFFSET %d"""
            _tuple_list.append(int(offset))
            if int(limit) > 0:
                query += """ LIMIT %d"""
                _tuple_list.append(int(limit))

            query = query % tuple(_tuple_list)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if bool(records):
                for each in records:
                    _tmp = dict()
                    _tmp["erp"] = "Odoo"
                    _tmp["warehouse"] = inputs["location_name"]
                    (_tmp["barcode"], _tmp["product_name"]) = products.get_barcode(each["product_id"])
                    _tracking = self.get_tracking(each["product_id"], each["lot_id"])
                    if _tracking == "lot":
                        (_tmp["lot"], _tmp["expiry_date"]) = self.get_lot_n_expiry(each["product_id"],
                                                                                   lot_id="x" if not bool(
                                                                                       each["lot_id"]) else each["lot_id"])
                        _tmp["serial"] = None
                        if not bool(internal):
                            _tmp["physical_qty"] = self.get_physical_qty(inputs, _tmp["barcode"], _tmp["lot"])
                    elif _tracking == "serial":
                        (_tmp["serial"], _tmp["expiry_date"]) = self.get_lot_n_expiry(each["product_id"],
                                                                                      lot_id="x" if not bool(
                                                                                          each["lot_id"]) else each[
                                                                                          "lot_id"])
                        _tmp["lot"] = None
                        if not bool(internal):
                            _tmp["physical_qty"] = 1
                    else:
                        _tmp["lot"] = None
                        _tmp["serial"] = None
                        _tmp["expiry_date"] = None
                        if not bool(internal):
                            _tmp["physical_qty"] = self.get_physical_qty(inputs, _tmp["barcode"])
                    (_tmp["in_stock"], _tmp["available"], _tmp["allocated"], _tmp["quarantined"],
                     _tmp["to_receive"]) = self.get_stock(location_ids, each["product_id"], each["lot_id"])
                    # if not bool(internal):
                    #     _tmp.pop("to_receive", None)
                    _tmp.pop("quarantined", None)
                    _tmp.pop("to_receive", None)
                    _records.append(_tmp)
        return _records

    def get_location_wise_item_stock(self, warehouse, location_name, location_ids, product_id, lot_id):
        in_stock = 0
        available = 0
        products = Products(company_id=self.company_id, user_id=self.user_id)
        locations = Locations(company_id=self.company_id, user_id=self.user_id)

        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity, product_id, location_id FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s)"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        _loc_ids = "'" + "', '".join(location_ids) + "'"
        _tuple_list.append(_loc_ids)

        if self.is_no_tracking:
            query += """ AND lot_id IS NULL"""
        else:
            query += """ AND lot_id = %d"""
            _tuple_list.append(int(lot_id))

        query += """ GROUP BY product_id, location_id"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _records = list()
        if bool(records):
            for each in records:
                allocated = self.get_allocation(each["product_id"], each["location_id"], lot_id)
                quarantine = self.get_quarantine(each["product_id"], each["location_id"], lot_id)
                in_stock = float(each["quantity"])
                available = float(in_stock - float(each["reserved_quantity"]))
                to_receive = self.get_to_receive(location_ids, each["product_id"], lot_id)
                _tmp = dict()
                _tmp["erp"] = "Odoo"
                _tmp["warehouse"] = warehouse
                _tmp["storage_location"] = locations.get_storage_location(each["location_id"])
                (_tmp["barcode"], _tmp["product_name"]) = products.get_barcode(product_id)
                _tracking = self.get_tracking(each["product_id"], lot_id)
                if _tracking == "lot":
                    (_tmp["lot"], _tmp["expiry_date"]) = self.get_lot_n_expiry(each["product_id"],
                                                                               lot_id="x" if not bool(
                                                                                   lot_id) else lot_id)
                    _tmp["serial"] = None
                elif _tracking == "serial":
                    (_tmp["serial"], _tmp["expiry_date"]) = self.get_lot_n_expiry(each["product_id"],
                                                                                  lot_id="x" if not bool(
                                                                                      lot_id) else lot_id)
                    _tmp["lot"] = None
                else:
                    _tmp["lot"] = None
                    _tmp["serial"] = None
                    _tmp["expiry_date"] = None
                _tmp["in_stock"] = int(in_stock)
                _tmp["available"] = int(available)
                _tmp["allocated"] = int(allocated)
                _tmp["quarantined"] = int(quarantine)
                _tmp["to_receive"] = int(to_receive)
                _tmp.pop("quarantined", None)
                _records.append(_tmp)
        else:
            allocated = self.get_allocation(product_id, None, lot_id)
            quarantine = self.get_quarantine(product_id, None, lot_id)
            to_receive = self.get_to_receive(location_ids, product_id, lot_id)
            _tmp = dict()
            _tmp["erp"] = "Odoo"
            _tmp["warehouse"] = warehouse
            _tmp["storage_location"] = location_name
            (_tmp["barcode"], _tmp["product_name"]) = products.get_barcode(product_id)
            _tracking = self.get_tracking(product_id, lot_id)
            if _tracking == "lot":
                (_tmp["lot"], _tmp["expiry_date"]) = self.get_lot_n_expiry(product_id,
                                                                           lot_id="x" if not bool(lot_id) else lot_id)
                _tmp["serial"] = None
            elif _tracking == "serial":
                (_tmp["serial"], _tmp["expiry_date"]) = self.get_lot_n_expiry(product_id, lot_id="x" if not bool(
                    lot_id) else lot_id)
                _tmp["lot"] = None
            else:
                _tmp["lot"] = None
                _tmp["serial"] = None
                _tmp["expiry_date"] = None
            _tmp["in_stock"] = int(in_stock)
            _tmp["available"] = int(available)
            _tmp["allocated"] = int(allocated)
            _tmp["quarantined"] = int(quarantine)
            _tmp["to_receive"] = int(to_receive)
            _tmp.pop("quarantined", None)
            _records.append(_tmp)
        return _records

    def get_item_instant_inventory_details(self, inputs):
        product_code = str(inputs["product_code"])
        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_code=product_code)

        location_name = inputs["location_name"]
        locations = Locations(company_id=self.company_id, user_id=self.user_id)
        location_ids = locations.get_location_ids_including_all_child_locations(location_name=location_name)

        start_date = inputs["start_date"]
        end_date = inputs["end_date"]

        lot_id = None
        lot_name = None
        is_lot_serial = None
        if not bool(inputs["serial"]) and not bool(inputs["lot"]):
            self.is_no_tracking = True
        else:
            if bool(inputs["serial"]):
                lot_name = str(inputs["serial"])
                is_lot_serial = "serial"
            elif bool(inputs["lot"]):
                lot_name = str(inputs["lot"])
                is_lot_serial = "lot"
            if bool(lot_name):
                lot_id = self.get_lot_n_expiry(product_id, lot_name=lot_name)
                if not bool(lot_id):
                    raise Exception("The lot/serial (" + lot_name + ") does not exist in Odoo!")

        _response = dict()
        _tmp = dict()
        _tmp["erp"] = "Odoo"
        _tmp["warehouse"] = locations.get_warehouse_name_by_stock_location(location_name=location_name)
        _tmp["location"] = location_name
        (_tmp["barcode"], _tmp["product_name"]) = products.get_barcode(product_id)
        _tracking = self.get_tracking(product_id, lot_id)
        if _tracking == "lot":
            if is_lot_serial == "serial":
                raise Exception("The serial (" + lot_name + ") does not exist in Odoo!")
            (_tmp["lot"], _tmp["expiry_date"]) = self.get_lot_n_expiry(product_id,
                                                                       lot_id="x" if not bool(lot_id) else lot_id)
            _tmp["serial"] = None
        elif _tracking == "serial":
            if is_lot_serial == "lot":
                raise Exception("The lot (" + lot_name + ") does not exist in Odoo!")
            (_tmp["serial"], _tmp["expiry_date"]) = self.get_lot_n_expiry(product_id,
                                                                          lot_id="x" if not bool(lot_id) else lot_id)
            _tmp["lot"] = None
        else:
            _tmp["lot"] = None
            _tmp["serial"] = None
            _tmp["expiry_date"] = None

        (_tmp["in_stock"], _tmp["available"], _tmp["allocated"], _tmp["quarantined"],
         _tmp["to_receive"]) = self.get_stock(location_ids, product_id, lot_id)
        _tmp.pop("quarantined", None)
        _response["stocks"] = _tmp

        _response["location_stocks"] = self.get_location_wise_item_stock(_tmp["warehouse"], location_name, location_ids,
                                                                         product_id, lot_id)

        inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id)
        _response["inbounds"] = inbounds.get_item_inbounds(location_ids, product_id, start_date, end_date, lot_serial=lot_id)

        outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id)
        _response["outbounds"] = outbounds.get_item_outbounds(location_ids, product_id, start_date, end_date, lot_serial=lot_id)
        return _response

    @staticmethod
    def is_expiration_valid(expiry_date):
        is_valid = False
        if bool(expiry_date):
            x_dt = datetime.datetime.strptime(str(expiry_date), "%Y-%m-%d %H:%M:%S")
            if x_dt > datetime.datetime.now():
                is_valid = True
        return is_valid

    def validate_stock_with_source(self, p_id, inputs):
        is_valid = False
        quantity = 0
        if "quantity" in inputs and float(inputs["quantity"]) > 0:
            quantity = float(inputs["quantity"])

        serial_name = inputs["serial"]
        lot_name = inputs["lot"]
        if bool(serial_name):
            sl = self.request.env["stock.lot"].sudo().search([("name", "=", serial_name), ("product_id", "=", int(p_id))])
            if bool(sl):
                spl_id = sl[-1].id
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND lot_id = %d""" % (int(self.company_id), int(p_id), int(spl_id))
                if "source" in inputs and bool(inputs["source"]):
                    query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id = %d""" % (int(self.company_id), int(p_id), int(inputs["source"]), int(spl_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    _quantity = 0
                    if bool(records[0]["quantity"]):
                        _quantity = records[0]["quantity"]
                    _reserved_qty = 0
                    #
                    # if bool(records[0]["reserved_qty"]):
                    #     _reserved_qty = records[0]["reserved_qty"]
                    if float(_quantity) - float(_reserved_qty) == quantity:
                        is_valid = True
        elif bool(lot_name):
            sl = self.request.env["stock.lot"].sudo().search([("name", "=", lot_name), ("product_id", "=", int(p_id))])
            if bool(sl):
                spl_id = sl[-1].id
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND lot_id = %d""" % (int(self.company_id), int(p_id), int(spl_id))
                if "source" in inputs and bool(inputs["source"]):
                    query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id = %d""" % (int(self.company_id), int(p_id), int(inputs["source"]), int(spl_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    _quantity = 0
                    if bool(records[0]["quantity"]):
                        _quantity = records[0]["quantity"]
                    _reserved_qty = 0
                    #
                    # if bool(records[0]["reserved_qty"]):
                    #     _reserved_qty = records[0]["reserved_qty"]
                    if float(_quantity) - float(_reserved_qty) >= quantity:
                        is_valid = True
        else:
            _tuple_list = list()
            query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND lot_id IS NULL"""
            _bc_format = inputs["bc_format"]
            if bool(_bc_format) and str(_bc_format).lower() in ["ean", "upc"]:
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d"""
            _tuple_list.append(int(self.company_id))
            _tuple_list.append(int(p_id))

            if "source" in inputs and bool(inputs["source"]):
                query += """ AND location_id = %d"""
                _tuple_list.append(int(inputs["source"]))

            query = query % tuple(_tuple_list)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                _quantity = 0
                if bool(records[0]["quantity"]):
                    _quantity = records[0]["quantity"]
                _reserved_qty = 0
                #
                # if bool(records[0]["reserved_qty"]):
                #     _reserved_qty = records[0]["reserved_qty"]
                if float(_quantity) - float(_reserved_qty) >= quantity:
                    is_valid = True
        return is_valid

    def validate_transfer_lot_serial(self, inputs):
        _res = list()
        _line_items = inputs["line_items"]
        for _each in _line_items:
            products = Products(company_id=self.company_id, user_id=self.user_id)
            product_id = products.get_product_name_id(p_code=_each["product_code"], raise_exception=False)
            product_name = products.get_product_name_id(p_id=product_id)
            if bool(product_id):
                _lot_serial = None
                is_serial = False
                if bool(_each["serial"]):
                    _lot_serial = str(_each["serial"])
                    is_serial = True
                elif bool(_each["lot"]):
                    _lot_serial = str(_each["lot"])
                if bool(_lot_serial):
                    _temp = dict()
                    _temp["product_name"] = str(product_name)
                    _temp["product_code"] = str(_each["product_code"])
                    _temp["lot"] = None if is_serial else str(_each["lot"])
                    _temp["serial"] = str(_each["serial"]) if is_serial else None
                    if "quantity" in _each:
                        _temp["quantity"] = str(_each["quantity"])
                    _temp["is_valid"] = 0
                    _temp["message"] = None

                    _conds = list()
                    _conds.append(("name", "=", str(_lot_serial)))
                    _conds.append(("product_id", "=", int(product_id)))
                    _conds.append(("company_id", "in", [int(self.company_id), False]))
                    _found = self.request.env["stock.lot"].sudo().search(_conds)
                    if bool(_found):
                        if self.is_expiration_valid(_found[-1].expiration_date):
                            if self.validate_stock_with_source(product_id, _each):
                                _temp["is_valid"] = 1
                            else:
                                if is_serial:
                                    _temp["message"] = "The product code " + str(_each["product_code"]) + " with serial " + str(_lot_serial) + " has no stock in the source location!"
                                else:
                                    _temp["message"] = "The product code " + str(_each["product_code"]) + " with lot " + str(_lot_serial) + " has no stock in the source location!"
                        else:
                            if is_serial:
                                _temp["message"] = "The serial " + str(_lot_serial) + " has no valid expiration date!"
                            else:
                                _temp["message"] = "The lot " + str(_lot_serial) + " has no valid expiration date!"
                    else:
                        _temp["message"] = "The lot or serial like " + str(_lot_serial) + " does not exist!"
                    _res.append(_temp)
                else:
                    _temp = dict()
                    _temp["product_name"] = str(product_name)
                    _temp["product_code"] = str(_each["product_code"])
                    _temp["lot"] = None
                    _temp["serial"] = None
                    if "quantity" in _each:
                        _temp["quantity"] = str(_each["quantity"])
                    _temp["is_valid"] = 0
                    _temp["message"] = None
                    if self.validate_stock_with_source(product_id, _each):
                        _temp["is_valid"] = 1
                    else:
                        _temp["message"] = "The product code " + str(_each["product_code"]) + " has no sufficient no-tracking stock!"
                    _res.append(_temp)
            else:
                _temp = dict()
                _temp["product_name"] = None
                _temp["product_code"] = str(_each["product_code"])
                _temp["lot"] = str(_each["lot"]) if bool(_each["lot"]) else None
                _temp["serial"] = str(_each["serial"]) if bool(_each["serial"]) else None
                if "quantity" in _each:
                    _temp["quantity"] = str(_each["quantity"])
                _temp["is_valid"] = 0
                _temp["message"] = "The product code " + str(inputs["product_code"]) + " does not exist!"
                _res.append(_temp)
        return _res

    def validate_transfer(self, src_wh_code, dst_wh_code, source, destination, _line):
        _exception_msg = None
        if int(source) == int(destination):
            raise Exception("Source and destination cannot be same!")
        _conditions = list()
        _conditions.append(("company_id", "in", [self.company_id, False]))
        _conditions.append(("active", "=", True))
        # _conditions.append(("scrap_location", "=", False))
        # _conditions.append(("return_location", "=", False))
        _conditions.append(("usage", "=", "internal"))
        _conditions.append(("id", "=", int(source)))
        stock_location = self.request.env["stock.location"].sudo().search(_conditions)
        if not bool(stock_location):
            raise Exception("Source with id: " + str(source) + " does not exist! It must be an active internal location, not any scrap or return location.")
        if stock_location[-1].complete_name.split("/")[0] != src_wh_code:
            raise Exception("Given source is not available in requested warehouse!")
        _conditions.pop()
        _conditions.append(("id", "=", int(destination)))
        stock_location = self.request.env["stock.location"].sudo().search(_conditions)
        if _exception_msg is None and not bool(stock_location):
            _exception_msg = "Destination with id: " + str(destination) + " does not exist! It must be an active internal location, not any scrap or return location."
        if _exception_msg is None and stock_location[-1].complete_name.split("/")[0] != dst_wh_code:
            _exception_msg = "Given destination is not available in requested destination warehouse!"

        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_code=_line["product_code"], raise_exception=True)
        product_name = products.get_product_name_id(p_id=product_id)
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        _tuple_list.append(int(source))
        lot_id = None
        if bool(_line["lot_serial"]):
            sl = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(product_id))])
            if bool(sl):
                lot_id = sl[-1].id
            else:
                if _exception_msg is None:
                    if _line["lot_or_serial"] == "lot":
                        _exception_msg = "Lot number (" + str(_line["lot_serial"]) + ") does not exist!"
                    else:
                        _exception_msg = "Serial number (" + str(_line["lot_serial"]) + ") does not exist!"
        if bool(lot_id):
            query += """ AND lot_id = %d GROUP BY product_id, lot_id"""
            _tuple_list.append(int(lot_id))
        else:
            query += """ AND lot_id IS NULL GROUP BY product_id, lot_id"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        is_not_available = True
        if bool(records):
            for each in records:
                available = float(float(each["quantity"]) - float(each["reserved_quantity"]))
                if int(available) >= int(_line["quantity"]):
                    is_not_available = False
        if is_not_available:
            if bool(_line["lot_serial"]):
                product_name = str(product_name) + "(" + str(_line["lot_serial"]) + ")"
            if _exception_msg is None:
                _exception_msg = "Requested quantity of " + str(product_name) + " is not available in the given source!"
        if _exception_msg is not None:
            _temp = dict()
            product = self.request.env["product.product"].sudo().search([("barcode", "=", _line["product_code"])])
            _temp["product_name"] = product[-1].name
            _temp["product_code"] = str(_line["product_code"])
            _temp["lot"] = _line["lot_serial"] if _line["lot_or_serial"] == "lot" else None
            _temp["serial"] = _line["lot_serial"] if _line["lot_or_serial"] == "serial" else None
            if "quantity" in _line:
                _temp["quantity"] = str(_line["quantity"])
            _temp["is_valid"] = 0
            _temp["message"] = _exception_msg
            return _temp
        return True

    def get_stock_move_lines(self, picking_id, transfer_lines):
        _stock_move_lines = list()
        for each in transfer_lines:
            lot_id = False
            lot_name = False
            expiration_date = False
            if bool(each["description_picking"]):
                _parts = each["description_picking"].split("<~>")
                _lot_name = _parts[0]
                _lot_product_id = int(_parts[1])
                sl = self.request.env["stock.lot"].sudo().search([("name", "=", _lot_name), ("product_id", "=", int(_lot_product_id))])
                if bool(sl):
                    lot_id = sl[-1].id
                    lot_name = sl[-1].name
                    if bool(sl[-1].expiration_date):
                        expiration_date = sl[-1].expiration_date

            temp = dict()
            temp["company_id"] = int(self.company_id)
            temp["picking_id"] = int(picking_id)
            temp["product_id"] = int(each["product_id"])
            temp["location_id"] = int(each["location_id"])
            temp["location_dest_id"] = int(each["location_dest_id"])
            temp["lot_id"] = lot_id
            temp["lot_name"] = lot_name
            temp["expiration_date"] = expiration_date
            temp["quantity"] = float(each["product_uom_qty"])
            temp["product_uom_id"] = each["product_uom"]
            _stock_move_lines.append(temp)
        return _stock_move_lines

    def execute_internal_transfer(self, picking_type_id, _source, _destination, data):
        stock_transfer = None
        _note = False
        product_uom = 1
        _move_ids_without_package = list()
        for _line in data:
            product_uom_qty = int(_line["quantity"])
            if not bool(_note) and "note" in _line and bool(_line["note"]):
                _note = _line["note"]
            product = self.request.env["product.product"].sudo().search([("barcode", "=", _line["product_code"])])
            product_id = product[-1].id
            product_name = product[-1].name
            product.sudo().write({"tracking": _line["lot_or_serial"], "use_expiration_date": True if _line["lot_or_serial"] != "none" else False})

            _move_line = dict()
            _move_line["company_id"] = int(self.company_id)
            _move_line["name"] = product_name
            _move_line["state"] = "confirmed"
            _move_line["picking_type_id"] = int(picking_type_id)
            _move_line["location_id"] = _source
            _move_line["location_dest_id"] = _destination
            _move_line["product_id"] = int(product_id)
            _move_line["description_picking"] = str(_line["lot_serial"]) + "<~>" + str(product_id)
            _move_line["product_uom_qty"] = product_uom_qty
            _move_line["product_uom"] = product_uom
            _move_ids_without_package.append(_move_line)

        if bool(_move_ids_without_package):
            payload = dict()
            payload["is_locked"] = True
            payload["picking_type_id"] = int(picking_type_id)
            payload["location_id"] = int(_source)
            payload["location_dest_id"] = int(_destination)
            payload["move_type"] = "direct"
            payload["user_id"] = int(self.user_id)
            payload["company_id"] = int(self.company_id)
            payload["note"] = _note
            payload["move_ids_without_package"] = [(0, False, _move_line) for _move_line in _move_ids_without_package]
            create_transfer = self.request.env["stock.picking"].sudo().create(payload)
            if bool(create_transfer):
                stock_transfer_lines = self.get_stock_move_lines(create_transfer.id, _move_ids_without_package)
                for i in range(len(create_transfer.move_ids_without_package)):
                    _line_to_move = stock_transfer_lines[i]
                    _quantity = _line_to_move["quantity"]
                    _product_uom_id = _line_to_move["product_uom_id"]
                    _product_id = _line_to_move["product_id"]
                    stock_move = self.request.env["stock.move"].sudo().search([("id", "=", create_transfer.move_ids_without_package[i].id)])
                    if bool(stock_move):
                        stock_move.sudo().write({
                            "company_id": int(self.company_id),
                            "product_id": _product_id,
                            "product_uom": _product_uom_id,
                            "product_uom_qty": _quantity,
                            "location_id": int(_source),
                            "location_dest_id": int(_destination),
                            "move_line_ids": [(0, False, _line_to_move)]
                        })
                create_transfer.button_validate()
                stock_transfer = create_transfer.name
        if not bool(stock_transfer):
            raise Exception("An error occurred in internal transfer!")
        return stock_transfer

    def internal_transfer(self, inputs):
        _response = dict()
        stock_transfer = None
        if "line_items" in inputs and bool(inputs["line_items"]) and isinstance(inputs["line_items"], list):
            source = inputs["source"]
            destination = inputs["destination"]
            warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", str(inputs["src_wh_name"]))])
            if not bool(warehouse):
                raise Exception("Warehouse(" + str(inputs["src_wh_name"]) + " does not exist!")
            wh_id = warehouse[-1].id
            src_wh_code = warehouse[-1].code

            internal_operation = self.request.env["stock.picking.type"].sudo().search([("warehouse_id", "=", int(wh_id)), ("sequence_code", "=", "INT"), ("code", "=", "internal")])
            if not bool(internal_operation):
                raise Exception("Internal transfer not yet setup for the source warehouse! Contact administrator.")
            stock_picking_type_id = internal_operation[-1].id

            warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", str(inputs["dst_wh_name"]))])
            if not bool(warehouse):
                raise Exception("Warehouse(" + str(inputs["dst_wh_name"]) + " does not exist!")
            dst_wh_code = warehouse[-1].code

            _res = list()
            for line_item in inputs["line_items"]:
                is_valid = self.validate_transfer(src_wh_code, dst_wh_code, source, destination, line_item)
                if not isinstance(is_valid, bool):
                    _res.append(is_valid)
            if bool(_res):
                return _res
            else:
                stock_transfer = self.execute_internal_transfer(stock_picking_type_id, source, destination, inputs["line_items"])
        if bool(stock_transfer):
            _response["stock_transfer"] = stock_transfer
        return _response

    def validate_quarantine(self, wh_code, _line):
        stock_location = self.request.env["stock.location"].sudo().search([("id", "=", int(_line["source"]))])
        if not bool(stock_location):
            raise Exception("Source with id: " + str(_line["source"]) + " does not exist!")
        if stock_location[-1].complete_name.split("/")[0] != wh_code:
            raise Exception("Given source is not available in requested warehouse!")
        stock_location = self.request.env["stock.location"].sudo().search([("id", "=", int(_line["destination"]))])
        if not bool(stock_location):
            raise Exception("Destination with id: " + str(_line["destination"]) + " does not exist!")

        products = Products(company_id=self.company_id, user_id=self.user_id)
        product_id = products.get_product_name_id(p_code=_line["product_code"], raise_exception=True)
        product_name = products.get_product_name_id(p_id=product_id)
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        _tuple_list.append(int(_line["source"]))
        lot_id = None
        if bool(_line["lot_serial"]):
            sl = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(product_id))])
            if bool(sl):
                lot_id = sl[-1].id
            else:
                if _line["lot_or_serial"] == "lot":
                    raise Exception("Lot number (" + str(_line["lot_serial"]) + ") does not exist!")
                else:
                    raise Exception("Serial number (" + str(_line["lot_serial"]) + ") does not exist!")
        if bool(lot_id):
            query += """ AND lot_id = %d GROUP BY product_id, lot_id"""
            _tuple_list.append(int(lot_id))
        else:
            query += """ AND lot_id IS NULL GROUP BY product_id, lot_id"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        is_not_available = True
        if bool(records):
            for each in records:
                available = float(float(each["quantity"]) - float(each["reserved_quantity"]))
                if int(available) >= int(_line["quantity"]):
                    is_not_available = False
        if is_not_available:
            if bool(_line["lot_serial"]):
                product_name = str(product_name) + "(" + str(_line["lot_serial"]) + ")"
            raise Exception("Requested quantity of " + str(product_name) + " is not available in the given source!")

    def stock_quarantine(self, inputs):
        _response = dict()
        if "line_items" in inputs and bool(inputs["line_items"]) and isinstance(inputs["line_items"], list):
            warehouse = self.request.env["stock.warehouse"].sudo().search(
                [("name", "=", str(inputs["warehouse_name"]))])
            if not bool(warehouse):
                raise Exception("Warehouse(" + str(inputs["warehouse_name"]) + " does not exist!")
            wh_code = warehouse[-1].code
            for _line in inputs["line_items"]:
                self.validate_quarantine(wh_code, _line)

            try:
                stock_quarantined = list()
                for _line in inputs["line_items"]:
                    products = Products(company_id=self.company_id, user_id=self.user_id)
                    product_id = products.get_product_name_id(p_code=_line["product_code"])

                    lot_id = False
                    if bool(_line["lot_serial"]):
                        sl = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(product_id))])
                        if bool(sl):
                            lot_id = sl[-1].id

                    payload = dict()
                    payload["product_uom_id"] = 1
                    payload["product_id"] = int(product_id)
                    payload["lot_id"] = lot_id
                    payload["scrap_qty"] = int(_line["quantity"])
                    payload["location_id"] = int(_line["source"])
                    payload["scrap_location_id"] = int(_line["destination"])
                    payload["origin"] = _line["source_document"]
                    payload["company_id"] = int(self.company_id)
                    create_scrap = self.request.env["stock.scrap"].sudo().create(payload)
                    if bool(create_scrap):
                        stock_scrap = self.request.env["stock.scrap"].sudo().search([("id", "=", int(create_scrap.id))])
                        stock_scrap.action_validate()
                        stock_quarantined.append(stock_scrap[-1].name)
                if bool(stock_quarantined):
                    _response["stock_quarantined"] = stock_quarantined
            except Exception as e:
                e.__str__()
                raise Exception("An error occurred in quarantine!")
        return _response

    def get_low_stock(self, product_id, *,  lot_id=None, location_ids=None):
        _min_stock = 0
        # _available = 0
        product = self.request.env["product.product"].sudo().search([("id", "=", int(product_id))])
        if bool(product) and bool(product[-1].middleware_min_stock):
            _min_stock = product[-1].middleware_min_stock
        in_stock = 0
        _tuple_list = list()
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity FROM stock_quant WHERE company_id = %d AND product_id = %d"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(product_id))
        if bool(location_ids):
            _loc_ids = "'" + "', '".join(location_ids) + "'"
            query += """ AND location_id IN (%s)"""
            _tuple_list.append(_loc_ids)
        if bool(lot_id):
            query += """ AND lot_id = %d GROUP BY product_id, lot_id"""
            _tuple_list.append(int(lot_id))
        else:
            query += """ AND lot_id IS NULL"""
            query += """ GROUP BY product_id"""
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        if bool(records):
            for each in records:
                # in_stock = float(each["quantity"])
                # available = float(in_stock - float(each["reserved_quantity"]))
                in_stock = float(each["quantity"])
        return 1 if float(in_stock) <= _min_stock else 0

    def get_validation_statuses(self, product_id, lot_serial, location_ids):
        quality_inspection = 1
        expired_item = 0
        wrong_item = 0
        # fragile_item = 0
        low_stock = 0
        if bool(product_id):
            if bool(lot_serial):
                _tuple_list = list()
                query = """SELECT * FROM stock_lot WHERE company_id = %d AND product_id = %d and name = '%s' and location_id IN (%s)"""
                _tuple_list.append(int(self.company_id))
                _tuple_list.append(int(product_id))
                _tuple_list.append(str(lot_serial))
                if bool(location_ids):
                    _loc_ids = "'" + "', '".join(location_ids) + "'"
                    _tuple_list.append(_loc_ids)
                query = query % tuple(_tuple_list)
                self.request.env.cr.execute(query)
                _found = self.request.env.cr.dictfetchall()
                if len(_found) > 0:
                    lot_serial_id = _found[0]["id"]
                    query = """SELECT * FROM stock_scrap WHERE lot_id = %d AND product_id = %d""" % (int(lot_serial_id), int(product_id))
                    self.request.env.cr.execute(query)
                    records = self.request.env.cr.dictfetchall()
                    if len(records) > 0:
                        quality_inspection = 0
                        # fragile_item = 1
                        wrong_item = 1
                    else:
                        is_low_stock = self.get_low_stock(product_id, lot_id=lot_serial_id, location_ids=location_ids)
                        if bool(is_low_stock):
                            quality_inspection = 0
                            low_stock = 1
                        else:
                            is_invalid_expiry = True
                            query = """SELECT name, expiration_date FROM stock_lot WHERE id = %d AND company_id = %d AND product_id = %d""" % (
                                int(lot_serial_id), int(self.company_id), int(product_id))
                            self.request.env.cr.execute(query)
                            records = self.request.env.cr.dictfetchall()
                            for _row in records:
                                if is_invalid_expiry and bool(_row["expiration_date"]):
                                    x_dt = datetime.datetime.strptime(str(_row["expiration_date"]), "%Y-%m-%d %H:%M:%S")
                                    if x_dt > datetime.datetime.now():
                                        is_invalid_expiry = False
                            if is_invalid_expiry:
                                quality_inspection = 0
                                expired_item = 1
                else:
                    quality_inspection = 0
                    wrong_item = 1
            else:
                query = """SELECT * FROM stock_scrap WHERE lot_id IS NULL AND product_id = %d""" % (int(product_id))
                if bool(location_ids):
                    _loc_ids = "'" + "', '".join(location_ids) + "'"
                    query = """SELECT * FROM stock_scrap WHERE lot_id IS NULL AND product_id = %d AND location_id IN(%s)""" % (int(product_id), _loc_ids)
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    quality_inspection = 0
                    # fragile_item = 1
                    wrong_item = 1
                else:
                    is_low_stock = self.get_low_stock(product_id, location_ids=location_ids)
                    if bool(is_low_stock):
                        quality_inspection = 0
                        low_stock = 1
        else:
            quality_inspection = 0
            wrong_item = 1
        return quality_inspection, expired_item, wrong_item, low_stock

    def validate_multi_scan_lot_serial(self, inputs):
        _res = list()
        location_ids = list()
        if "warehouse" in inputs and bool(inputs["warehouse"]):
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            location_ids = locations.get_location_ids_including_all_child_locations(location_name=inputs["warehouse"])

        _line_items = json.loads(inputs["line_items"])
        products = Products(company_id=self.company_id, user_id=self.user_id)
        for _each in _line_items:
            product_id = products.get_product_name_id(p_code=str(_each["product_code"]), raise_exception=False)

            _lot_serial = None
            is_serial = False
            if bool(_each["serial"]):
                _lot_serial = str(_each["serial"])
                is_serial = True
            elif bool(_each["lot"]):
                _lot_serial = str(_each["lot"])

            if bool(product_id):
                if bool(_lot_serial):
                    _temp = dict()
                    _temp["product_code"] = str(_each["product_code"])
                    _temp["lot"] = None if is_serial else str(_each["lot"])
                    _temp["serial"] = str(_each["serial"]) if is_serial else None
                    (_temp["quality_inspection"], _temp["expired_item"], _temp["wrong_item"], _temp["low_stock"]) = self.get_validation_statuses(product_id, _lot_serial, location_ids)
                    _res.append(_temp)
                else:
                    _temp = dict()
                    _temp["product_code"] = str(_each["product_code"])
                    _temp["lot"] = None
                    _temp["serial"] = None
                    (_temp["quality_inspection"], _temp["expired_item"], _temp["wrong_item"], _temp["low_stock"]) = self.get_validation_statuses(product_id, _lot_serial, location_ids)
                    _res.append(_temp)
            else:
                _temp = dict()
                _temp["product_code"] = str(_each["product_code"])
                _temp["lot"] = str(_each["lot"]) if bool(_each["lot"]) else None
                _temp["serial"] = str(_each["serial"]) if bool(_each["serial"]) else None
                (_temp["quality_inspection"], _temp["expired_item"], _temp["wrong_item"], _temp["low_stock"]) = self.get_validation_statuses(product_id, _lot_serial, location_ids)
                _res.append(_temp)
        return _res

    def get_tracking_by_ls_name(self, product_id, lot_name):
        _tracking = None
        if bool(lot_name):
            query = """SELECT * FROM stock_move_line WHERE quantity > 0 AND company_id = %d AND product_id = %d AND lot_name = '%s' GROUP BY id HAVING MAX(quantity) > 1 LIMIT 1""" % (int(self.company_id), int(product_id), str(lot_name))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                _tracking = "lot"
            else:
                _tracking = "serial"
        return _tracking

    def arrange_ids(self, _list_a, _list_b, _is_and):
        _ids = list(set(_list_a + _list_b))
        if _is_and:
            if bool(_ids):
                if bool(_list_a) and bool(_list_b):
                    _tmp_ids = list(set(_list_a).intersection(set(_list_b)))
                    if bool(_tmp_ids):
                        _ids = _tmp_ids
                    else:
                        _ids = list()
        return _ids

    def get_product_n_ls_ids(self, _criteria, _is_and):
        is_notracking = False
        _product_ids = list()
        _ls_ids = list()
        _temp_product_ids = list()
        _temp_ls_ids = list()

        for criteria in _criteria:
            _name_pids = list()
            for key, val in criteria.items():
                if key == "type" and val == "name" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT PP.id, PP.barcode FROM product_product AS PP LEFT JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PP.barcode IS NOT NULL AND PT.company_id = %d"""
                    _tuple_list.append(int(self.company_id))
                    if criteria["condition"] == "EQUALS_TO":
                        query += """ AND LOWER(PT.name ->> 'en_US') = '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower())
                    elif criteria["condition"] == "CONTAINS":
                        query += """ AND LOWER(PT.name ->> 'en_US') LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "STARTS_WITH":
                        query += """ AND LOWER(PT.name ->> 'en_US') LIKE '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "ENDS_WITH":
                        query += """ AND LOWER(PT.name ->> 'en_US') LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower())
                    if len(_tuple_list) > 1:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            _name_pids.append(str(_row["id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _name_pids, _is_and)

        for criteria in _criteria:
            _barcode_pids = list()
            for key, val in criteria.items():
                if key == "type" and val == "barcode" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT PP.id, PP.barcode FROM product_product AS PP LEFT JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PP.barcode IS NOT NULL AND PT.company_id = %d"""
                    _tuple_list.append(int(self.company_id))
                    if criteria["condition"] == "EQUALS_TO":
                        query += """ AND LOWER(PP.barcode) = '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower())
                    elif criteria["condition"] == "CONTAINS":
                        query += """ AND LOWER(PP.barcode) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "STARTS_WITH":
                        query += """ AND LOWER(PP.barcode) LIKE '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "ENDS_WITH":
                        query += """ AND LOWER(PP.barcode) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower())
                    if len(_tuple_list) > 1:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            _barcode_pids.append(str(_row["id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _barcode_pids, _is_and)

        for criteria in _criteria:
            _status_pids = list()
            for key, val in criteria.items():
                if key == "type" and val == "status" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT PP.id, PP.barcode FROM product_product AS PP LEFT JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PP.barcode IS NOT NULL AND PT.company_id = %d"""
                    _tuple_list.append(int(self.company_id))
                    _product_status = "t" if bool(int(criteria["value"])) else "f"
                    query += """ AND PP.active = '%s'"""
                    _tuple_list.append(_product_status)
                    if len(_tuple_list) > 1:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            _status_pids.append(str(_row["id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _status_pids, _is_and)

        for criteria in _criteria:
            _supplier_pids = list()
            for key, val in criteria.items():
                if key == "type" and val == "supplier" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT id FROM res_partner WHERE supplier_rank > 0"""
                    if criteria["condition"] == "EQUALS_TO":
                        query += """ AND LOWER(name) = '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower())
                    elif criteria["condition"] == "CONTAINS":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "STARTS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "ENDS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower())
                    if len(_tuple_list) > 0:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            _supplier_id = _row["id"]
                            query = """SELECT DISTINCT SML.product_id FROM stock_picking AS SP INNER JOIN stock_move_line AS SML ON SP.id = SML.picking_id WHERE SP.company_id = %d AND SP.partner_id = %d AND SP.name LIKE '%s'""" % (int(self.company_id), int(_supplier_id), "%/IN/%")
                            self.request.env.cr.execute(query)
                            _records = self.request.env.cr.dictfetchall()
                            if len(_records) > 0:
                                for _rec in _records:
                                    _supplier_pids.append(str(_rec["product_id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _supplier_pids, _is_and)

        is_notracking_applied = False
        for criteria in _criteria:
            _notracking_product_ids = list()
            _notracking_lot_ids = list()
            for key, val in criteria.items():
                if key == "type" and val == "no_tracking" and bool(str(criteria["value"])):
                    is_notracking_applied = True
                    _tuple_list = list()
                    query = """SELECT product_id, lot_id FROM stock_move_line WHERE company_id = %d AND lot_id IS NOT NULL"""
                    if bool(int(criteria["value"])):
                        is_notracking = True
                        query = """SELECT product_id, lot_id FROM stock_move_line WHERE company_id = %d AND lot_id IS NULL"""
                    _tuple_list.append(int(self.company_id))
                    query += """ GROUP BY product_id, lot_id"""
                    query = query % tuple(_tuple_list)
                    self.request.env.cr.execute(query)
                    records = self.request.env.cr.dictfetchall()
                    for _row in records:
                        _notracking_product_ids.append(str(_row["product_id"]))
                        if bool(_row["lot_id"]):
                            _notracking_lot_ids.append(str(_row["lot_id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _notracking_product_ids, _is_and)
            _temp_ls_ids = self.arrange_ids(_temp_ls_ids, _notracking_lot_ids, _is_and)

        for criteria in _criteria:
            _serial_product_ids = list()
            _serial_lot_ids = list()
            _tuple_list = list()
            query = """SELECT id, product_id FROM stock_lot WHERE company_id = %d"""
            _tuple_list.append(int(self.company_id))
            for key, val in criteria.items():
                if key == "expiry" and bool(str(val["value"])):
                    if val["condition"] == "BETWEEN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') BETWEEN '%s' AND '%s'"""
                        _value = val["value"].split("<~>")
                        _tuple_list.append(_value[0])
                        _tuple_list.append(_value[1])
                    elif val["condition"] == "BEFORE_DAYS":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') <= '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "AFTER_DAYS":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') >= '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "GREATER_THAN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') > '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "LESS_THAN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') < '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "EQUALS_TO":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') = '%s'"""
                        _tuple_list.append(val["value"])
                elif key == "type" and val == "serial_tracking" and bool(str(criteria["value"])):
                    if criteria["condition"] == "EQUALS_TO":
                        query += """ AND LOWER(name) = '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower())
                    elif criteria["condition"] == "CONTAINS":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "STARTS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "ENDS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower())
            if len(_tuple_list) > 1:
                query = query % tuple(_tuple_list)
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _row in records:
                    _serial_product_ids.append(str(_row["product_id"]))
                    if _is_and and is_notracking_applied and bool(is_notracking):
                        _temp_ls_ids = list()
                    else:
                        _serial_lot_ids.append(str(_row["id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _serial_product_ids, _is_and)
            _temp_ls_ids = self.arrange_ids(_temp_ls_ids, _serial_lot_ids, _is_and)

        for criteria in _criteria:
            _lot_product_ids = list()
            _lot_lot_ids = list()
            _tuple_list = list()
            query = """SELECT id, product_id FROM stock_lot WHERE company_id = %d"""
            _tuple_list.append(int(self.company_id))
            for key, val in criteria.items():
                if key == "expiry" and bool(str(val["value"])):
                    if val["condition"] == "BETWEEN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') BETWEEN '%s' AND '%s'"""
                        _value = val["value"].split("<~>")
                        _tuple_list.append(_value[0])
                        _tuple_list.append(_value[1])
                    elif val["condition"] == "BEFORE_DAYS":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') <= '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "AFTER_DAYS":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') >= '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "GREATER_THAN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') > '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "LESS_THAN":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') < '%s'"""
                        _tuple_list.append(val["value"])
                    elif val["condition"] == "EQUALS_TO":
                        query += """ AND TO_CHAR(expiration_date, 'YYYY-MM-DD HH24:MI:SS') = '%s'"""
                        _tuple_list.append(val["value"])
                elif key == "type" and val == "lot_tracking" and bool(str(criteria["value"])):
                    if criteria["condition"] == "EQUALS_TO":
                        query += """ AND LOWER(name) = '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower())
                    elif criteria["condition"] == "CONTAINS":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "STARTS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append(str(criteria["value"]).lower() + "%")
                    elif criteria["condition"] == "ENDS_WITH":
                        query += """ AND LOWER(name) LIKE '%s'"""
                        _tuple_list.append("%" + str(criteria["value"]).lower())
            if len(_tuple_list) > 1:
                query = query % tuple(_tuple_list)
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _row in records:
                    _lot_product_ids.append(str(_row["product_id"]))
                    if _is_and and is_notracking_applied and bool(is_notracking):
                        _temp_ls_ids = list()
                    else:
                        _lot_lot_ids.append(str(_row["id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _lot_product_ids, _is_and)
            _temp_ls_ids = self.arrange_ids(_temp_ls_ids, _lot_lot_ids, _is_and)

        for criteria in _criteria:
            _in_inventory_product_ids = list()
            for key, val in criteria.items():
                if key == "type" and val == "in_inventory" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT product_id, lot_id, (COALESCE(SUM(quantity), 0) - COALESCE(SUM(reserved_quantity), 0)) AS in_stock FROM stock_quant WHERE company_id = %d"""
                    if _is_and and is_notracking_applied and bool(is_notracking):
                        query = """SELECT product_id, lot_id, (COALESCE(SUM(quantity), 0) - COALESCE(SUM(reserved_quantity), 0)) AS in_stock FROM stock_quant WHERE lot_id IS NULL AND company_id = %d"""
                    _tuple_list.append(int(self.company_id))

                    if bool(_temp_product_ids):
                        _tmp_p_ids = "'" + "', '".join(_temp_product_ids) + "'"
                        query += """ AND product_id IN(%s)"""
                        _tuple_list.append(_tmp_p_ids)
                    query += """ GROUP BY product_id, lot_id"""

                    if len(_tuple_list) > 0:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            if int(criteria["value"]) > 0:
                                if float(_row["in_stock"]) > 0:
                                    if str(_row["product_id"]) not in _in_inventory_product_ids:
                                        _in_inventory_product_ids.append(str(_row["product_id"]))
                            else:
                                if float(_row["in_stock"]) <= 0:
                                    if str(_row["product_id"]) not in _in_inventory_product_ids:
                                        _in_inventory_product_ids.append(str(_row["product_id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _in_inventory_product_ids, _is_and)

        for criteria in _criteria:
            _known_product_ids = list()
            for key, val in criteria.items():
                if key == "type" and val == "is_known" and bool(str(criteria["value"])):
                    _tuple_list = list()
                    query = """SELECT SML.product_id, SML.lot_id FROM stock_picking AS SP LEFT JOIN stock_move_line AS SML ON SP.id = SML.picking_id WHERE SP.company_id = %d AND SP.name LIKE '%s'"""
                    if _is_and and is_notracking_applied and bool(is_notracking):
                        query = """SELECT SML.product_id, SML.lot_id FROM stock_picking AS SP LEFT JOIN stock_move_line AS SML ON SP.id = SML.picking_id WHERE SP.company_id = %d AND SML.lot_id IS NULL AND SP.name LIKE '%s'"""
                    _tuple_list.append(int(self.company_id))
                    _tuple_list.append("%/IN/%")

                    if bool(_temp_product_ids):
                        _tmp_p_ids = "'" + "', '".join(_temp_product_ids) + "'"
                        query += """ AND SML.product_id IN(%s)"""
                        _tuple_list.append(_tmp_p_ids)
                    query += """ GROUP BY SML.product_id, SML.lot_id"""

                    if len(_tuple_list) > 1:
                        query = query % tuple(_tuple_list)
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        for _row in records:
                            if int(criteria["value"]) > 0:
                                if bool(_row["product_id"]):
                                    if str(_row["product_id"]) not in _known_product_ids:
                                        _known_product_ids.append(str(_row["product_id"]))
            _temp_product_ids = self.arrange_ids(_temp_product_ids, _known_product_ids, _is_and)

        for _pid in _temp_product_ids:
            if _pid not in _product_ids:
                _product_ids.append(_pid)
        for _lsid in _temp_ls_ids:
            if _lsid not in _ls_ids:
                _ls_ids.append(_lsid)
        return _product_ids, _ls_ids

    def finder_search(self, inputs):
        _data_set = list()
        _payload = dict()
        _search_with = None
        _items = inputs["items"]
        _is_and = False
        _criteria = list()
        if "criteria" in inputs and bool(inputs["criteria"]):
            criteria = inputs["criteria"]
            _is_and = bool(criteria["is_and"])
            _criteria = criteria["criteria"]
            if bool(_criteria):
                _search_with = "criteria"

        if _search_with == "criteria":
            (product_ids, ls_ids) = self.get_product_n_ls_ids(_criteria, _is_and)
            if bool(product_ids):
                _p_ids = "'" + "', '".join(product_ids) + "'"
                query = """SELECT PP.id, PP.barcode, NULL AS lot_serial_name FROM product_product AS PP LEFT JOIN product_template AS PT ON PP.product_tmpl_id = PT.id WHERE PP.barcode IS NOT NULL AND PT.company_id = %d AND PP.id IN (%s)""" % (int(self.company_id), _p_ids)
                if bool(ls_ids):
                    _ls_ids = "'" + "', '".join(ls_ids) + "'"
                    query = """SELECT PP.id, PP.barcode, SL.name AS lot_serial_name FROM product_product AS PP RIGHT JOIN stock_lot AS SL ON PP.id = SL.product_id WHERE PP.barcode IS NOT NULL AND SL.company_id = %d AND PP.id IN (%s) AND SL.id in (%s)""" % (int(self.company_id), _p_ids, _ls_ids)
                self.request.env.cr.execute(query)
                _new_items = self.request.env.cr.dictfetchall()
                if bool(_new_items):
                    _temp_items = list()
                    for _pid in product_ids:
                        product_code = None
                        lots_serials = list()
                        for _row in _new_items:
                            if int(_pid) == int(_row["id"]):
                                product_code = _row["barcode"]
                                if bool(_row["lot_serial_name"]):
                                    lots_serials.append(_row["lot_serial_name"])
                        if bool(product_code):
                            if bool(lots_serials):
                                _lots = list()
                                for each in lots_serials:
                                    if self.get_tracking_by_ls_name(_pid, each) == "lot":
                                        _lots.append({
                                            "lot_number": str(each),
                                            "p_serials": []
                                        })
                                if bool(_lots):
                                    _temp_items.append({
                                        "product_code": str(product_code),
                                        "lots": _lots
                                    })

                                _serials = list()
                                for each in lots_serials:
                                    if self.get_tracking_by_ls_name(_pid, each) == "serial":
                                        _serials.append(str(each))
                                if bool(_serials):
                                    _temp_items.append({
                                        "product_code": str(product_code),
                                        "lots": [{
                                            "lot_number": None,
                                            "p_serials": _serials
                                        }]
                                    })
                            else:
                                _temp_items.append({
                                    "product_code": str(product_code),
                                    "lots": [{
                                        "lot_number": None,
                                        "p_serials": []
                                    }]
                                })
                    _items = _temp_items

        if bool(_items) and isinstance(_items, list):
            _tracking_product_codes = list()
            _no_tracking_product_codes = list()
            _lots = list()
            for _item in _items:
                for _item_lot in _item["lots"]:
                    if bool(_item_lot["p_serials"]) and isinstance(_item_lot["p_serials"], list):
                        for _serial in _item_lot["p_serials"]:
                            if bool(_serial) and _serial not in _lots:
                                _lots.append(_serial)
                        if bool(_item["product_code"]) and str(_item["product_code"]) not in _tracking_product_codes:
                            _tracking_product_codes.append(str(_item["product_code"]))
                    elif bool(_item_lot["lot_number"]) and _item_lot["lot_number"] not in _lots:
                        _lots.append(_item_lot["lot_number"])
                        if bool(_item["product_code"]) and str(_item["product_code"]) not in _tracking_product_codes:
                            _tracking_product_codes.append(str(_item["product_code"]))
                    else:
                        if bool(_item["product_code"]) and str(_item["product_code"]) not in _no_tracking_product_codes:
                            _no_tracking_product_codes.append(str(_item["product_code"]))

            _payload["limit"] = inputs["limit"]
            _payload["offset"] = inputs["offset"]
            _payload["location_name"] = inputs["location_name"]
            _payload["tracking_product_codes"] = _tracking_product_codes
            _payload["no_tracking_product_codes"] = _no_tracking_product_codes
            _payload["lots"] = _lots
            _payload["items"] = _items
            _data_set = self.get_item_inventory_count(_payload, True)

        _response = dict()
        _response["data_set"] = _data_set
        return _response
    