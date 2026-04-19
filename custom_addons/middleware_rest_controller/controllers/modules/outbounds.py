# -*- coding: utf-8 -*-
import json
import ast
import datetime
from odoo import http
from odoo.tests import Form
from .locations import Locations
from .partners import Partners
from .users import Users
from .products import Products


class Outbounds(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def create_sales_order(self, inputs):
        _res = dict()
        payload = {
            "name": inputs["name"],
            "warehouse_id": int(inputs["warehouse_id"]),
            "partner_id": int(inputs["customer_id"]),
            "order_line": [(0, False, product) for product in json.loads(inputs["order_line"])]
        }
        so = self.request.env["sale.order"].sudo().create(payload)
        if bool(so):
            so.action_confirm()
            _res["sales_order_id"] = so[-1].id
        else:
            raise Exception("Unable to create the sales order!")
        return _res

    def so_creation_with_delivery(self, inputs):
        _res = dict()
        payload = {
            "name": inputs["name"],
            "warehouse_id": int(inputs["warehouse_id"]),
            "partner_id": int(inputs["customer_id"]),
            "order_line": [(0, False, product) for product in json.loads(inputs["order_line"])]
        }
        so = self.request.env["sale.order"].sudo().create(payload)
        if bool(so):
            so.action_confirm()
            sales_order_id = so[-1].id
            get_stock_picking = so.action_view_delivery()
            if bool(get_stock_picking) and bool(get_stock_picking["res_id"]):
                stock_picking = self.request.env["stock.picking"].sudo().search(
                    [("id", "=", get_stock_picking["res_id"])])
                if bool(stock_picking):
                    stock_picking.button_validate()

                    immediate_transfer_line_ids = [[0, False, {
                        'picking_id': get_stock_picking["res_id"],
                        'to_immediate': True
                    }]]
                    payload = {
                        'show_transfers': False,
                        'pick_ids': [(4, get_stock_picking["res_id"])],
                        'immediate_transfer_line_ids': immediate_transfer_line_ids
                    }

                    create_transfer = self.request.env["stock.immediate.transfer"].sudo().create(payload)
                    if bool(create_transfer):
                        stock_transfer_id = create_transfer[-1].id
                        transfer = self.request.env["stock.immediate.transfer"].sudo().search(
                            [("id", "=", stock_transfer_id)])
                        transfer.with_context(button_validate_picking_ids=transfer.pick_ids.ids).process()

                        _res["sales_order_id"] = sales_order_id
                    else:
                        raise Exception("Unable to arrange the stock transfer!")
                else:
                    raise Exception("Unable to create the sales order!")
            else:
                raise Exception("Unable to pick stock!")
        else:
            raise Exception("Unable to create the sales order!")
        return _res

    def sale_order_delivery(self, inputs):
        _res = dict()
        so = self.request.env["sale.order"].sudo().search([("id", "=", inputs["sales_order_id"])])
        if bool(so):
            get_stock_picking = so.action_view_delivery()
            if bool(get_stock_picking) and bool(get_stock_picking["res_id"]):
                stock_picking = self.request.env["stock.picking"].sudo().search(
                    [("id", "=", get_stock_picking["res_id"])])
                if bool(stock_picking):
                    if stock_picking[-1].state == "done":
                        raise Exception("Please check if already delivered!")
                    else:
                        stock_picking.button_validate()
                        immediate_transfer_line_ids = [[0, False, {
                            "picking_id": get_stock_picking["res_id"],
                            "to_immediate": True
                        }]]
                        payload = {
                            "show_transfers": False,
                            "pick_ids": [(6, False, [get_stock_picking["res_id"]])],
                            "immediate_transfer_line_ids": immediate_transfer_line_ids
                        }

                        create_transfer = self.request.env["stock.immediate.transfer"].sudo().create(payload)
                        if bool(create_transfer):
                            stock_transfer_id = create_transfer[-1].id
                            transfer = self.request.env["stock.immediate.transfer"].sudo().search(
                                [("id", "=", stock_transfer_id)])
                            transfer.with_context(button_validate_picking_ids=transfer.pick_ids.ids).process()

                            _res["stock_transfer_id"] = stock_transfer_id
                        else:
                            raise Exception("Unable to arrange the stock transfer!")
                else:
                    raise Exception("Please check if already delivered!")
            else:
                raise Exception("Unable to deliver the order!")
        else:
            raise Exception("Sales order not found!")
        return _res

    def get_location_n_customer_by_sale_order(self, so_id):
        location = None
        customer = None
        so = self.request.env["sale.order"].sudo().search([("id", "=", int(so_id))])
        if bool(so):
            location = so[-1].warehouse_id[0].name
            location = location.split(":")[0]
            customer = so[-1].partner_id[0].name
        return location, customer

    def check_duplicate_so_line_items(self, inputs):
        has_duplicate = False
        query = """SELECT * FROM sale_order_line WHERE order_id = %d""" % (int(inputs["so_id"]))
        self.request.env.cr.execute(query)
        line_items = self.request.env.cr.dictfetchall()
        _temp_line_item = list()
        for _li in line_items:
            if _li["product_id"] in _temp_line_item:
                has_duplicate = True
            _temp_line_item.append(_li["product_id"])
        return has_duplicate

    def get_reserved_line_items(self, data):
        barcode_format = None
        reserved_line_items = list()
        if bool(data["calculate_open_picking"]) and "list_type" in data and bool(data["list_type"]) and data["list_type"].lower() == "in_progress":
            _existing = self.request.env["middleware.open.picking"].sudo().search(
                [("so_id", "=", int(data["so_id"])), ("picker_id", "=", int(self.user_id)),
                 ("status", "=", data["list_type"].lower())])
            if bool(_existing):
                barcode_format = _existing[-1].barcode_format
                reserved_line_items = _existing[-1].line_items
        return barcode_format, reserved_line_items

    def get_order_state(self, so_id, list_type):
        _state = "New"
        _in_ref = "%/IN/%"
        _out_ref = "%/OUT/%"
        _so_order_line_data = self.request.env["sale.order.line"].sudo().search([("order_id", "=", int(so_id))])
        _ordered = 0
        _delivered = 0
        if bool(_so_order_line_data):
            for each in _so_order_line_data:
                _ordered += each.product_uom_qty
                query = """SELECT COALESCE(SUM(SML.quantity), 0) AS delivered FROM sale_order_line AS SOL LEFT JOIN stock_move_line AS SML ON SOL.product_id = SML.product_id WHERE SML.state = 'done' AND SOL.order_id = %d AND SML.reference LIKE '%s' AND SML.picking_id IN (SELECT SP.id FROM stock_picking AS SP WHERE SP.id = SML.picking_id AND SP.sale_id = %d) AND SOL.product_id = %d""" % (int(so_id), _out_ref, int(so_id), int(each.product_id))
                self.request.env.cr.execute(query)
                _data = self.request.env.cr.dictfetchall()
                if bool(_data) and len(_data) > 0:
                    _delivered += _data[-1]["delivered"]
        _existing = self.request.env["middleware.open.picking"].sudo().search([("so_id", "=", int(so_id)), ("status", "=", "in_progress")])
        if len(_existing) > 0:
            _state = "In Progress"
        else:
            if _delivered > 0:
                if _ordered == _delivered:
                    _state = "Completed"
                else:
                    _state = "Partially Picked"
        if not bool(list_type):
            if _delivered > 0:
                if _ordered == _delivered:
                    query = """SELECT SO.name FROM sale_order AS SO WHERE SO.id IN (SELECT DISTINCT SP1.sale_id FROM stock_picking AS SP1 WHERE SP1.sale_id = SO.id AND (SELECT COUNT(SP2.id) FROM stock_picking AS SP2 WHERE SP2.sale_id = SO.id AND SP2.state = 'done' AND SP2.name LIKE '%s') > 0) AND SO.company_id = %d AND SO.id = %d""" % (_in_ref, int(self.company_id), int(so_id))
                    self.request.env.cr.execute(query)
                    _data = self.request.env.cr.dictfetchall()
                    if bool(_data) and len(_data) > 0:
                        _state = "Returned"
        return _state

    def list_sale_orders(self, inputs):
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit
        _out_ref = "%/OUT/%"
        _in_ref = "%/IN/%"
        company_id = self.company_id
        list_type = None

        if "calculate_open_picking" in inputs and bool(inputs["calculate_open_picking"]):
            state = "'" + "', '".join(["draft", "cancel"]) + "'"
            query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN sale_order_line AS SOL1 ON SO.id = SOL1.order_id WHERE SOL1.order_id IS NOT NULL AND SO.company_id = %d AND SO.state NOT IN (%s) AND SOL1.product_id NOT IN (SELECT PP1.id FROM product_product AS PP1 INNER JOIN product_template AS PT ON PP1.product_tmpl_id = PT.id WHERE PP1.id = SOL1.product_id AND PT.type != 'product') AND SO.id NOT IN (SELECT SOL2.order_id FROM sale_order_line AS SOL2 INNER JOIN product_product AS PP2 ON SOL2.product_id = PP2.id WHERE (PP2.barcode = '') IS NOT FALSE AND SOL2.order_id = SO.id) AND SO.id NOT IN (SELECT MOP.so_id FROM middleware_open_picking AS MOP WHERE MOP.so_id = SO.id AND MOP.status = 'in_progress') GROUP BY SO.id ORDER BY SO.id DESC LIMIT %d OFFSET %d""" % (int(company_id), state, _limit, _offset)
            if "list_type" in inputs and bool(inputs["list_type"]):
                state = "'" + "', '".join(["draft", "sent", "cancel"]) + "'"
                list_type = inputs["list_type"].lower()
                if list_type == "to_do":
                    query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN sale_order_line AS SOL1 ON SO.id = SOL1.order_id WHERE SOL1.order_id IS NOT NULL AND SO.company_id = %d AND SO.state NOT IN (%s) AND SOL1.product_id NOT IN (SELECT PP1.id FROM product_product AS PP1 INNER JOIN product_template AS PT ON PP1.product_tmpl_id = PT.id WHERE PP1.id = SOL1.product_id AND PT.type != 'product') AND SO.id NOT IN (SELECT SOL2.order_id FROM sale_order_line AS SOL2 INNER JOIN product_product AS PP2 ON SOL2.product_id = PP2.id WHERE (PP2.barcode = '') IS NOT FALSE AND SOL2.order_id = SO.id) AND (SELECT COUNT(SML.id) FROM stock_move_line AS SML WHERE SML.reference LIKE '%s' AND SML.state = 'done' AND SML.picking_id IN (SELECT SP1.id FROM stock_picking AS SP1 WHERE SP1.id = SML.picking_id AND SP1.sale_id = SO.id)) = 0 AND SO.id NOT IN (SELECT MOP.so_id FROM middleware_open_picking AS MOP WHERE MOP.so_id = SO.id AND MOP.status = 'in_progress') GROUP BY SO.id ORDER BY SO.id DESC LIMIT %d OFFSET %d""" % (int(company_id), state, _out_ref, _limit, _offset)
                elif list_type == "in_progress":
                    query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN sale_order_line AS SOL1 ON SO.id = SOL1.order_id WHERE SO.company_id = %d AND SO.state NOT IN (%s) AND SOL1.product_id NOT IN (SELECT PP1.id FROM product_product AS PP1 INNER JOIN product_template AS PT ON PP1.product_tmpl_id = PT.id WHERE PP1.id = SOL1.product_id AND PT.type != 'product') AND SO.id NOT IN (SELECT SOL2.order_id FROM sale_order_line AS SOL2 INNER JOIN product_product AS PP2 ON SOL2.product_id = PP2.id WHERE (PP2.barcode = '') IS NOT FALSE AND SOL2.order_id = SO.id) AND ((SELECT COALESCE(SUM(SOL3.product_uom_qty), 0) FROM sale_order_line AS SOL3 WHERE SOL3.order_id = SO.id) - (SELECT COALESCE(SUM(SML.quantity), 0) FROM stock_move_line AS SML WHERE SML.reference LIKE '%s' AND SML.state = 'done' AND SML.picking_id IN (SELECT SP1.id FROM stock_picking AS SP1 WHERE SP1.id = SML.picking_id AND SP1.sale_id = SO.id))) > 0 AND SO.id IN (SELECT MOP.so_id FROM middleware_open_picking AS MOP WHERE MOP.so_id = SO.id AND MOP.status = 'in_progress' AND MOP.picker_id = %d) GROUP BY SO.id ORDER BY SO.id DESC LIMIT %d OFFSET %d""" % (int(company_id), state, _out_ref, int(self.user_id), _limit, _offset)
        else:
            state = "'" + "', '".join(["draft", "sent", "cancel"]) + "'"
            query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN sale_order_line AS SOL1 ON SO.id = SOL1.order_id WHERE SO.company_id = %d AND SO.state NOT IN (%s) AND SOL1.product_id NOT IN (SELECT PP1.id FROM product_product AS PP1 INNER JOIN product_template AS PT ON PP1.product_tmpl_id = PT.id WHERE PP1.id = SOL1.product_id AND PT.type != 'product') AND SO.id NOT IN (SELECT SOL2.order_id FROM sale_order_line AS SOL2 INNER JOIN product_product AS PP2 ON SOL2.product_id = PP2.id WHERE (PP2.barcode = '') IS NOT FALSE AND SOL2.order_id = SO.id) AND ((SELECT COALESCE(SUM(SOL3.product_uom_qty), 0) FROM sale_order_line AS SOL3 WHERE SOL3.order_id = SO.id) - (SELECT COALESCE(SUM(SML.quantity), 0) FROM stock_move_line AS SML WHERE SML.reference LIKE '%s' AND SML.state != 'done' AND SML.picking_id IN (SELECT SP1.id FROM stock_picking AS SP1 WHERE SP1.id = SML.picking_id AND SP1.sale_id = SO.id))) > 0 GROUP BY SO.id ORDER BY SO.id DESC LIMIT %d OFFSET %d""" % (int(company_id), state, _out_ref, _limit, _offset)

        sale_orders = list()
        if bool(query):
            self.request.env.cr.execute(query)
            s_orders_data = self.request.env.cr.dictfetchall()
            for _so in s_orders_data:
                (location, customer) = self.get_location_n_customer_by_sale_order(_so["id"])
                temp = dict()
                temp["id"] = _so["id"]
                temp["duplicate_line_items"] = self.check_duplicate_so_line_items({"so_id": _so["id"]})
                (temp["barcode_format"], temp["reserved_line_items"]) = self.get_reserved_line_items({"list_type": list_type, "so_id": _so["id"], "calculate_open_picking": True if "calculate_open_picking" in inputs and bool(inputs["calculate_open_picking"]) else False})
                temp["name"] = _so["name"]
                temp["customer"] = customer
                temp["location"] = location
                temp["created_on"] = _so["date_order"]
                temp["status"] = self.get_order_state(_so["id"], list_type)
                temp["invoice_ref"] = self.get_invoice_reference(_so["id"])
                sale_orders.append(temp)
        return sale_orders

    def get_so_delivered_qty(self, line):
        _returned_qty = 0
        _line_delivered_qty = 0
        _so_id = line.order_id
        _line_product_id = line.product_id

        so = self.request.env["sale.order"].sudo().search([("id", "=", int(_so_id))])
        view_stock_picking = so.action_view_delivery()
        stock_picking_ids = list()
        if bool(view_stock_picking) and bool(view_stock_picking["res_id"]):
            stock_picking_ids.append(int(view_stock_picking["res_id"]))
        else:
            domain = view_stock_picking["domain"]
            try:
                domain = ast.literal_eval(view_stock_picking["domain"])
            except Exception as e:
                e.__str__()
                pass
            if bool(domain) and bool(domain[0]) and bool(domain[0][2]):
                stock_picking_ids = domain[0][2]
        if bool(stock_picking_ids):
            stock_picking_ids.sort(reverse=True)
            for _id in stock_picking_ids:
                query = """SELECT COALESCE(SUM(SML.quantity), 0) AS delivered_quantity FROM stock_picking AS SP LEFT JOIN stock_move_line AS SML ON SP.id = SML.picking_id WHERE SP.name like '%s' AND SP.state = 'done' AND SML.state = 'done' AND SP.id = %d AND SML.product_id = %d""" % ("%/OUT/%", int(_id), int(_line_product_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _rec in records:
                    _line_delivered_qty += _rec["delivered_quantity"]

                query = """SELECT COALESCE(SUM(SML.quantity), 0) AS returned_quantity FROM stock_picking AS SP LEFT JOIN stock_move_line AS SML ON SP.id = SML.picking_id WHERE SP.name like '%s' AND SP.state = 'done' AND SML.state = 'done' AND SP.id = %d AND SML.product_id = %d""" % ("%/IN/%", int(_id), int(_line_product_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _rec in records:
                    _returned_qty += _rec["returned_quantity"]
        return _line_delivered_qty - _returned_qty

    def list_line_items_by_sale_order(self, inputs):
        list_line_items = list()
        so = self.request.env["sale.order"].sudo().search([("id", "=", int(inputs["so_id"]))])
        if bool(so):
            order_line = so[-1].order_line
            line_item_ids = list()
            for line in order_line:
                line_item_ids.append(line[0].id)
            if bool(line_item_ids):
                for li_id in line_item_ids:
                    line_item = self.request.env["sale.order.line"].sudo().search([("id", "=", int(li_id))])
                    product = line_item[-1].product_id
                    temp = dict()
                    temp["transaction_type"] = "sale"
                    temp["product_id"] = product[0].id
                    temp["product_code"] = product[0].barcode if bool(product[0].barcode) else ""
                    temp["product_name"] = product[0].name
                    temp["product_demand_quantity"] = line_item[-1].product_uom_qty
                    delivered_qty = self.get_so_delivered_qty(line_item[-1])
                    temp["product_delivered_quantity"] = delivered_qty
                    temp["product_qty_to_deliver"] = line_item[-1].product_uom_qty - delivered_qty
                    list_line_items.append(temp)
            else:
                raise Exception("Line items not found for the given sale order!")
        else:
            raise Exception("Given sale order does not exist!")
        return list_line_items

    def check_availability(self, ls_id, qty):
        is_available = False
        available = self.request.env["stock.quant"].sudo().search(
            [("lot_id", "=", int(ls_id)), ("company_id", "=", int(self.company_id)), ("quantity", ">", 0)],
            order="create_date desc")
        if bool(available):
            if float(qty) <= float(available[-1].quantity):
                is_available = True
        return is_available

    def check_availability_with_source(self, p_id, qty_to_pick, loc_id, comp_id, ls_id):
        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id IS NULL""" % (int(comp_id), int(p_id), int(loc_id))
        if bool(ls_id):
            query = """SELECT COALESCE(SUM(quantity), 0) AS quantity FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id = %d""" % (int(comp_id), int(p_id), int(loc_id), int(ls_id))
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _quantity = 0
        if len(records) > 0 and "quantity" in records[0] and bool(records[0]["quantity"]):
            _quantity = float(records[0]["quantity"])
        if float(qty_to_pick) > float(_quantity):
            stock_loc = http.request.env["stock.location"].sudo().search([("id", "=", int(loc_id))])
            products = Products(company_id=self.company_id, user_id=self.user_id)
            p_name = products.get_product_name_id(p_id=p_id)
            if bool(ls_id):
                if int(qty_to_pick) == 1:
                    raise Exception(str(p_name) + " has no sufficient serial-based stock in the given source location(" + str(stock_loc[-1].complete_name) + ").")
                else:
                    raise Exception(str(p_name) + " has no sufficient lot-based stock in the given source location(" + str(stock_loc[-1].complete_name) + ").")
            else:
                raise Exception(str(p_name) + " has no sufficient no-tracking stock in the given source location(" + str(stock_loc[-1].complete_name) + ").")

    def get_lots_serials_nots_quantities(self, data):
        _res = dict()
        _line_items = data
        if bool(_line_items):
            _product_codes = list()
            _lots = list()
            _serials = list()
            _reserved_quantities = list()
            for each in _line_items:
                if each["product_tracking"] == "serial":
                    lots = each["lots"]
                    if bool(lots) and len(lots) > 0:
                        for obj in lots:
                            serials = obj["p_serials"] if bool(obj["p_serials"]) else list()
                            for p in range(len(serials)):
                                _product_codes.append(str(each["product_code"]))
                                _lots.append("")
                                _serials.append(str(serials[p]))
                                _reserved_quantities.append(1)
                elif each["product_tracking"] == "lot":
                    lots = each["lots"]
                    if bool(lots) and len(lots) > 0:
                        for obj in lots:
                            _product_codes.append(str(each["product_code"]))
                            _lots.append(str(obj["lot_number"]))
                            _serials.append("")
                            _reserved_quantities.append(int(obj["quantity"]))
                else:
                    _product_codes.append(str(each["product_code"]))
                    _lots.append("")
                    _serials.append("")
                    _reserved_quantities.append(int(each["quantity"]))
            _res = {"product_codes": _product_codes, "lots": _lots, "serials": _serials,
                    "reserved_quantities": _reserved_quantities}
        return _res

    def get_participant_id(self, participant):
        participant_id = None
        user = http.request.env["res.users"].sudo().search([("login", "ilike", participant)])
        if bool(user):
            participant_id = user[-1].id
        if participant_id is None:
            raise Exception("User(" + str(participant) + ") does not exist in Odoo!")
        return participant_id

    def handle_middleware_open_picking(self, is_backorder, data, *, is_internal=False):
        _so_id = int(data["so_id"])
        query = """SELECT * FROM sale_order WHERE id = {}""".format(_so_id)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        so_name = records[0]["name"]
        notify = False
        participant_id = self.user_id
        assigned_by = self.user_id
        if "participant" in data and bool(data["participant"]):
            participant_id = self.get_participant_id(data["participant"])

        _lots_serials_nots_quantities = self.get_lots_serials_nots_quantities(
            data["reserved_line_items"] if "reserved_line_items" in data and bool(
                data["reserved_line_items"]) else list())
        if is_backorder:
            _existing = self.request.env["middleware.open.picking"].sudo().search(
                [("so_id", "=", int(_so_id)), ("picker_id", "=", int(participant_id))])
            if len(_existing) > 0:
                _columns = dict()
                if "is_void" in data and int(data["is_void"]) == 1:
                    _columns["line_items"] = json.dumps(list())
                    _columns["lots_serials_nots_quantities"] = json.dumps(dict())
                    _columns["status"] = "void"
                else:
                    if int(participant_id) != int(assigned_by):
                        notify = True
                        _columns["assigned_by"] = int(assigned_by)
                    _columns["picker_id"] = int(participant_id)
                    _columns["line_items"] = json.dumps(
                        data["reserved_line_items"] if "reserved_line_items" in data and bool(
                            data["reserved_line_items"]) else list())
                    _columns["lots_serials_nots_quantities"] = json.dumps(_lots_serials_nots_quantities)
                    _columns["status"] = "partial" if is_internal else "in_progress"
                    if "barcode_format" in data and bool(data["barcode_format"]):
                        _columns["barcode_format"] = data["barcode_format"]

                if bool(_columns):
                    for record in _existing:
                        record.update(_columns)
            else:
                if int(assigned_by) != int(participant_id):
                    notify = True

                _columns = dict()
                _columns["so_id"] = _so_id
                _columns["assigned_by"] = int(assigned_by)
                _columns["picker_id"] = int(participant_id)
                _columns["line_items"] = json.dumps(
                    data["reserved_line_items"] if "reserved_line_items" in data and bool(
                        data["reserved_line_items"]) else list())
                _columns["lots_serials_nots_quantities"] = json.dumps(_lots_serials_nots_quantities)
                _columns["status"] = "partial" if is_internal else "void" if "is_void" in data and int(data["is_void"]) == 1 else "in_progress"
                if "barcode_format" in data and bool(data["barcode_format"]):
                    _columns["barcode_format"] = data["barcode_format"]

                _previous_records = self.request.env["middleware.open.picking"].sudo().search([("so_id", "=", int(_so_id))])
                if bool(_previous_records) and len(_previous_records) > 0:
                    for record in _previous_records:
                        _line = self.request.env["middleware.open.picking"].sudo().search([("id", "=", int(record.id))])
                        _line.unlink()
                self.request.env["middleware.open.picking"].sudo().create(_columns)
        else:
            _lines = self.request.env["middleware.open.picking"].sudo().search([("so_id", "=", int(_so_id))])
            if bool(_lines) and len(_lines) > 0:
                for record in _lines:
                    _line = self.request.env["middleware.open.picking"].sudo().search([("id", "=", int(record.id))])
                    _line.unlink()
        user = http.request.env["res.users"].sudo().search([("id", "=", int(participant_id))])
        participant_user = user[-1].login
        return {
            "status": "done",
            "erp": "odoo",
            "type": "participant_reassignment",
            "notify": notify,
            "so_name": so_name,
            "participant": participant_user
        }

    def picking_by_sale_order(self, inputs):
        _res = dict()
        is_backorder = False
        so = self.request.env["sale.order"].sudo().search([("id", "=", int(inputs["so_id"]))])
        if bool(so):
            order_line = so[-1].order_line
            line_item_ids = list()
            for line in order_line:
                line_item_ids.append(line[0].id)
            if bool(line_item_ids):
                products_id = list()
                products_qty_to_pick = list()
                products_product_uom_id = list()
                for li_id in line_item_ids:
                    line_item = self.request.env["sale.order.line"].sudo().search([("id", "=", int(li_id))])
                    product = line_item[-1].product_id
                    products_id.append(int(product[0].id))

                    product_variant = self.request.env["product.product"].sudo().search(
                        [("id", "=", int(product[0].id))])
                    product_template = self.request.env["product.template"].sudo().search(
                        [("id", "=", int(product_variant[-1].product_tmpl_id))])
                    products_product_uom_id.append(
                        {"product_id": str(product[0].id), "uom_id": product_template[-1].uom_id[0].id})
                    products_qty_to_pick.append(
                        {"product_id": str(product[0].id), "qty_to_pick": line_item[-1].qty_to_deliver})

                go = True
                products_to_this_picking = list()
                invalid_product_details = False
                lot_name_not_exist = None
                serial_name_not_exist = None
                serial_ids = list()
                lot_ids = list()
                for l_item in inputs["line_items"]:
                    for key, val in l_item.items():
                        if key == "serials":
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_picking:
                                            products_to_this_picking.append(int(_l_i["product_id"]))
                                        _check_ls_name = None
                                        if "serial_name" in _l_i and bool(_l_i["serial_name"]):
                                            _check_ls_name = _l_i["serial_name"]
                                        if bool(_check_ls_name):
                                            lot_serial = self.request.env["stock.lot"].sudo().search(
                                                [("name", "=", _check_ls_name),
                                                 ("product_id", "=", int(_l_i["product_id"]))])
                                            if not bool(lot_serial):
                                                serial_name_not_exist = _check_ls_name
                                                go = False
                                            else:
                                                ls_id = lot_serial[-1].id
                                                is_available = self.check_availability(ls_id, 1)
                                                if not bool(is_available):
                                                    raise Exception(
                                                        "Requested quantity for the serial(" + _check_ls_name + ") is currently not available!")
                                                else:
                                                    serial_ids.append({_check_ls_name: ls_id})
                                    else:
                                        invalid_product_details = True
                                        go = False
                        elif key == "lots":
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_picking:
                                            products_to_this_picking.append(int(_l_i["product_id"]))
                                        _check_ls_name = None
                                        if "lot_name" in _l_i and bool(_l_i["lot_name"]):
                                            _check_ls_name = _l_i["lot_name"]
                                        if bool(_check_ls_name):
                                            lot_serial = self.request.env["stock.lot"].sudo().search(
                                                [("name", "=", _check_ls_name),
                                                 ("product_id", "=", int(_l_i["product_id"]))])
                                            if not bool(lot_serial):
                                                lot_name_not_exist = _check_ls_name
                                                # go = False #lot-uniqueness
                                            else:
                                                ls_id = lot_serial[-1].id
                                                is_available = self.check_availability(ls_id, _l_i["qty_done"])
                                                if not bool(is_available):
                                                    raise Exception(
                                                        "Requested quantity for the lot(" + _check_ls_name + ") is currently not available!")
                                                else:
                                                    lot_ids.append({_check_ls_name: ls_id})
                                    else:
                                        invalid_product_details = True
                                        go = False
                        else:
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_picking:
                                            products_to_this_picking.append(int(_l_i["product_id"]))
                                    else:
                                        invalid_product_details = True
                                        go = False
                if go:
                    if len(products_id) > len(products_to_this_picking):
                        is_backorder = True

                    stock_picking = None
                    stock_picking_id = None
                    stock_picking_ids = list()
                    view_stock_picking = so.action_view_delivery()
                    if bool(view_stock_picking) and bool(view_stock_picking["res_id"]):
                        stock_picking_ids.append(int(view_stock_picking["res_id"]))
                    else:
                        domain = view_stock_picking["domain"]
                        try:
                            domain = ast.literal_eval(view_stock_picking["domain"])
                        except Exception as e:
                            e.__str__()
                            pass
                        if bool(domain) and bool(domain[0]) and bool(domain[0][2]):
                            stock_picking_ids = domain[0][2]
                    if bool(stock_picking_ids):
                        stock_picking_ids.sort(reverse=True)
                        for _id in stock_picking_ids:
                            stock_picking = self.request.env["stock.picking"].sudo().search([("id", "=", int(_id))])
                            if bool(stock_picking):
                                # if stock_picking[-1].state == "assigned":
                                if stock_picking[-1].state in ["assigned", "confirmed"]:
                                    stock_picking_id = _id
                                    break

                    if not bool(stock_picking_id):
                        raise Exception("An unknown error occurred to pick!")

                    revised_line_items = list()
                    for l_item in inputs["line_items"]:
                        if go:
                            for key, val in l_item.items():
                                if key == "serials":
                                    line_item_product_id = None
                                    serials = list()
                                    for _l_i in val:
                                        line_item_product_id = int(_l_i["product_id"])

                                        product_uom_id = None
                                        for each in products_product_uom_id:
                                            if int(each["product_id"]) == int(_l_i["product_id"]):
                                                product_uom_id = each["uom_id"]
                                        if not bool(product_uom_id):
                                            raise Exception("Invalid product uom id detected!")

                                        if go:
                                            temp = dict()
                                            lot_serial_no_id = None
                                            for each in serial_ids:
                                                for _k, _v in each.items():
                                                    if _k == _l_i["serial_name"]:
                                                        lot_serial_no_id = int(_v)
                                                        temp["lot_id"] = int(_v)
                                                        temp["lot_name"] = _k
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = float(_l_i["qty_done"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            if "source" in _l_i and bool(_l_i["source"]):
                                                temp["location_id"] = int(_l_i["source"])
                                            else:
                                                temp["location_id"] = stock_picking[-1].location_id[0].id
                                            self.check_availability_with_source(temp["product_id"], temp["quantity"], temp["location_id"], temp["company_id"], lot_serial_no_id)
                                            temp["picking_id"] = stock_picking_id
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
                                            temp["result_package_id"] = False
                                            serials.append(temp)

                                    if bool(serials):
                                        for each in products_qty_to_pick:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if int(each["qty_to_pick"]) > len(serials):
                                                    is_backorder = True
                                                if int(each["qty_to_pick"]) < len(serials):
                                                    raise Exception(
                                                        "Picking quantity of a serial-based product is not possible to process!")
                                        revised_line_items.append(serials)
                                elif key == "lots":
                                    lots = list()
                                    total_done_qty = 0
                                    line_item_product_id = None
                                    for _l_i in val:
                                        line_item_product_id = int(_l_i["product_id"])

                                        product_uom_id = None
                                        for each in products_product_uom_id:
                                            if int(each["product_id"]) == int(_l_i["product_id"]):
                                                product_uom_id = each["uom_id"]
                                        if not bool(product_uom_id):
                                            raise Exception("Invalid product uom id detected!")

                                        if go:
                                            total_done_qty = total_done_qty + float(_l_i["qty_done"])
                                            temp = dict()
                                            lot_serial_no_id = None
                                            for each in lot_ids:
                                                for _k, _v in each.items():
                                                    if _k == _l_i["lot_name"]:
                                                        lot_serial_no_id = int(_v)
                                                        temp["lot_id"] = int(_v)
                                                        temp["lot_name"] = _k
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = float(_l_i["qty_done"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            if "source" in _l_i and bool(_l_i["source"]):
                                                temp["location_id"] = int(_l_i["source"])
                                            else:
                                                temp["location_id"] = stock_picking[-1].location_id[0].id
                                            self.check_availability_with_source(temp["product_id"], temp["quantity"], temp["location_id"], temp["company_id"], lot_serial_no_id)
                                            temp["picking_id"] = stock_picking_id
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
                                            temp["result_package_id"] = False
                                            lots.append(temp)
                                    if bool(lots):
                                        for each in products_qty_to_pick:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if float(each["qty_to_pick"]) > total_done_qty:
                                                    is_backorder = True
                                                if float(each["qty_to_pick"]) < total_done_qty:
                                                    raise Exception(
                                                        "Picking quantity of a lot-based product is not possible to process!")

                                        revised_line_items.append(lots)
                                elif key == "normal":
                                    normal = list()
                                    for _l_i in val:
                                        line_item_product_id = int(_l_i["product_id"])

                                        product_uom_id = None
                                        for each in products_product_uom_id:
                                            if int(each["product_id"]) == int(_l_i["product_id"]):
                                                product_uom_id = each["uom_id"]
                                        if not bool(product_uom_id):
                                            raise Exception("Invalid product uom id detected!")

                                        for each in products_qty_to_pick:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if float(each["qty_to_pick"]) > float(_l_i["qty_done"]):
                                                    is_backorder = True
                                                if float(each["qty_to_pick"]) < float(_l_i["qty_done"]):
                                                    raise Exception(
                                                        "Picking quantity of a product is not possible to process!")
                                        if go:
                                            temp = dict()
                                            lot_serial_no_id = None
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = float(_l_i["qty_done"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            if "source" in _l_i and bool(_l_i["source"]):
                                                temp["location_id"] = int(_l_i["source"])
                                            else:
                                                temp["location_id"] = stock_picking[-1].location_id[0].id
                                            self.check_availability_with_source(temp["product_id"], temp["quantity"], temp["location_id"], temp["company_id"], lot_serial_no_id)
                                            temp["picking_id"] = stock_picking_id
                                            temp["lot_name"] = False
                                            temp["lot_id"] = False
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
                                            temp["result_package_id"] = False
                                            normal.append(temp)
                                    if bool(normal):
                                        revised_line_items.append(normal)

                    if go:
                        go = False
                        for i in range(len(stock_picking[-1].move_ids_without_package)):
                            stock_move = self.request.env["stock.move"].sudo().search(
                                [("id", "=", stock_picking[-1].move_ids_without_package[i].id)])
                            if bool(stock_move):
                                try:
                                    _reserved_line_items_to_remove = list()
                                    stock_move_lines = self.request.env["stock.move.line"].sudo().search(
                                        [("move_id", "=", int(stock_move[-1].id))])
                                    for _reserved_line in stock_move_lines:
                                        if bool(_reserved_line.id) and _reserved_line.id not in _reserved_line_items_to_remove:
                                            _reserved_line_items_to_remove.append(int(_reserved_line.id))
                                    if len(_reserved_line_items_to_remove) > 0:
                                        stock_move.sudo().write({"move_line_ids": [(2, _line_id, False) for _line_id in
                                                                                   _reserved_line_items_to_remove]})
                                except Exception as e:
                                    e.__str__()
                                    pass
                                _line_items_to_move = list()
                                qty_to_pick = 0
                                for revised_line in revised_line_items:
                                    for line in revised_line:
                                        if int(line["product_id"]) == int(stock_move[-1].product_id[0].id):
                                            _line_items_to_move.append(line)
                                            qty_to_pick += float(line["quantity"])
                                if qty_to_pick > 0:
                                    if float(stock_move[-1].product_qty) - float(
                                            stock_move[-1].quantity) >= qty_to_pick:
                                        stock_move.sudo().write(
                                            {"move_line_ids": [(0, False, _line) for _line in _line_items_to_move]})
                                        go = True
                        if go:
                            try:
                                stock_picking.button_validate()
                                if is_backorder:
                                    data = dict()
                                    data["backorder_confirmation_line_ids"] = [
                                        (0, False, {"picking_id": stock_picking_id, "to_backorder": True})]
                                    data["pick_ids"] = [(6, False, [stock_picking_id])]
                                    data["show_transfers"] = False
                                    backorder = self.request.env["stock.backorder.confirmation"].sudo().create(data)
                                    backorder.with_context(button_validate_picking_ids=backorder.pick_ids.ids).process()
                            except Exception as e:
                                if "lot" in e.__str__().lower() or "serial" in e.__str__().lower():
                                    raise Exception(e.__str__())
                                pass
                        else:
                            raise Exception("An unknown error occurred to pick!")
                else:
                    if bool(lot_name_not_exist):
                        raise Exception("Lot number(" + lot_name_not_exist + ") does not exist!")
                    elif bool(serial_name_not_exist):
                        raise Exception("Serial number(" + serial_name_not_exist + ") does not exist!")
                    elif bool(invalid_product_details):
                        raise Exception("Invalid product details supplied!")
            else:
                raise Exception("Line items not found for the given sale order!")
        else:
            raise Exception("Given sale order does not exist!")
        self.handle_middleware_open_picking(is_backorder, inputs, is_internal=True)
        return _res

    def get_country_code(self, country):
        code = None
        _country = self.request.env["res.country"].sudo().search([("name", "=", country)])
        if bool(_country):
            code = _country[-1].code
        return code

    def get_sale_order_location_n_customer_addresses(self, inputs):
        res = dict()
        so = None
        if "so_id" in inputs:
            so = self.request.env["sale.order"].sudo().search([("id", "=", int(inputs["so_id"]))])
        if bool(so):
            location_id = so[-1].warehouse_id[0].id
            warehouse = self.request.env["stock.warehouse"].sudo().search([("id", "=", int(location_id))])
            warehouse_name = warehouse[-1].name
            location = self.request.env["res.partner"].sudo().search([("id", "=", int(warehouse[-1].partner_id.id))])
            if bool(location):
                res["location_id"] = location_id
                temp = dict()
                if bool(location[-1].country_id) and bool(location[-1].state_id):
                    temp["wh_name"] = warehouse_name
                    temp["name"] = location[-1].name if bool(location[-1].name) else warehouse_name
                    temp["line1"] = location[-1].street
                    temp["city"] = location[-1].city
                    temp["state"] = location[-1].state_id[0].name
                    temp["zip"] = location[-1].zip
                    temp["country"] = location[-1].country_id[0].name
                    temp["country_code"] = self.get_country_code(location[-1].country_id[0].name)
                res["location_address"] = temp

                customer_id = so[-1].partner_id[0].id
                customer = self.request.env["res.partner"].sudo().search([("id", "=", int(customer_id))])
                if bool(customer):
                    res["customer_id"] = customer_id
                    temp = dict()
                    if bool(customer[-1].country_id) and bool(customer[-1].state_id):
                        temp["name"] = customer[-1].name
                        temp["line1"] = customer[-1].street
                        temp["city"] = customer[-1].city
                        temp["state"] = customer[-1].state_id[0].name
                        temp["zip"] = customer[-1].zip
                        temp["country"] = customer[-1].country_id[0].name
                        temp["country_code"] = self.get_country_code(customer[-1].country_id[0].name)
                    res["customer_address"] = temp
        else:
            raise Exception("Sale order not found!")
        return res

    def check_if_so_exists(self, inputs):
        res = dict()
        so = self.request.env["sale.order"].sudo().search([("name", "=", inputs["name"])])
        if bool(so):
            res["id"] = so[-1].id
        else:
            raise Exception("Sale order does not exist!")
        return res

    @staticmethod
    def is_expiration_valid(expiry_date):
        is_valid = False
        if bool(expiry_date):
            x_dt = datetime.datetime.strptime(str(expiry_date), "%Y-%m-%d %H:%M:%S")
            if x_dt > datetime.datetime.now():
                is_valid = True
        return is_valid

    def validate_stock_with_tracking(self, p_id, inputs):
        is_valid = False
        if "quantity" in inputs and float(inputs["quantity"]) > 0:
            quantity = float(inputs["quantity"])
            serial_name = inputs["serial"]
            lot_name = inputs["lot_number"]
            locations = Locations(company_id=self.company_id, user_id=self.user_id)
            internal_ids = locations.get_all_internal_location_ids(wh_name=inputs["warehouse_name"])
            _internal_loc_ids = "'" + "', '".join(internal_ids) + "'"
            if bool(serial_name):
                spl = self.request.env["stock.lot"].sudo().search([("name", "=", serial_name), ("product_id", "=", int(p_id))])
                if bool(spl):
                    spl_id = spl[-1].id
                    query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id = %d""" % (
                        int(self.company_id), int(p_id), _internal_loc_ids, int(spl_id))
                    if "source" in inputs and int(inputs["source"]) > 0:
                        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id = %d""" % (
                            int(self.company_id), int(p_id), int(inputs["source"]), int(spl_id))
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
                spl = self.request.env["stock.lot"].sudo().search([("name", "=", lot_name), ("product_id", "=", int(p_id))])
                if bool(spl):
                    spl_id = spl[-1].id
                    query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id = %d""" % (
                        int(self.company_id), int(p_id), _internal_loc_ids, int(spl_id))
                    if "source" in inputs and int(inputs["source"]) > 0:
                        query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id = %d""" % (
                            int(self.company_id), int(p_id), int(inputs["source"]), int(spl_id))
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
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id IS NULL""" % (
                    int(self.company_id), int(p_id), _internal_loc_ids)
                if "source" in inputs and int(inputs["source"]) > 0:
                    query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id = %d AND lot_id IS NULL""" % (
                        int(self.company_id), int(p_id), int(inputs["source"]))
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

    def get_current_stock(self, inputs):
        serial_name = inputs["serial"]
        lot_name = inputs["lot_number"]

        products = Products(company_id=self.company_id, user_id=self.user_id)
        p_id = products.get_product_name_id(p_code=inputs["product_code"])

        locations = Locations(company_id=self.company_id, user_id=self.user_id)
        internal_ids = locations.get_all_internal_location_ids()
        _internal_loc_ids = "'" + "', '".join(internal_ids) + "'"

        _quantity = 0
        if bool(serial_name):
            spl = self.request.env["stock.lot"].sudo().search([("name", "=", serial_name), ("product_id", "=", int(p_id))])
            if bool(spl):
                spl_id = spl[-1].id
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id = %d""" % (
                    int(self.company_id), int(p_id), _internal_loc_ids, int(spl_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    if bool(records[0]["quantity"]):
                        _quantity = records[0]["quantity"]
        elif bool(lot_name):
            spl = self.request.env["stock.lot"].sudo().search([("name", "=", lot_name), ("product_id", "=", int(p_id))])
            if bool(spl):
                spl_id = spl[-1].id
                query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id = %d""" % (
                    int(self.company_id), int(p_id), _internal_loc_ids, int(spl_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                if len(records) > 0:
                    if bool(records[0]["quantity"]):
                        _quantity = records[0]["quantity"]
        else:
            query = """SELECT COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(reserved_quantity), 0) AS reserved_qty FROM stock_quant WHERE company_id = %d AND product_id = %d AND location_id IN (%s) AND lot_id IS NULL""" % (
                int(self.company_id), int(p_id), _internal_loc_ids)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                if bool(records[0]["quantity"]):
                    _quantity = records[0]["quantity"]
        return _quantity

    def consider_open_picking_reserved_qty(self, res, inputs):
        _res = res
        if "calculate_open_picking" in inputs and bool(inputs["calculate_open_picking"]) and bool(res["is_ok"]) and "so_id" in inputs and int(inputs["so_id"]) > 0:
            ordered_qty = int(inputs["quantity"])
            query = """SELECT * FROM middleware_open_picking WHERE status = 'in_progress' AND so_id != %d""" % (
                int(inputs["so_id"]))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            reserved_qty = 0
            for _row in records:
                _data = _row["lots_serials_nots_quantities"]
                try:
                    _data = json.loads(_row["lots_serials_nots_quantities"])
                except Exception as e:
                    print(e.__str__())
                    pass
                if isinstance(_data, dict) and bool(_data):
                    if not bool(inputs["lot_number"]) and not bool(inputs["serial"]):
                        _index = _data["product_codes"].index(inputs["product_code"])
                        if _index > -1:
                            reserved_qty += int(_data["reserved_quantities"][_index])
                    elif bool(inputs["serial"]):
                        if inputs["serial"] in _data["serials"]:
                            _index = _data["serials"].index(inputs["serial"])
                            if _index > -1:
                                if _data["product_codes"][_index] == inputs["product_code"]:
                                    reserved_qty += int(_data["reserved_quantities"][_index])
                    elif bool(inputs["lot_number"]):
                        if inputs["lot_number"] in _data["lots"]:
                            _index = _data["lots"].index(inputs["lot_number"])
                            if _index > -1:
                                if _data["product_codes"][_index] == inputs["product_code"]:
                                    reserved_qty += int(_data["reserved_quantities"][_index])
            if reserved_qty > 0:
                current_stock = self.get_current_stock(inputs)
                if float(current_stock) - float(reserved_qty) < float(ordered_qty):
                    _res["is_ok"] = False
                    _res["product_tracking"] = None
                    _res["msg"] = "Quantity not available, reserved in open picking!"
        return _res

    def validate_picking_lot_serial(self, inputs):
        _res = dict()
        _res["is_ok"] = False
        _res["product_tracking"] = None
        _res["msg"] = "An unknown error occurred!"
        product = self.request.env["product.product"].sudo().search([("barcode", "=", inputs["product_code"])])
        if bool(product):
            product_id = product[-1].id
            lot_name = None
            if not bool(inputs["lot_number"]) and not bool(inputs["serial"]):
                if self.validate_stock_with_tracking(product_id, inputs):
                    _res["is_ok"] = True
                    _res["msg"] = None
                    _res["product_tracking"] = "none"
                else:
                    _res["msg"] = "The product code " + str(inputs["product_code"]) + " has no sufficient no-tracking stock!"
            else:
                if bool(inputs["serial"]):
                    lot_name = inputs["serial"]
                elif bool(inputs["lot_number"]):
                    lot_name = inputs["lot_number"]
                if bool(lot_name):
                    _conds = list()
                    _conds.append(("name", "=", lot_name))
                    _conds.append(("product_id", "=", int(product_id)))
                    _conds.append(("company_id", "=", self.company_id))
                    _found = self.request.env["stock.lot"].sudo().search(_conds)
                    if bool(_found) and float(_found[-1].product_qty) > 0:
                        if self.is_expiration_valid(_found[-1].expiration_date):
                            if self.validate_stock_with_tracking(product_id, inputs):
                                _res["is_ok"] = True
                                if bool(inputs["serial"]):
                                    _res["product_tracking"] = "serial"
                                else:
                                    _res["product_tracking"] = "lot"
                                _res["msg"] = None
                            else:
                                if bool(inputs["serial"]):
                                    _res["msg"] = "The product code " + str(
                                        inputs["product_code"]) + " has no requested serial-based stock!"
                                else:
                                    _res["msg"] = "The product code " + str(
                                        inputs["product_code"]) + " has no sufficient lot-based stock!"
                        else:
                            if bool(inputs["serial"]):
                                _res["msg"] = "The serial " + str(inputs["serial"]) + " has no valid expiration date!"
                            else:
                                _res["msg"] = "The lot " + str(inputs["lot_number"]) + " has no valid expiration date!"
                    else:
                        if bool(inputs["serial"]):
                            _res["msg"] = "The serial " + str(inputs["serial"]) + " does not exist or has no stock!"
                        else:
                            _res["msg"] = "The lot " + str(inputs["lot_number"]) + " does not exist or has no sufficient stock!"
        else:
            _res["msg"] = "The product code " + str(inputs["product_code"]) + " does not exist!"
        return self.consider_open_picking_reserved_qty(_res, inputs)

    def get_tracking(self, product_id, lot_serial):
        _tracking = None
        lot_id = None
        if bool(lot_serial):
            lot_id = lot_serial
            if not isinstance(lot_serial, (str, int)):
                lot_id = lot_serial[0].id
        if bool(lot_id):
            query = """SELECT * FROM stock_move_line WHERE quantity > 0 AND company_id = %d AND product_id = %d AND lot_id = %d GROUP BY id HAVING MAX(quantity) > 1 LIMIT 1""" % (
                int(self.company_id), int(product_id), int(lot_id))
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            if len(records) > 0:
                _tracking = "lot"
            else:
                _tracking = "serial"
        return _tracking

    def get_lot_n_expiry(self, product_id, *, lot_id=None, lot_name=None):
        if bool(lot_id):
            lot_name = None
            expiry_date = None
            if lot_id != "x":
                query = """SELECT name, expiration_date FROM stock_lot WHERE id = %d AND company_id = %d AND product_id = %d""" % (
                    int(lot_id), int(self.company_id), int(product_id))
                self.request.env.cr.execute(query)
                records = self.request.env.cr.dictfetchall()
                for _row in records:
                    lot_name = _row["name"]
                    expiry_date = _row["expiration_date"].strftime('%Y-%m-%d') if bool(
                        _row["expiration_date"]) and isinstance(_row["expiration_date"], datetime.datetime) else ""
            return lot_name, expiry_date
        if bool(lot_name):
            lot_id = None
            query = """SELECT id FROM stock_lot WHERE company_id = %d AND product_id = %d AND name = '%s'""" % (
                int(self.company_id), int(product_id), lot_name)
            self.request.env.cr.execute(query)
            records = self.request.env.cr.dictfetchall()
            for _row in records:
                lot_id = _row["id"]
            return lot_id

    def get_item_outbounds(self, _locations, _product, start_date, end_date, *, lot_serial=None):
        partners = Partners(company_id=self.company_id, user_id=self.user_id)
        users = Users(company_id=self.company_id, user_id=self.user_id)
        products = Products(company_id=self.company_id, user_id=self.user_id)
        locations = Locations(company_id=self.company_id, user_id=self.user_id)

        _tuple_list = list()
        query = """SELECT SML.company_id, SML.product_id, SM.origin, SM.warehouse_id, SO.partner_id, SOL.product_uom_qty AS ordered_qty, SML.quantity AS delivered_qty, SML.location_id AS location_id, SML.lot_id, SML.write_date, SML.write_uid FROM stock_move_line AS SML JOIN stock_move AS SM ON SML.move_id = SM.id JOIN sale_order_line AS SOL ON SM.sale_line_id = SOL.id JOIN sale_order AS SO ON SOL.order_id = SO.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.company_id = %d AND SML.product_id = %d AND SML.location_id IN (%s) AND SML.write_date BETWEEN '%s' AND '%s'"""
        _tuple_list.append("%/OUT/%")
        _tuple_list.append(int(self.company_id))
        _tuple_list.append(int(_product))
        _loc_ids = "'" + "', '".join(_locations) + "'"
        _tuple_list.append(_loc_ids)
        _tuple_list.append(start_date)
        _tuple_list.append(end_date)

        if bool(lot_serial):
            query += """ AND SML.lot_id = %d"""
            _tuple_list.append(int(lot_serial))
        else:
            query += """ AND SML.lot_id IS NULL"""
        query += """ ORDER BY SML.id DESC"""

        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        records = self.request.env.cr.dictfetchall()
        _history = list()
        for _rec in records:
            _temp = dict()
            _temp["erp"] = "Odoo"
            _temp["warehouse"] = locations.get_warehouse_name(_rec["warehouse_id"])
            _temp["product_name"] = products.get_product_name_id(p_id=_rec["product_id"])
            _temp["sales_order"] = _rec["origin"]
            _temp["customer"] = partners.get_partner_name(_rec["partner_id"], email=True)
            _temp["ordered_qty"] = int(_rec["ordered_qty"])
            _temp["picked_qty"] = int(_rec["delivered_qty"])
            _temp["location"] = locations.get_location_name_id(location_id=_rec["location_id"], stock_location=True)
            _temp["lot"] = None
            _temp["serial"] = None
            _temp["expiry_date"] = None
            _tracking = self.get_tracking(_rec["product_id"], _rec["lot_id"])
            if _tracking == "lot":
                (_temp["lot"], _temp["expiry_date"]) = self.get_lot_n_expiry(_rec["product_id"], lot_id=_rec["lot_id"])
            elif _tracking == "serial":
                (_temp["serial"], _temp["expiry_date"]) = self.get_lot_n_expiry(_rec["product_id"], lot_id=_rec["lot_id"])
            _temp["picked_by"] = users.get_user_name(_rec["write_uid"], email=True)
            _temp["picked_on"] = _rec["write_date"]
            _history.append(_temp)
        return _history

    def list_sales_orders_delivered(self, inputs):
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit

        so_name = None
        if "so_name" in inputs and bool(inputs["so_name"]):
            so_name = "%" + str(inputs["so_name"]).lower() + "%"

        invoice_no = None
        if "invoice_no" in inputs and bool(inputs["invoice_no"]):
            invoice_no = "%" + str(inputs["invoice_no"]).lower() + "%"

        warehouse_id = None
        if "warehouse_id" in inputs and bool(inputs["warehouse_id"]):
            warehouse_id = int(inputs["warehouse_id"])

        location_id = None
        so_ids = list()
        is_good_to_go = True
        if "location_id" in inputs and bool(inputs["location_id"]):
            location_id = int(inputs["location_id"])
            query = """SELECT sale_id FROM stock_picking WHERE state = 'done' AND sale_id IS NOT NULL and location_id = {}""".format(location_id)
            self.request.env.cr.execute(query)
            stock_picking_data = self.request.env.cr.dictfetchall()
            for each in stock_picking_data:
                so_ids.append(str(each["sale_id"]))
            if not bool(so_ids):
                is_good_to_go = False

        customer_id = None
        if "customer_id" in inputs and bool(inputs["customer_id"]):
            customer_id = int(inputs["customer_id"])

        date_order_start = None
        date_order_end = None
        if "date_order_start" in inputs and bool(inputs["date_order_start"]):
            date_order_start = inputs["date_order_start"]
            date_order_end = inputs["date_order_end"]

        _tuple_list = list()
        # query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN stock_picking AS SP1 ON SO.id = SP1.sale_id WHERE SO.company_id = %d AND SO.id NOT IN (SELECT SOL.order_id FROM sale_order_line AS SOL INNER JOIN product_product AS PP1 ON SOL.product_id = PP1.id WHERE (PP1.barcode = '') IS NOT FALSE AND SOL.order_id = SO.id AND SOL.product_id NOT IN (SELECT PP2.id FROM product_product AS PP2 INNER JOIN product_template AS PT ON PP2.product_tmpl_id = PT.id WHERE PP2.id = SOL.product_id AND PT.type != 'product')) AND SO.id NOT IN (SELECT SP2.sale_id FROM stock_picking AS SP2 WHERE SP2.state != 'done' AND SP2.sale_id = SO.id) AND ((SELECT COALESCE(SUM(SML1.quantity), 0) FROM stock_move_line AS SML1 WHERE SML1.state = 'done' AND SML1.reference LIKE '%s' AND SML1.picking_id IN (SELECT SP3.id FROM stock_picking AS SP3 WHERE SP3.sale_id = SO.id)) - (SELECT COALESCE(SUM(SML2.quantity), 0) FROM stock_move_line AS SML2 WHERE SML2.state = 'done' AND SML2.reference LIKE '%s' AND SML2.picking_id IN (SELECT SP4.id FROM stock_picking AS SP4 WHERE SP4.sale_id = SO.id))) > 0"""
        query = """SELECT SO.id, SO.name, SO.date_order FROM sale_order AS SO LEFT JOIN stock_picking AS SP1 ON SO.id = SP1.sale_id WHERE SO.company_id = %d AND SO.id NOT IN (SELECT SOL1.order_id FROM sale_order_line AS SOL1 INNER JOIN product_product AS PP1 ON SOL1.product_id = PP1.id WHERE (PP1.barcode = '') IS NOT FALSE AND SOL1.order_id = SO.id AND SOL1.product_id NOT IN (SELECT PP2.id FROM product_product AS PP2 INNER JOIN product_template AS PT ON PP2.product_tmpl_id = PT.id WHERE PP2.id = SOL1.product_id AND PT.type != 'product')) AND ((SELECT COALESCE(SUM(SOL2.product_uom_qty), 0) FROM sale_order_line AS SOL2 WHERE SOL2.order_id = SO.id) - (SELECT COALESCE(SUM(SML3.quantity), 0) FROM sale_order_line AS SOL3 LEFT JOIN stock_move_line AS SML3 ON SOL3.product_id = SML3.product_id WHERE SML3.state = 'done' AND SOL3.order_id = SO.id AND SML3.reference LIKE '%s' AND SML3.picking_id IN (SELECT SP.id FROM stock_picking AS SP WHERE SP.id = SML3.picking_id AND SP.sale_id = SO.id))) = 0 AND ((SELECT COALESCE(SUM(SML1.quantity), 0) FROM stock_move_line AS SML1 WHERE SML1.state = 'done' AND SML1.reference LIKE '%s' AND SML1.picking_id IN (SELECT SP3.id FROM stock_picking AS SP3 WHERE SP3.sale_id = SO.id)) - (SELECT COALESCE(SUM(SML2.quantity), 0) FROM stock_move_line AS SML2 WHERE SML2.state = 'done' AND SML2.reference LIKE '%s' AND SML2.picking_id IN (SELECT SP4.id FROM stock_picking AS SP4 WHERE SP4.sale_id = SO.id))) > 0"""
        _tuple_list.append(int(self.company_id))
        _tuple_list.append("%/OUT/%")
        _tuple_list.append("%/OUT/%")
        _tuple_list.append("%/IN/%")

        if bool(so_name):
            query += """ AND LOWER(SO.name) LIKE '%s'"""
            _tuple_list.append(so_name)
        if bool(invoice_no):
            query += """ AND SO.name IN (SELECT AM.invoice_origin FROM account_move AS AM WHERE LOWER(AM.name) LIKE '%s')"""
            _tuple_list.append(invoice_no)
        if bool(warehouse_id):
            query += """ AND SO.warehouse_id = %d"""
            _tuple_list.append(int(warehouse_id))
        if bool(location_id):
            if len(so_ids) > 0:
                _so_ids = "'" + "', '".join(so_ids) + "'"
                query += """ AND SO.id IN (%s)"""
                _tuple_list.append(_so_ids)
        if bool(customer_id):
            query += """ AND SO.partner_id = %d"""
            _tuple_list.append(int(customer_id))
        if bool(date_order_start):
            query += """ AND SO.date_order BETWEEN '%s' AND '%s'"""
            _tuple_list.append(str(date_order_start))
            _tuple_list.append(str(date_order_end))
        query += """ GROUP BY SO.id ORDER BY SO.id DESC LIMIT %d OFFSET %d"""
        _tuple_list.append(_limit)
        _tuple_list.append(_offset)
        query = query % tuple(_tuple_list)

        sale_orders = list()
        if is_good_to_go and bool(query):
            self.request.env.cr.execute(query)
            s_orders_data = self.request.env.cr.dictfetchall()
            for _so in s_orders_data:
                (location, customer) = self.get_location_n_customer_by_sale_order(_so["id"])
                temp = dict()
                temp["id"] = _so["id"]
                temp["name"] = _so["name"]
                temp["customer"] = customer
                temp["location"] = location
                temp["created_at"] = _so["date_order"]
                temp["invoice_ref"] = self.get_invoice_reference(_so["id"])
                sale_orders.append(temp)
        return sale_orders

    def get_delivered_qty(self, picking_name, record):
        already_returned = 0
        _lot_id = int(record.lot_id[0].id) if bool(record.lot_id) else False
        _origin = "Return of " + str(picking_name)
        _product_id = record.product_id[0].id

        return_pickings = self.request.env["stock.picking"].sudo().search([("origin", "=", _origin), ("state", "=", "done")])
        if bool(return_pickings):
            for return_picking in return_pickings:
                for each in return_picking.move_line_ids_without_package:
                    _conds = list()
                    _conds.append(("state", "=", "done"))
                    _conds.append(("id", "=", int(each.id)))
                    _conds.append(("product_id", "=", int(_product_id)))
                    _conds.append(("company_id", "=", int(self.company_id)))
                    _conds.append(("lot_id", "=", _lot_id))
                    stock_move_lines = self.request.env["stock.move.line"].sudo().search(_conds)
                    for _sm_line in stock_move_lines:
                        already_returned += int(_sm_line.quantity)
        return int(record.quantity) - int(already_returned)

    def get_lot_name(self, product_id, lot_id):
        _lot_name = None
        lot_data = self.request.env["stock.lot"].sudo().search([("id", "=", int(lot_id)), ("product_id", "=", int(product_id))])
        if bool(lot_data):
            _lot_name = lot_data[-1].name
        return _lot_name

    def is_returnable(self, sp_id, product_id, so_id):
        _returnable_lines = list()
        _picking_ids = list()
        query = """SELECT id FROM stock_picking WHERE sale_id = %d""" % (int(so_id))
        self.request.env.cr.execute(query)
        pickings = self.request.env.cr.dictfetchall()
        for each in pickings:
            _picking_ids.append(str(each["id"]))
        if bool(_picking_ids):
            _pick_ids = "'" + "', '".join(_picking_ids) + "'"

            _reference = "%/OUT/%"
            query = """SELECT SML.picking_id, SP.name AS picking_name, SP.origin, SML.product_id, SML.lot_id, COALESCE(SUM(SML.quantity), 0) AS quantity FROM stock_move_line AS SML LEFT JOIN stock_picking AS SP ON SML.picking_id = SP.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.picking_id IN (%s) GROUP BY SML.picking_id, SP.name, SP.origin, SML.product_id, SML.lot_id""" % (_reference, _pick_ids)
            if bool(product_id):
                query = """SELECT SML.picking_id, SP.name AS picking_name, SP.origin, SML.product_id, SML.lot_id, COALESCE(SUM(SML.quantity), 0) AS quantity FROM stock_move_line AS SML LEFT JOIN stock_picking AS SP ON SML.picking_id = SP.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.picking_id IN (%s) AND SML.product_id = %d GROUP BY SML.picking_id, SP.name, SP.origin, SML.product_id, SML.lot_id""" % (_reference, _pick_ids, int(product_id))
            self.request.env.cr.execute(query)
            _delivered_lines = self.request.env.cr.dictfetchall()

            _reference = "%/IN/%"
            query = """SELECT SML.picking_id, SP.name AS picking_name, SP.origin, SML.product_id, SML.lot_id, COALESCE(SUM(SML.quantity), 0) AS quantity FROM stock_move_line AS SML LEFT JOIN stock_picking AS SP ON SML.picking_id = SP.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.picking_id IN (%s) GROUP BY SML.picking_id, SP.name, SP.origin, SML.product_id, SML.lot_id""" % (_reference, _pick_ids)
            if bool(product_id):
                query = """SELECT SML.picking_id, SP.name AS picking_name, SP.origin, SML.product_id, SML.lot_id, COALESCE(SUM(SML.quantity), 0) AS quantity FROM stock_move_line AS SML LEFT JOIN stock_picking AS SP ON SML.picking_id = SP.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.picking_id IN (%s) AND SML.product_id = %d GROUP BY SML.picking_id, SP.name, SP.origin, SML.product_id, SML.lot_id""" % (_reference, _pick_ids, int(product_id))
            self.request.env.cr.execute(query)
            _returned_lines = self.request.env.cr.dictfetchall()

            for _d_line in _delivered_lines:
                if int(_d_line["picking_id"]) == int(sp_id):
                    _return_qty = 0
                    for _r_line in _returned_lines:
                        if _d_line["product_id"] == _r_line["product_id"] and _d_line["lot_id"] == _r_line["lot_id"] and _d_line["picking_name"] in _r_line["origin"]:
                            _return_qty += _r_line["quantity"]
                    if _return_qty > 0:
                        if _d_line["quantity"] - _return_qty > 0:
                            _temp = dict()
                            _temp["picking_id"] = sp_id
                            _temp["product_id"] = _d_line["product_id"]
                            _temp["lot_id"] = _d_line["lot_id"]
                            _temp["delivered_quantity"] = _d_line["quantity"] - _return_qty
                            _returnable_lines.append(_temp)
                    else:
                        _temp = dict()
                        _temp["picking_id"] = sp_id
                        _temp["product_id"] = _d_line["product_id"]
                        _temp["lot_id"] = _d_line["lot_id"]
                        _temp["delivered_quantity"] = _d_line["quantity"]
                        _returnable_lines.append(_temp)
        return _returnable_lines

    def get_line_items(self, sp_id, product_id, _returnable_lines):
        _line_items = list()
        if bool(_returnable_lines):
            products = Products(company_id=self.company_id, user_id=self.user_id)
            for _line in _returnable_lines:
                if bool(product_id):
                    if _line["product_id"] == product_id and _line["picking_id"] == sp_id:
                        _line_item = dict()
                        (_line_item["product_code"], _line_item["product_name"]) = products.get_barcode(p_id=_line["product_id"])
                        lot_no = None
                        serial_no = None
                        tracking = "none"
                        product_tracking = self.get_tracking(_line["product_id"], _line["lot_id"])
                        if bool(product_tracking):
                            if product_tracking == "serial":
                                serial_no = self.get_lot_name(_line["product_id"], _line["lot_id"])
                            else:
                                lot_no = self.get_lot_name(_line["product_id"], _line["lot_id"])
                            tracking = product_tracking
                        _line_item["lot_no"] = lot_no
                        _line_item["serial_no"] = serial_no
                        _line_item["product_tracking"] = tracking
                        _line_item["delivered_quantity"] = 1 if product_tracking == "serial" else int(_line["delivered_quantity"])
                        _line_items.append(_line_item)
                else:
                    if _line["picking_id"] == sp_id:
                        _line_item = dict()
                        (_line_item["product_code"], _line_item["product_name"]) = products.get_barcode(
                            p_id=_line["product_id"])
                        lot_no = None
                        serial_no = None
                        tracking = "none"
                        product_tracking = self.get_tracking(_line["product_id"], _line["lot_id"])
                        if bool(product_tracking):
                            if product_tracking == "serial":
                                serial_no = self.get_lot_name(_line["product_id"], _line["lot_id"])
                            else:
                                lot_no = self.get_lot_name(_line["product_id"], _line["lot_id"])
                            tracking = product_tracking
                        _line_item["lot_no"] = lot_no
                        _line_item["serial_no"] = serial_no
                        _line_item["product_tracking"] = tracking
                        _line_item["delivered_quantity"] = 1 if product_tracking == "serial" else int(
                            _line["delivered_quantity"])
                        _line_items.append(_line_item)
        return _line_items

    def get_returnable_sp(self, so_id, product_id, shipment_name, shipment_date_start, shipment_date_end):
        _returnable_sp_ids = list()
        _returnable_lines = list()
        _tuple_list = list()
        query = """SELECT SP.id, SP.name, SP.sale_id, SP.state, SP.origin FROM stock_picking AS SP WHERE SP.sale_id = %d"""
        _tuple_list.append(int(so_id))
        if bool(shipment_name):
            query += """ AND LOWER(SP.name) like '%s'"""
            _tuple_list.append(shipment_name)
        if bool(shipment_date_start) and bool(shipment_date_end):
            query += """ AND SP.date_done BETWEEN '%s' AND '%s'"""
            _tuple_list.append(str(shipment_date_start))
            _tuple_list.append(str(shipment_date_end))
        query = query % tuple(_tuple_list)
        self.request.env.cr.execute(query)
        so_data = self.request.env.cr.dictfetchall()

        _sp_ids = list()
        for each in so_data:
            if each["sale_id"] == so_id:
                if each["state"] == "done" and "Return of" not in each["origin"]:
                    _sp_ids.append(each["id"])
        if bool(_sp_ids):
            for _sp_id in _sp_ids:
                _returnables = self.is_returnable(_sp_id, product_id, so_id)
                if bool(_returnables):
                    _returnable_sp_ids.append(str(_sp_id))
                    for each in _returnables:
                        _returnable_lines.append(each)
        return _returnable_sp_ids, _returnable_lines

    def list_sales_order_shipments(self, inputs):
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit

        product_id = None
        if "product_id" in inputs and bool(inputs["product_id"]):
            product_id = int(inputs["product_id"])

        shipment_name = None
        if "shipment_name" in inputs and bool(inputs["shipment_name"]):
            shipment_name = "%" + str(inputs["shipment_name"]).lower() + "%"

        shipment_date_start = None
        shipment_date_end = None
        if "shipment_date_start" in inputs and bool(inputs["shipment_date_start"]):
            shipment_date_start = inputs["shipment_date_start"]
            shipment_date_end = inputs["shipment_date_end"]

        query = """SELECT * FROM stock_location WHERE active IS True AND return_location IS True AND company_id = %d""" % (
            int(self.company_id))
        self.request.env.cr.execute(query)
        stock_locations = self.request.env.cr.dictfetchall()

        _data = list()
        (_allowed_sp_ids, _returnable_lines) = self.get_returnable_sp(int(inputs["so_id"]), product_id, shipment_name, shipment_date_start, shipment_date_end)
        if bool(_allowed_sp_ids):
            _stock_p_ids = "'" + "', '".join(_allowed_sp_ids) + "'"
            _tuple_list = list()
            query = ""
            shipment_name_pattern = "%/out/%"
            if bool(product_id):
                query += """SELECT SP.* FROM stock_picking AS SP INNER JOIN stock_move AS SM ON SP.id = SM.picking_id WHERE SP.id IN (%s) AND SP.state = 'done' AND LOWER(SP.name) LIKE '%s' AND SM.id IN (SELECT SML.move_id FROM stock_move_line AS SML WHERE SML.move_id = SM.id AND SML.product_id = %d)"""
                _tuple_list.append(_stock_p_ids)
                _tuple_list.append(shipment_name_pattern)
                _tuple_list.append(product_id)

                if bool(shipment_name):
                    query += """ AND LOWER(SP.name) like '%s'"""
                    _tuple_list.append(shipment_name)

                if bool(shipment_date_start):
                    query += """ AND SP.date_done BETWEEN '%s' AND '%s'"""
                    _tuple_list.append(str(shipment_date_start))
                    _tuple_list.append(str(shipment_date_end))
            else:
                query += """SELECT SP.* FROM stock_picking AS SP WHERE SP.id IN (%s) AND SP.state = 'done' AND LOWER(SP.name) LIKE '%s'"""
                _tuple_list.append(_stock_p_ids)
                _tuple_list.append(shipment_name_pattern)

                if bool(shipment_name):
                    query += """ AND LOWER(SP.name) like '%s'"""
                    _tuple_list.append(shipment_name)

                if bool(shipment_date_start):
                    query += """ AND SP.date_done BETWEEN '%s' AND '%s'"""
                    _tuple_list.append(str(shipment_date_start))
                    _tuple_list.append(str(shipment_date_end))

            if bool(query):
                query += """ LIMIT %d OFFSET %d"""
                _tuple_list.append(_limit)
                _tuple_list.append(_offset)

                query = query % tuple(_tuple_list)
                self.request.env.cr.execute(query)
                stock_picking = self.request.env.cr.dictfetchall()
                for _each in stock_picking:
                    _temp = dict()
                    _temp["id"] = _each["id"]
                    _temp["name"] = _each["name"]
                    _temp["shipment_date"] = _each["date_done"]
                    _temp["line_items"] = self.get_line_items(_each["id"], product_id, _returnable_lines)

                    _return_locations = list()
                    for _loc in stock_locations:
                        if int(_loc["id"]) == int(_each["location_id"]):
                            _return_locations.append({"id": _loc["id"], "name": _loc["complete_name"]})
                    for _loc in stock_locations:
                        if int(_loc["id"]) != int(_each["location_id"]):
                            _return_locations.append({"id": _loc["id"], "name": _loc["complete_name"]})
                    _temp["return_locations"] = _return_locations
                    _data.append(_temp)
        return _data

    def check_if_any_other_shipments_open(self, so_name, line_items):
        _exceptions = list()
        so = self.request.env["sale.order"].sudo().search([("name", "=", str(so_name))])
        stock_picking_ids = list()
        view_stock_picking = so.action_view_delivery()
        if bool(view_stock_picking) and bool(view_stock_picking["res_id"]):
            stock_picking_ids.append(str(view_stock_picking["res_id"]))

        domain = view_stock_picking["domain"]
        try:
            domain = ast.literal_eval(view_stock_picking["domain"])
        except Exception as e:
            e.__str__()
            pass
        if bool(domain) and bool(domain[0]) and bool(domain[0][2]):
            for _id in domain[0][2]:
                if str(_id) not in stock_picking_ids:
                    stock_picking_ids.append(str(_id))
        if bool(stock_picking_ids):
            sp_ids = "'" + "', '".join(stock_picking_ids) + "'"
            for _line in line_items:
                products = Products(company_id=self.company_id, user_id=self.user_id)
                product_id = products.get_product_name_id(p_code=_line["product_code"], raise_exception=False)
                lot_id = None
                if bool(_line["lot_serial"]):
                    lot_serial = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(product_id))])
                    if bool(lot_serial):
                        lot_id = lot_serial[-1].id
                _tuple_list = list()
                query = """SELECT SML.quantity FROM stock_move_line AS SML WHERE SML.state NOT IN ('done', 'cancel') AND SML.product_id = %d AND SML.picking_id IN (%s)"""
                _tuple_list.append(int(product_id))
                _tuple_list.append(sp_ids)
                if bool(lot_id):
                    query += """ AND SML.lot_id = %d"""
                    _tuple_list.append(int(lot_id))
                query = query % tuple(_tuple_list)
                self.request.env.cr.execute(query)
                sm_data = self.request.env.cr.dictfetchall()
                if bool(sm_data):
                    _temp = dict()
                    _temp["product_code"] = _line["product_code"]
                    _temp["product_name"] = _line["product_name"]
                    _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                    _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                    _temp["return_quantity"] = int(_line["return_qty"])
                    _temp["message"] = "The same stock line has already been assigned in another transfer!"
                    _exceptions.append(_temp)
        return _exceptions

    def verify_return_lines(self, line_items, stock_picking):
        _exceptions = list()
        move_line_ids = stock_picking[-1].move_line_ids_without_package
        for _line in line_items:
            products = Products(company_id=self.company_id, user_id=self.user_id)
            product_id = products.get_product_name_id(p_code=_line["product_code"], raise_exception=False)
            if not bool(product_id):
                _temp = dict()
                _temp["product_code"] = _line["product_code"]
                _temp["product_name"] = _line["product_name"]
                _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                _temp["return_quantity"] = int(_line["return_qty"])
                _temp["message"] = "Product barcode like " + str(_line["product_code"]) + " does not exist!"
                _exceptions.append(_temp)
            elif bool(_line["lot_serial"]):
                lot_serial = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(product_id))])
                if not bool(lot_serial):
                    _temp = dict()
                    _temp["product_code"] = _line["product_code"]
                    _temp["product_name"] = _line["product_name"]
                    _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                    _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                    _temp["return_quantity"] = int(_line["return_qty"])
                    _temp["message"] = "Lot or serial like " + str(_line["lot_serial"]) + " does not exist!"
                    _exceptions.append(_temp)
                else:
                    lot_serial_id = lot_serial[-1].id
                    _move_id = False
                    for _id in move_line_ids:
                        move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(product_id)), ("lot_id", "=", int(lot_serial_id))])
                        if bool(move_line):
                            _move_id = move_line[-1].move_id
                    if bool(_move_id):
                        for _id in move_line_ids:
                            move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(product_id)), ("lot_id", "=", int(lot_serial_id))])
                            if bool(move_line):
                                delivered_qty = self.get_delivered_qty(stock_picking[-1].name, move_line[-1])
                                if delivered_qty < int(_line["return_qty"]):
                                    _temp = dict()
                                    _temp["product_code"] = _line["product_code"]
                                    _temp["product_name"] = _line["product_name"]
                                    _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                                    _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                                    _temp["return_quantity"] = int(_line["return_qty"])
                                    _temp["message"] = "Requested return quantity of the lot or serial(" + str(_line["lot_serial"]) + ") is not valid!"
                                    _exceptions.append(_temp)
                    else:
                        _temp = dict()
                        _temp["product_code"] = _line["product_code"]
                        _temp["product_name"] = _line["product_name"]
                        _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                        _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                        _temp["return_quantity"] = int(_line["return_qty"])
                        _temp["message"] = "Stock line not found for the lot or serial " + str(_line["lot_serial"])
                        _exceptions.append(_temp)
            else:
                _move_id = False
                for _id in move_line_ids:
                    move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(product_id)), ("lot_id", "=", False)])
                    if bool(move_line):
                        _move_id = move_line[-1].move_id
                if bool(_move_id):
                    for _id in move_line_ids:
                        move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(product_id)), ("lot_id", "=", False)])
                        if bool(move_line):
                            delivered_qty = self.get_delivered_qty(stock_picking[-1].name, move_line[-1])
                            if delivered_qty < int(_line["return_qty"]):
                                _temp = dict()
                                _temp["product_code"] = _line["product_code"]
                                _temp["product_name"] = _line["product_name"]
                                _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                                _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                                _temp["return_quantity"] = int(_line["return_qty"])
                                _temp["message"] = "Requested no-tracking return quantity of the product barcode(" + str(_line["product_code"]) + ") is not valid!"
                                _exceptions.append(_temp)
                else:
                    _temp = dict()
                    _temp["product_code"] = _line["product_code"]
                    _temp["product_name"] = _line["product_name"]
                    _temp["lot_number"] = _line["lot_serial"] if _line["tracking"] == "lot" else None
                    _temp["serial"] = _line["lot_serial"] if _line["tracking"] == "serial" else None
                    _temp["return_quantity"] = int(_line["return_qty"])
                    _temp["message"] = "Stock line not found for the no-tracking product barcode " + str(_line["product_code"])
                    _exceptions.append(_temp)
        if not bool(_exceptions):
            _exceptions = self.check_if_any_other_shipments_open(stock_picking[-1].origin, line_items)
        return _exceptions

    def return_out_shipment(self, inputs):
        _response = dict()
        if "shipment_id" not in inputs and not bool(inputs["shipment_id"]):
            raise Exception("Shipment ID not found in the request!")
        shipment_id = int(inputs["shipment_id"])

        if "return_location_id" not in inputs and not bool(inputs["return_location_id"]):
            raise Exception("Return location not found in the request!")
        return_location_id = int(inputs["return_location_id"])
        _conditions = list()
        _conditions.append(("id", "=", int(return_location_id)))
        _conditions.append(("company_id", "in", [self.company_id, False]))
        _conditions.append(("active", "=", True))
        _conditions.append(("return_location", "=", True))
        stock_location = self.request.env["stock.location"].sudo().search(_conditions)
        if not bool(stock_location):
            raise Exception("Requested return location is not valid or it does not exist!")

        line_items = inputs["items"]
        if not bool(line_items):
            raise Exception("Invalid request line items!")

        stock_picking = self.request.env["stock.picking"].sudo().search([("id", "=", int(shipment_id))])
        if not bool(stock_picking):
            raise Exception("Unable to find the requested shipment!")

        _exceptions = self.verify_return_lines(line_items, stock_picking)
        if bool(_exceptions):
            _response["exceptions"] = _exceptions
        else:
            move_line_ids = stock_picking[-1].move_line_ids_without_package
            stock_return_lines = list()
            stock_move_items = list()
            for _line in line_items:
                products = Products(company_id=self.company_id, user_id=self.user_id)
                _product_id = products.get_product_name_id(p_code=_line["product_code"], raise_exception=False)

                _move_id = False
                _lot_serial_id = False
                if bool(_line["lot_serial"]):
                    lot_serial = self.request.env["stock.lot"].sudo().search([("name", "=", _line["lot_serial"]), ("product_id", "=", int(_product_id))])
                    _lot_serial_id = lot_serial[-1].id
                    for _id in move_line_ids:
                        move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(_product_id)), ("lot_id", "=", int(_lot_serial_id))])
                        if bool(move_line):
                            _move_id = move_line[-1].move_id
                else:
                    for _id in move_line_ids:
                        move_line = self.request.env["stock.move.line"].sudo().search([("id", "=", int(_id)), ("product_id", "=", int(_product_id)), ("lot_id", "=", False)])
                        if bool(move_line):
                            _move_id = move_line[-1].move_id
                if bool(_move_id):
                    _tmp = dict()
                    _tmp["to_refund"] = True
                    _tmp["move_id"] = int(_move_id)
                    _tmp["product_id"] = int(_product_id)
                    _tmp["quantity"] = int(_line["return_qty"])
                    stock_return_lines.append(_tmp)

                    _temp = dict()
                    _temp["product_uom_id"] = 1
                    _temp["company_id"] = int(self.company_id)
                    _temp["product_id"] = int(_product_id)
                    _temp["lot_id"] = _lot_serial_id
                    _temp["quantity"] = int(_line["return_qty"])
                    stock_move_items.append(_temp)

            if bool(stock_return_lines):
                _return_data = dict()
                _return_data["location_id"] = int(return_location_id)
                _return_data["original_location_id"] = int(stock_picking[-1].location_id)
                _return_data["picking_id"] = int(shipment_id)
                _return_data["product_return_moves"] = [(0, False, _line) for _line in stock_return_lines]
                return_picking = self.request.env["stock.return.picking"].sudo().create(_return_data)
                data = return_picking.create_returns()
                new_return_picking_id = data["res_id"]
                new_stock_picking = self.request.env["stock.picking"].sudo().search([("id", "=", int(new_return_picking_id))])
                for i in range(len(new_stock_picking[-1].move_ids_without_package)):
                    new_move_id = new_stock_picking[-1].move_ids_without_package[i].id
                    stock_move = self.request.env["stock.move"].sudo().search([("id", "=", int(new_move_id))])

                    try:
                        _reserved_line_items_to_remove = list()
                        stock_move_lines = self.request.env["stock.move.line"].sudo().search([("move_id", "=", int(stock_move[-1].id))])
                        for _reserved_line in stock_move_lines:
                            if bool(_reserved_line.id) and _reserved_line.id not in _reserved_line_items_to_remove:
                                _reserved_line_items_to_remove.append(int(_reserved_line.id))
                        if len(_reserved_line_items_to_remove) > 0:
                            stock_move.sudo().write({"move_line_ids": [(2, _line_id, False) for _line_id in _reserved_line_items_to_remove]})
                    except Exception as e:
                        e.__str__()
                        pass

                    _move_lines = list()
                    for each_line in stock_move_items:
                        if int(each_line["product_id"]) == int(stock_move[-1].product_id[0].id):
                            _tmp = each_line
                            _tmp["picking_id"] = int(new_stock_picking[-1].id)
                            _tmp["location_id"] = int(new_stock_picking[-1].location_id.id)
                            _tmp["location_dest_id"] = int(new_stock_picking[-1].location_dest_id.id)
                            _move_lines.append(_tmp)
                    stock_move.sudo().write({"move_line_ids": [(0, False, _move_line) for _move_line in _move_lines]})

                try:
                    validation_res = new_stock_picking.button_validate()
                    if not isinstance(validation_res, bool) and validation_res["res_model"] == "expiry.picking.confirmation":
                        confirm_expiry = Form(self.request.env["expiry.picking.confirmation"].with_context(validation_res["context"])).save()
                        confirm_expiry.process()
                    if "return_note" in inputs and bool(inputs["return_note"]):
                        new_stock_picking.sudo().write({"note": str(inputs["return_note"])})
                    _response["stock_return"] = new_stock_picking[-1].name
                except Exception as e:
                    new_stock_picking.action_cancel()
                    raise Exception(e.__str__())
        return _response

    def get_invoice_reference(self, so_id):
        invoice_reference = ""
        so = self.request.env["sale.order"].sudo().search([("id", "=", int(so_id))])
        action_invoice = so.action_view_invoice()
        if bool(action_invoice) and "res_id" in action_invoice and bool(action_invoice["res_id"]):
            invoice = self.request.env["account.move"].sudo().search([("id", "=", int(action_invoice["res_id"]))])
            if bool(invoice):
                if bool(invoice[-1].name) and invoice[-1].name != "/":
                    invoice_reference = invoice[-1].name
        return invoice_reference if bool(invoice_reference) else None
