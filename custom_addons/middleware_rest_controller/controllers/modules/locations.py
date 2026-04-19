# -*- coding: utf-8 -*-
from odoo import http


class Locations(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request

        self.location_ids = list()
        pass

    def get_warehouse_name(self, w_id):
        warehouse_name = None
        data = self.request.env["stock.warehouse"].sudo().search(
            [("company_id", "=", int(self.company_id)), ("id", "=", int(w_id))])
        for each in data:
            warehouse_name = each.name
        return warehouse_name

    def get_warehouse_name_by_stock_location(self, *, location_name=None):
        warehouse_name = None
        if bool(location_name):
            _temp = location_name.split("/")
            _l_name = _temp[0]
            if len(_temp) > 1:
                data = self.request.env["stock.warehouse"].sudo().search(
                    [("company_id", "=", int(self.company_id)), ("code", "=", _l_name)])
                for each in data:
                    warehouse_name = each.name
            else:
                warehouse_name = _l_name
            return warehouse_name

    def get_location_name_id(self, *, location_name=None, location_id=None, stock_location=False):
        if bool(location_name):
            location_id = None
            if bool(stock_location):
                data = self.request.env["stock.location"].sudo().search([("complete_name", "=", location_name)])
                for each in data:
                    location_id = each.id
            else:
                data = self.request.env["stock.warehouse"].sudo().search(
                    [("active", "=", True), ("company_id", "=", int(self.company_id)), ("name", "=", location_name)])
                for each in data:
                    location_id = each.id
            if not bool(location_id):
                raise Exception("Given location(" + str(location_name) + ") does not exist in Odoo!")
            return location_id

        if bool(location_id):
            location_name = None
            if bool(stock_location):
                data = self.request.env["stock.location"].sudo().search([("id", "=", int(location_id))])
                for each in data:
                    location_name = each.complete_name
            else:
                data = self.request.env["stock.warehouse"].sudo().search(
                    [("active", "=", True), ("company_id", "=", int(self.company_id)),
                     ("lot_stock_id", "=", int(location_id))])
                for each in data:
                    location_name = each.name
            if not bool(location_name):
                raise Exception("Given location ID(" + str(location_id) + ") does not exist in Odoo!")
            return location_name

    def find_child_locations(self, location_id):
        query = """SELECT * FROM stock_location WHERE active = TRUE AND usage = 'internal' AND company_id = %d AND location_id = %d""" % (int(self.company_id), int(location_id))
        self.request.env.cr.execute(query)
        data = self.request.env.cr.dictfetchall()
        if bool(data):
            for each in data:
                if bool(each["id"]):
                    self.location_ids.append(str(each["id"]))
                    self.find_child_locations(each["id"])

    def get_location_ids_including_all_child_locations(self, *, location_name=None, only_warehouse=False):
        if bool(location_name):
            location_stock_id = None
            data = self.request.env["stock.warehouse"].sudo().search(
                [("active", "=", True), ("company_id", "=", int(self.company_id)), ("name", "ilike", location_name)])
            for each in data:
                if bool(each.name) and each.name.lower() == location_name.lower():
                    location_stock_id = each.lot_stock_id[0].id
            if bool(only_warehouse):
                if not bool(location_stock_id):
                    raise Exception("Unable to find the location(" + str(location_name) + ").")
                self.location_ids.append(str(location_stock_id))
                return self.location_ids

            if not bool(location_stock_id):
                data = self.request.env["stock.location"].sudo().search([("name", "ilike", location_name)])
                for each in data:
                    if bool(each.name) and each.name.lower() == location_name.lower():
                        location_stock_id = each.id
            if not bool(location_stock_id):
                data = self.request.env["stock.location"].sudo().search([("complete_name", "ilike", location_name)])
                for each in data:
                    if bool(each.complete_name) and each.complete_name.lower() == location_name.lower():
                        location_stock_id = each.id

            if not bool(location_stock_id):
                raise Exception("Given location(" + str(location_name) + ") does not exist in Odoo!")
            else:
                self.location_ids.append(str(location_stock_id))
                self.find_child_locations(location_stock_id)
        return self.location_ids

    def get_all_internal_location_ids(self, *, wh_name=None):
        internal_location_ids = list()
        internal_locations = self.request.env["stock.location"].sudo().search([("usage", "=", "internal")])
        if bool(wh_name):
            warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", wh_name)])
            if bool(warehouse):
                stock_location_name = warehouse[-1].lot_stock_id.complete_name
                internal_locations = self.request.env["stock.location"].sudo().search([("usage", "=", "internal"), ("complete_name", "=", stock_location_name)])
        for each in internal_locations:
            internal_location_ids.append(str(each.id))
        return internal_location_ids

    def get_locations_list(self):
        _locations = list()
        data = self.request.env["stock.warehouse"].sudo().search(
            [("active", "=", True), ("company_id", "=", int(self.company_id))])
        for each in data:
            _tmp = dict()
            _tmp["location_id"] = each.id
            _tmp["location_name"] = each.name
            _locations.append(_tmp)
        return _locations

    def get_warehouse_receipts_id(self, wh):
        warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", wh)])
        warehouse_id = warehouse[-1].id
        stock_picking_type = self.request.env["stock.picking.type"].sudo().search(
            [("warehouse_id", "=", int(warehouse_id)), ("sequence_code", "=", "IN")])
        return int(stock_picking_type[-1].id)

    def get_receiving_destination_locations(self, inputs):
        _records = list()
        _limit = inputs["limit"]
        _offset = inputs["offset"]
        warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", inputs["location_name"])])
        if bool(warehouse):
            wh_code = warehouse[-1].code
            if bool(wh_code):
                wh_code = str(wh_code) + "/Stock%"
                query = """SELECT id, complete_name FROM stock_location WHERE complete_name LIKE '%s' AND scrap_location != 't' ORDER BY id ASC LIMIT %d OFFSET %d""" % (wh_code, int(_limit), int(_offset))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    _records.append({"id": each["id"], "name": each["complete_name"]})
        return _records

    def get_picking_source_locations(self, inputs):
        _records = list()
        _limit = inputs["limit"]
        _offset = inputs["offset"]

        _location_ids = self.get_location_ids_including_all_child_locations(location_name=inputs["location_name"])
        if bool(_location_ids):
            _location_ids = "'" + "', '".join(_location_ids) + "'"

        _lot_name = None
        if "lot" in inputs and bool(inputs["lot"]):
            _lot_name = inputs["lot"]

        _serials = list()
        if "serials" in inputs and bool(inputs["serials"]):
            _serials = inputs["serials"]

        if "product_id" not in inputs or not bool(inputs["product_id"]):
            raise Exception("Product ID is required!")
        product_id = inputs["product_id"]

        if isinstance(_serials, list) and len(_serials) > 0:
            _multiple_locations = list()
            for _serial in _serials:
                query = """SELECT SL.id, SL.complete_name FROM stock_location AS SL INNER JOIN stock_quant AS SQ ON SL.id = SQ.location_id INNER JOIN stock_lot AS SPL ON SQ.lot_id = SPL.id WHERE SQ.quantity > 0 AND SL.usage = 'internal' AND SL.scrap_location != 't' AND SL.company_id = %d AND SQ.product_id = %d AND SPL.name = '%s' AND SQ.location_id IN (%s) GROUP BY SL.id, SL.complete_name ORDER BY SL.id ASC""" % (int(self.company_id), int(product_id), _serial, _location_ids)
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    if each["complete_name"] not in _multiple_locations:
                        _multiple_locations.append(each["complete_name"])
                    _records.append({"id": each["id"], "name": each["complete_name"]})
            if len(_multiple_locations) > 1:
                raise Exception("Multiple sources found in Odoo! You can split serials for each source.")
            elif len(_serials) > len(_records):
                raise Exception("No source found for some serials! Please remove them from the list.")
            else:
                _records = list()
                _serials_str = "'" + "', '".join(_serials) + "'"
                query = """SELECT SL.id, SL.complete_name FROM stock_location AS SL INNER JOIN stock_quant AS SQ ON SL.id = SQ.location_id INNER JOIN stock_lot AS SPL ON SQ.lot_id = SPL.id WHERE SQ.quantity > 0 AND SL.usage = 'internal' AND SL.scrap_location != 't' AND SL.company_id = %d AND SQ.product_id = %d AND SPL.name IN (%s) AND SQ.location_id IN (%s) GROUP BY SL.id, SL.complete_name ORDER BY SL.id ASC LIMIT %d OFFSET %d""" % (
                    int(self.company_id), int(product_id), _serials_str, _location_ids, int(_limit), int(_offset))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    _records.append({"id": each["id"], "name": each["complete_name"]})
        else:
            if bool(_lot_name):
                query = """SELECT SL.id, SL.complete_name FROM stock_location AS SL INNER JOIN stock_quant AS SQ ON SL.id = SQ.location_id INNER JOIN stock_lot AS SPL ON SQ.lot_id = SPL.id WHERE SQ.quantity > 0 AND SL.usage = 'internal' AND SL.scrap_location != 't' AND SL.company_id = %d AND SQ.product_id = %d AND SPL.name = '%s' AND SQ.location_id IN (%s) GROUP BY SL.id, SL.complete_name ORDER BY SL.id ASC LIMIT %d OFFSET %d""" % (int(self.company_id), int(product_id), _lot_name, _location_ids, int(_limit), int(_offset))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    _records.append({"id": each["id"], "name": each["complete_name"]})
            else:
                query = """SELECT SL.id, SL.complete_name FROM stock_location AS SL INNER JOIN stock_quant AS SQ ON SL.id = SQ.location_id WHERE SQ.quantity > 0 AND SL.usage = 'internal' AND SL.scrap_location != 't' AND SL.company_id = %d AND SQ.product_id = %d AND SQ.lot_id IS NULL AND SQ.location_id IN (%s) GROUP BY SL.id, SL.complete_name ORDER BY SL.id ASC LIMIT %d OFFSET %d""" % (int(self.company_id), int(product_id), _location_ids, int(_limit), int(_offset))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    _records.append({"id": each["id"], "name": each["complete_name"]})
        return _records

    def get_receiving_destination_location_name(self, inputs):
        _data = dict()
        query = """SELECT complete_name FROM stock_location WHERE id = %d""" % (int(inputs["destination_id"]))
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for each in records:
            _data["name"] = each["complete_name"]
        return _data

    def get_picking_source_location_name(self, inputs):
        _data = dict()
        query = """SELECT complete_name FROM stock_location WHERE id = %d""" % (int(inputs["source_id"]))
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        for each in records:
            _data["name"] = each["complete_name"]
        return _data

    def get_receiving_destination_location_id(self, inputs):
        _data = dict()
        warehouse_id = int(inputs["warehouse_id"])
        location_path = inputs["location"]
        if bool(warehouse_id):
            query = """SELECT lot_stock_id FROM stock_warehouse WHERE id = %d""" % (int(warehouse_id))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            location_id = None
            for each in records:
                location_id = int(each["lot_stock_id"])
            if bool(location_id):
                parent_location_id = None
                query = """SELECT id, complete_name FROM stock_location WHERE id = %d""" % (int(location_id))
                self.request.env.cr.execute(query)
                location_name = None
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    parent_location_id = each["id"]
                    location_name = each["complete_name"]
                if bool(location_name):
                    complete_path = ""
                    if location_path[0] == "/":
                        complete_path += location_name + location_path
                    else:
                        complete_path += location_name + "/" + location_path
                    destination_id = None
                    query = """SELECT id FROM stock_location WHERE company_id = %d AND complete_name = '%s'""" % (int(self.company_id), complete_path)
                    self.request.env.cr.execute(query)
                    records = self.request.env.cr.dictfetchall()
                    for each in records:
                        destination_id = int(each["id"])
                    if not bool(destination_id):
                        _parts = location_path.split("/")
                        _loc_parts = list()
                        for _part in _parts:
                            if bool(_part):
                                _loc_parts.append(_part)
                        count = 0
                        search_loc_path = location_name
                        for _loc in _loc_parts:
                            count += 1
                            search_loc_path += "/" + _loc
                            query = """SELECT id FROM stock_location WHERE company_id = %d AND complete_name = '%s'""" % (int(self.company_id), search_loc_path)
                            self.request.env.cr.execute(query)
                            records = self.request.env.cr.dictfetchall()
                            if len(records) > 0:
                                for each in records:
                                    if len(_loc_parts) == count:
                                        destination_id = int(each["id"])
                                    else:
                                        parent_location_id = int(each["id"])
                            else:
                                payload = {
                                    "name": _loc,
                                    "location_id": int(parent_location_id),
                                    "company_id": int(self.company_id),
                                    "active": True
                                }
                                loc_created = self.request.env["stock.location"].sudo().create(payload)
                                if bool(loc_created):
                                    if len(_loc_parts) == count:
                                        destination_id = int(loc_created[-1].id)
                                    else:
                                        parent_location_id = int(loc_created[-1].id)
                    _data["destination_id"] = destination_id
        if not bool(_data):
            raise Exception("An error occurred to get the destination!")
        return _data

    def get_picking_source_location_id(self, inputs):
        _data = dict()
        warehouse_id = int(inputs["warehouse_id"])
        location_path = inputs["location"]
        if bool(warehouse_id):
            query = """SELECT lot_stock_id FROM stock_warehouse WHERE id = %d""" % (int(warehouse_id))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            location_id = None
            for each in records:
                location_id = int(each["lot_stock_id"])
            if bool(location_id):
                query = """SELECT id, complete_name FROM stock_location WHERE id = %d""" % (int(location_id))
                self.request.env.cr.execute(query)
                location_name = None
                records = self.request.env.cr.dictfetchall()
                for each in records:
                    location_name = each["complete_name"]
                if bool(location_name):
                    complete_path = ""
                    if location_path[0] == "/":
                        complete_path += location_name + location_path
                    else:
                        complete_path += location_name + "/" + location_path
                    query = """SELECT id FROM stock_location WHERE company_id = %d AND complete_name = '%s'""" % (int(self.company_id), complete_path)
                    self.request.env.cr.execute(query)
                    records = self.request.env.cr.dictfetchall()
                    for each in records:
                        _data["source_id"] = int(each["id"])
        if not bool(_data):
            raise Exception("An error occurred to get the source!")
        return _data

    def get_storage_location(self, stock_location_id):
        data = self.request.env["stock.location"].sudo().search(
            [("company_id", "=", int(self.company_id)), ("id", "=", int(stock_location_id))])
        for each in data:
            return each.complete_name

    def create_warehouse(self, inputs):
        res = dict()
        payload = {
            "name": inputs["name"],
            "code": inputs["short_name"],
            "partner_id": int(inputs["partner_id"])
        }
        wh_created = self.request.env["stock.warehouse"].sudo().create(payload)
        if bool(wh_created):
            res["warehouse_id"] = wh_created[-1].id
            res["warehouse_location_id"] = wh_created[-1].view_location_id[0].id
            res["warehouse_code"] = payload["code"]
        else:
            raise Exception("Unable to create the warehouse!")
        return res

    def create_location(self, inputs):
        res = dict()
        payload = {
            "name": inputs["name"],
            "location_id": int(inputs["parent"]),
            "active": inputs["status"]
        }
        loc_created = self.request.env["stock.location"].sudo().create(payload)
        if bool(loc_created):
            res["location_id"] = loc_created[-1].id
        else:
            raise Exception("Unable to create the location!")
        return res

    def get_country_state_ids(self, inputs):
        country_id = None
        state_id = None
        country_name = inputs["country_name"]
        state_name = inputs["state_name"]
        countries = self.request.env["res.country"].sudo().search([])
        for each in countries:
            if country_name.lower() == "united states of america" and each.name.lower() == "united states":
                country_id = int(each.id)
            elif country_name.lower() in each.name.lower() and each.name.lower().endswith(country_name.lower()):
                country_id = int(each.id)
        if country_id is not None:
            states = self.request.env["res.country.state"].sudo().search([("country_id", "=?", country_id)])
            for each in states:
                if state_name.lower() in each.name.lower() and each.name.lower().startswith(state_name.lower()):
                    state_id = int(each.id)
        res = dict()
        res["country_id"] = country_id
        res["state_id"] = state_id
        return res

    def check_if_location_exists(self, inputs):
        res = dict()
        warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", inputs["name"])])
        if bool(warehouse):
            res["location_id"] = warehouse[-1].id
        else:
            raise Exception("No such location exists!")
        return res

    def check_warehouse_code(self, inputs):
        res = dict()
        _conds = list()
        _conds.append(("code", "=", inputs["code"]))
        code = self.request.env["stock.warehouse"].sudo().search(_conds)
        if bool(code):
            raise Exception("Code already exists!")
        else:
            res["code"] = inputs["code"]
        return res

    def get_location_by_scan(self, inputs):
        res = dict()
        if bool(inputs["location_barcode"]):
            is_barcode = False
            is_name = False
            is_complete_name = False
            is_id = False

            query = """SELECT id FROM stock_location WHERE barcode = '%s'""" % (str(inputs["location_barcode"]))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                is_barcode = True
            else:
                query = """SELECT id FROM stock_location WHERE name = '%s'""" % (str(inputs["location_barcode"]))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    is_name = True
                else:
                    query = """SELECT id FROM stock_location WHERE complete_name = '%s'""" % (str(inputs["location_barcode"]))
                    self.request.env.cr.execute(query)
                    records = self.request.env.cr.dictfetchall()
                    if len(records) > 0:
                        is_complete_name = True
                    else:
                        _id = 0
                        try:
                            _id = int(inputs["location_barcode"])
                        except Exception as e:
                            e.__str__()
                            pass
                        query = """SELECT id FROM stock_location WHERE id = %d""" % (int(_id))
                        self.request.env.cr.execute(query)
                        records = self.request.env.cr.dictfetchall()
                        if len(records) > 0:
                            is_id = True
            if is_barcode or is_name or is_complete_name or is_id:
                _code = None
                if "wh_name" in inputs and bool(inputs["wh_name"]):
                    warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", inputs["wh_name"])])
                    if bool(warehouse):
                        _code = warehouse[-1].code + "/%"
                    else:
                        raise Exception("Given warehouse does not exist!")

                _conditions = list()
                _conditions.append(("company_id", "in", [self.company_id, False]))
                if is_barcode:
                    _conditions.append(("barcode", "=", str(inputs["location_barcode"])))
                elif is_name:
                    _conditions.append(("name", "=", str(inputs["location_barcode"])))
                elif is_complete_name:
                    _conditions.append(("complete_name", "=", str(inputs["location_barcode"])))
                elif is_id:
                    _conditions.append(("id", "=", int(inputs["location_barcode"])))
                if bool(_code):
                    _conditions.append(("complete_name", "=like", _code))
                stock_locations = self.request.env["stock.location"].sudo().search(_conditions)
                if bool(stock_locations):
                    res["id"] = stock_locations[-1].id
                    res["name"] = stock_locations[-1].complete_name
        if not bool(res):
            raise Exception("No such location exists!")
        return res

    def get_warehouse_by_stock_location(self, inputs):
        res = dict()
        stock_location = self.request.env["stock.location"].sudo().search([("id", "=", inputs["stock_location_id"])])
        if bool(stock_location):
            stock_location_name = stock_location[-1].complete_name
            tmp = stock_location_name.split("/")
            warehouse = self.request.env["stock.warehouse"].sudo().search([("code", "=", tmp[0])])
            if bool(warehouse):
                res["wh_name"] = warehouse[-1].name
        if not bool(res):
            raise Exception("Warehouse not found!")
        return res

    def get_stock_locations(self, inputs):
        if "stock_location" in inputs:
            stock_location = self.request.env["stock.location"].sudo().search([("complete_name", "=", inputs["stock_location"])])
            if bool(stock_location):
                return stock_location[-1].id
        else:
            _locations = list()
            _conditions = list()
            _conditions.append(("company_id", "in", [self.company_id, False]))
            _conditions.append(("active", "=", True))
            if "location_type" in inputs and bool(inputs["location_type"]) and inputs["location_type"] == "scrap":
                _conditions.append(("scrap_location", "=", True))
            elif "location_type" in inputs and bool(inputs["location_type"]) and inputs["location_type"] == "return":
                _conditions.append(("return_location", "=", True))
            else:
                # _conditions.append(("scrap_location", "=", False))
                # _conditions.append(("return_location", "=", False))
                _conditions.append(("usage", "=", "internal"))
                if "warehouse_name" in inputs and bool(inputs["warehouse_name"]):
                    warehouse = self.request.env["stock.warehouse"].sudo().search([("name", "=", inputs["warehouse_name"])])
                    if bool(warehouse):
                        _code = warehouse[-1].code + "/%"
                        _conditions.append(("complete_name", "=like", _code))
            search_term = None
            if "search_term" in inputs and bool(inputs["search_term"]):
                search_term = inputs["search_term"]
                _conditions.append(("complete_name", "ilike", search_term.lower()))
            stock_locations = self.request.env["stock.location"].sudo().search(_conditions, limit=int(inputs["limit"]), offset=int(inputs["offset"]))
            if bool(stock_locations):
                for each in stock_locations:
                    _locations.append({"id": each.id, "name": each.complete_name})
            if not bool(_locations) and "location_type" in inputs and bool(inputs["location_type"]) and inputs["location_type"] == "scrap":
                if not bool(search_term):
                    raise Exception("No scrap location found! Contact administrator.")
            elif not bool(_locations) and "location_type" in inputs and bool(inputs["location_type"]) and inputs["location_type"] == "return":
                if not bool(search_term):
                    raise Exception("No return location found! Contact administrator.")
            return _locations
