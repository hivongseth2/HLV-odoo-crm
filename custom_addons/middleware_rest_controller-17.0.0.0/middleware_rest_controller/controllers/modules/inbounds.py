# -*- coding: utf-8 -*-
import json
import ast
import datetime
from odoo import http
from .locations import Locations
from .partners import Partners
from .users import Users
from .products import Products


class Inbounds(http.Controller):
    def __init__(self, *, company_id=None, user_id=None, mode=None) -> None:
        self.company_id = company_id
        self.user_id = user_id
        self.mode = mode
        self.request = http.request
        pass

    def create_purchase_order(self, inputs):
        locations = Locations(company_id=self.company_id, user_id=self.user_id)
        picking_type_id = locations.get_warehouse_receipts_id(inputs["warehouse"])

        payload = {
            "partner_id": int(inputs["partner_id"]),
            "name": inputs["name"],
            "picking_type_id": picking_type_id,
            "order_line": [(0, False, product) for product in json.loads(inputs["order_line"])]
        }
        _res = dict()
        po = self.request.env["purchase.order"].sudo().create(payload)
        if bool(po):
            po.button_confirm()
            _res["purchase_order_id"] = po[-1].id
        else:
            raise Exception("Unable to create the purchase order!")
        return _res

    def po_receiving(self, inputs):
        _res = dict()
        po = self.request.env["purchase.order"].sudo().search([("id", "=", inputs["purchase_order_id"])])
        if bool(po):
            get_stock_picking = po.action_view_picking()
            if bool(get_stock_picking) and bool(get_stock_picking["res_id"]):
                stock_picking = self.request.env["stock.picking"].sudo().search(
                    [("id", "=", get_stock_picking["res_id"])])
                if bool(stock_picking):
                    if stock_picking[-1].state == "done":
                        raise Exception("Please check if already received!")
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
                    raise Exception("Please check if already received!")
            else:
                raise Exception("Unable to receive the order!")
        else:
            raise Exception("Purchase order not found!")
        return _res

    def get_location_n_vendor_by_purchase_order(self, po_id):
        location = None
        vendor = None
        po = self.request.env["purchase.order"].sudo().search([("id", "=", int(po_id))])
        if bool(po):
            location = po[-1].picking_type_id[0].warehouse_id[0].name
            location = location.split(":")[0]
            vendor = po[-1].partner_id[0].name
        return location, vendor

    def check_duplicate_po_line_items(self, inputs):
        has_duplicate = False
        query = """SELECT * FROM purchase_order_line WHERE order_id = %d""" % (int(inputs["po_id"]))
        self.request.env.cr.execute(query)
        line_items = self.request.env.cr.dictfetchall()
        _temp_line_item = list()
        for _li in line_items:
            if _li["product_id"] in _temp_line_item:
                has_duplicate = True
            _temp_line_item.append(_li["product_id"])
        return has_duplicate

    def list_purchase_orders(self, inputs):
        _limit = int(inputs["limit"])
        _offset = 0
        if "page" in inputs and int(inputs["page"]) > 0:
            _offset = (int(inputs["page"]) - 1) * _limit
        state = "'" + "', '".join(["purchase", "done"]) + "'"
        company_id = self.company_id
        query = """SELECT PO.* FROM purchase_order AS PO LEFT JOIN purchase_order_line AS POL ON PO.id = POL.order_id WHERE PO.id NOT IN (SELECT POL2.order_id FROM purchase_order_line AS POL2 INNER JOIN product_product AS PP ON POL2.product_id = PP.id WHERE (PP.barcode = '') IS NOT FALSE AND POL2.order_id = PO.id) AND POL.product_id NOT IN (SELECT PP2.id FROM product_product AS PP2 INNER JOIN product_template AS PT ON PP2.product_tmpl_id = PT.id WHERE PP2.id = POL.product_id AND PT.type != 'product') AND PO.state IN (%s) AND PO.company_id = %d AND (POL.product_uom_qty - POL.qty_received) > 0 GROUP BY PO.id ORDER BY PO.id DESC LIMIT %d OFFSET %d""" % (state, int(company_id), _limit, _offset)
        self.request.env.cr.execute(query)
        p_orders_data = self.request.env.cr.dictfetchall()
        purchase_orders = list()
        for _po in p_orders_data:
            (location, vendor) = self.get_location_n_vendor_by_purchase_order(_po["id"])
            temp = dict()
            temp["id"] = _po["id"]
            temp["duplicate_line_items"] = self.check_duplicate_po_line_items({"po_id": _po["id"]})
            temp["name"] = _po["name"]
            temp["vendor"] = vendor
            temp["location"] = location
            temp["created_on"] = _po["date_order"]
            purchase_orders.append(temp)
        return purchase_orders

    def list_line_items_by_purchase_order(self, inputs):
        list_line_items = list()
        po = self.request.env["purchase.order"].sudo().search([("id", "=", int(inputs["po_id"]))])
        if bool(po):
            order_line = po[-1].order_line
            line_item_ids = list()
            for line in order_line:
                line_item_ids.append(line[0].id)
            if bool(line_item_ids):
                for li_id in line_item_ids:
                    line_item = self.request.env["purchase.order.line"].sudo().search([("id", "=", int(li_id))])
                    product = line_item[-1].product_id
                    temp = dict()
                    temp["transaction_type"] = "purchase"
                    temp["product_id"] = product[0].id
                    temp["product_code"] = product[0].barcode if bool(product[0].barcode) else ""
                    temp["product_name"] = product[0].name
                    temp["product_demand_quantity"] = line_item[-1].product_uom_qty
                    temp["product_received_quantity"] = line_item[-1].qty_received
                    temp["product_qty_to_receive"] = line_item[-1].product_uom_qty - line_item[-1].qty_received
                    list_line_items.append(temp)
            else:
                raise Exception("Line items not found for the given purchase order!")
        else:
            raise Exception("Given purchase order does not exist!")
        return list_line_items

    @staticmethod
    def prepare_expiration_date(_dt):
        _expiry_date = False
        if bool(_dt):
            _tmp_dt = _dt.split(" ")[0]
            _expiry_date = _tmp_dt + " 00:00:00"
        return _expiry_date

    def receiving_by_purchase_order(self, inputs):
        _res = dict()
        is_backorder = False
        po = self.request.env["purchase.order"].sudo().search([("id", "=", int(inputs["po_id"]))])
        if bool(po):
            order_line = po[-1].order_line
            line_item_ids = list()
            for line in order_line:
                line_item_ids.append(line[0].id)
            if bool(line_item_ids):
                products_id = list()
                products_qty_to_receive = list()
                products_product_uom_id = list()
                for li_id in line_item_ids:
                    line_item = self.request.env["purchase.order.line"].sudo().search([("id", "=", int(li_id))])
                    product = line_item[-1].product_id
                    products_id.append(int(product[0].id))

                    product_variant = self.request.env["product.product"].sudo().search(
                        [("id", "=", int(product[0].id))])
                    product_template = self.request.env["product.template"].sudo().search(
                        [("id", "=", int(product_variant[-1].product_tmpl_id))])
                    products_product_uom_id.append(
                        {"product_id": str(product[0].id), "uom_id": product_template[-1].uom_id[0].id})
                    products_qty_to_receive.append({"product_id": str(product[0].id),
                                                    "qty_to_receive": line_item[-1].product_qty - line_item[
                                                        -1].qty_received})

                go = True
                products_to_this_receiving = list()
                invalid_product_details = False
                lot_name_exist = None
                serial_name_exist = None
                for l_item in inputs["line_items"]:
                    for key, val in l_item.items():
                        if key == "serials":
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_receiving:
                                            products_to_this_receiving.append(int(_l_i["product_id"]))
                                        _check_ls_name = None
                                        if "serial_name" in _l_i and bool(_l_i["serial_name"]):
                                            _check_ls_name = _l_i["serial_name"]
                                        if bool(_check_ls_name):
                                            lot_serial = self.request.env["stock.lot"].sudo().search(
                                                [("name", "=", _check_ls_name)])
                                            if bool(lot_serial):
                                                serial_name_exist = _check_ls_name
                                                go = False
                                    else:
                                        invalid_product_details = True
                                        go = False
                        elif key == "lots":
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_receiving:
                                            products_to_this_receiving.append(int(_l_i["product_id"]))
                                        _check_ls_name = None
                                        if "lot_name" in _l_i and bool(_l_i["lot_name"]):
                                            _check_ls_name = _l_i["lot_name"]
                                        if bool(_check_ls_name):
                                            lot_serial = self.request.env["stock.lot"].sudo().search(
                                                [("name", "=", _check_ls_name)])
                                            if bool(lot_serial):
                                                lot_name_exist = _check_ls_name
                                                # Ignoring LOT existence checking to support partial lot-based shipment
                                                # go = False
                                    else:
                                        invalid_product_details = True
                                        go = False
                        else:
                            for _l_i in val:
                                if go:
                                    if "product_id" in _l_i and int(_l_i["product_id"]) in products_id:
                                        if int(_l_i["product_id"]) not in products_to_this_receiving:
                                            products_to_this_receiving.append(int(_l_i["product_id"]))
                                    else:
                                        invalid_product_details = True
                                        go = False
                if go:
                    if len(products_id) > len(products_to_this_receiving):
                        is_backorder = True

                    stock_picking = None
                    stock_picking_id = None
                    stock_picking_ids = list()
                    view_stock_picking = po.action_view_picking()
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
                                if stock_picking[-1].state == "assigned":
                                    stock_picking_id = _id
                                    break

                    if not bool(stock_picking_id):
                        raise Exception("An unknown error occurred to receive!")

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
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = int(_l_i["qty_done"])
                                            temp["expiration_date"] = self.prepare_expiration_date(_l_i["expiry_date"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            if "destination" in _l_i and bool(_l_i["destination"]):
                                                temp["location_dest_id"] = int(_l_i["destination"])
                                            else:
                                                temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            temp["location_id"] = stock_picking[-1].location_id[0].id
                                            temp["picking_id"] = stock_picking_id
                                            temp["lot_name"] = _l_i["serial_name"]
                                            temp["lot_id"] = False
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
                                            serials.append(temp)

                                    if bool(serials):
                                        for each in products_qty_to_receive:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if int(each["qty_to_receive"]) > len(serials):
                                                    is_backorder = True
                                                if int(each["qty_to_receive"]) < len(serials):
                                                    raise Exception(
                                                        "Receiving quantity of a serial-based product is not possible to process!")
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
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = float(_l_i["qty_done"])
                                            temp["expiration_date"] = self.prepare_expiration_date(_l_i["expiry_date"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            if "destination" in _l_i and bool(_l_i["destination"]):
                                                temp["location_dest_id"] = int(_l_i["destination"])
                                            else:
                                                temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            temp["location_id"] = stock_picking[-1].location_id[0].id
                                            temp["picking_id"] = stock_picking_id
                                            temp["lot_name"] = _l_i["lot_name"]
                                            temp["lot_id"] = False
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
                                            lots.append(temp)
                                    if bool(lots):
                                        for each in products_qty_to_receive:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if float(each["qty_to_receive"]) > total_done_qty:
                                                    is_backorder = True
                                                if float(each["qty_to_receive"]) < total_done_qty:
                                                    raise Exception(
                                                        "Receiving quantity of a lot-based product is not possible to process!")
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

                                        for each in products_qty_to_receive:
                                            if int(each["product_id"]) == int(line_item_product_id):
                                                if float(each["qty_to_receive"]) > float(_l_i["qty_done"]):
                                                    is_backorder = True
                                                if float(each["qty_to_receive"]) < float(_l_i["qty_done"]):
                                                    raise Exception(
                                                        "Receiving quantity of a product is not possible to process!")
                                        if go:
                                            temp = dict()
                                            temp["product_uom_id"] = int(product_uom_id)
                                            temp["product_id"] = int(_l_i["product_id"])
                                            temp["quantity"] = float(_l_i["qty_done"])
                                            temp["expiration_date"] = self.prepare_expiration_date(_l_i["expiry_date"])
                                            temp["company_id"] = stock_picking[-1].company_id[0].id
                                            if "destination" in _l_i and bool(_l_i["destination"]):
                                                temp["location_dest_id"] = int(_l_i["destination"])
                                            else:
                                                temp["location_dest_id"] = stock_picking[-1].location_dest_id[0].id
                                            temp["location_id"] = stock_picking[-1].location_id[0].id
                                            temp["picking_id"] = stock_picking_id
                                            temp["lot_name"] = False
                                            temp["lot_id"] = False
                                            temp["move_id"] = False
                                            temp["owner_id"] = False
                                            temp["package_id"] = False
                                            temp["package_level_id"] = False
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
                                        stock_move.sudo().write({"move_line_ids": [(0, False, _line) for _line in _line_items_to_move]})
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
                                e.__str__()
                                pass
                        else:
                            raise Exception("An unknown error occurred to receive!")
                else:
                    if bool(lot_name_exist):
                        raise Exception("Lot number(" + lot_name_exist + ") already exists!")
                    elif bool(serial_name_exist):
                        raise Exception("Serial number(" + serial_name_exist + ") already exists!")
                    elif bool(invalid_product_details):
                        raise Exception("Invalid product details supplied!")
            else:
                raise Exception("Line items not found for the given purchase order!")
        else:
            raise Exception("Given purchase order does not exist!")
        return _res

    def get_country_code(self, country):
        code = None
        _country = self.request.env["res.country"].sudo().search([("name", "=", country)])
        if bool(_country):
            code = _country[-1].code
        return code

    def get_purchase_order_location_n_vendor_addresses(self, inputs):
        res = dict()
        po = None
        if "po_id" in inputs:
            po = self.request.env["purchase.order"].sudo().search([("id", "=", int(inputs["po_id"]))])
        if bool(po):
            location_id = po[-1].picking_type_id[0].warehouse_id[0].id
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
                    temp["line2"] = location[-1].street2
                    temp["line3"] = ""
                    temp["line4"] = ""
                    temp["city"] = location[-1].city
                    temp["state"] = location[-1].state_id[0].name
                    temp["zip"] = location[-1].zip
                    temp["country"] = location[-1].country_id[0].name
                    temp["country_code"] = self.get_country_code(location[-1].country_id[0].name)
                res["location_address"] = temp

                vendor_id = po[-1].partner_id[0].id
                vendor = self.request.env["res.partner"].sudo().search([("id", "=", int(vendor_id))])
                if bool(vendor):
                    res["vendor_id"] = vendor_id
                    temp = dict()
                    if bool(vendor[-1].country_id) and bool(vendor[-1].state_id):
                        temp["name"] = vendor[-1].name
                        temp["line1"] = vendor[-1].street
                        temp["line2"] = vendor[-1].street2
                        temp["line3"] = ""
                        temp["line4"] = ""
                        temp["city"] = vendor[-1].city
                        temp["state"] = vendor[-1].state_id[0].name
                        temp["zip"] = vendor[-1].zip
                        temp["country"] = vendor[-1].country_id[0].name
                        temp["country_code"] = self.get_country_code(vendor[-1].country_id[0].name)
                    res["vendor_address"] = temp
        else:
            raise Exception("Purchase order not found!")
        return res

    def check_if_po_exists(self, inputs):
        res = dict()
        po = self.request.env["purchase.order"].sudo().search([("name", "=", inputs["name"])])
        if bool(po):
            res["id"] = po[-1].id
        else:
            raise Exception("Purchase order does not exist!")
        return res

    @staticmethod
    def is_expiration_valid(sys_expiry_date, expiry_date):
        is_valid = False
        if bool(sys_expiry_date):
            system_expiry_dt = datetime.datetime.strptime(str(sys_expiry_date), "%Y-%m-%d %H:%M:%S")
            if system_expiry_dt > datetime.datetime.now():
                if bool(expiry_date):
                    input_expiry_dt = datetime.datetime.strptime(str(expiry_date), "%Y-%m-%d")
                    if system_expiry_dt == input_expiry_dt:
                        is_valid = True
        elif bool(expiry_date):
            input_expiry_dt = datetime.datetime.strptime(str(expiry_date), "%Y-%m-%d")
            if input_expiry_dt > datetime.datetime.now():
                is_valid = True
        return is_valid

    def check_last_received_as(self, po_id, p_id):
        _tracking = None
        po = self.request.env["purchase.order"].sudo().search([("id", "=", int(po_id))])
        view_stock_picking = po.action_view_picking()
        domain = view_stock_picking["domain"]
        try:
            domain = ast.literal_eval(view_stock_picking["domain"])
        except Exception as e:
            e.__str__()
            pass
        if bool(domain) and bool(domain[0]) and bool(domain[0][2]):
            stock_picking_ids = domain[0][2]
            if isinstance(stock_picking_ids, list) and bool(stock_picking_ids):
                stock_picking_ids.sort(reverse=True)
                stock_pickings = self.request.env["stock.picking"].sudo().search([("id", "in", stock_picking_ids)])
                if bool(stock_pickings):
                    for _each in stock_pickings:
                        if _each.state == "done":
                            move_line_ids = list()
                            for i in range(len(_each.move_line_ids_without_package)):
                                move_line_ids.append(_each.move_line_ids_without_package[i].id)
                            move_line_ids.sort(reverse=True)
                            _serial_found = False
                            for i in range(len(move_line_ids)):
                                stock_move_line = self.request.env["stock.move.line"].sudo().search(
                                    [("id", "=", move_line_ids[i])])
                                if bool(stock_move_line):
                                    if int(stock_move_line[-1].product_id[0].id) == int(p_id) and float(
                                            stock_move_line[-1].quantity) > 0:
                                        if not bool(_tracking):
                                            if bool(stock_move_line[-1].lot_id):
                                                if float(stock_move_line[-1].quantity) == 1:
                                                    _tracking = "serial"
                                                else:
                                                    _tracking = "lot"
                                            else:
                                                _tracking = "none"
        return _tracking

    def validate_receiving_lot_serial(self, inputs):
        _res = dict()
        _res["is_ok"] = False
        _res["product_tracking"] = None
        _res["msg"] = "An unknown error occurred!"
        product = self.request.env["product.product"].sudo().search([("barcode", "=", inputs["product_code"])])
        if bool(product):
            product_id = product[-1].id
            po_id = None
            try:
                po_id = int(inputs["po_id"])
            except Exception as e:
                e.__str__()
                pass
            exception_found = False
            # if bool(po_id):
            #     _last_received_as = self.check_last_received_as(po_id, product_id)
            #     if bool(_last_received_as):
            #         if _last_received_as == "lot":
            #             if bool(inputs["serial"]):
            #                 exception_found = True
            #                 _res["msg"] = "The product code " + str(inputs[
            #                                                             "product_code"]) + " was received as lot-based last time, so serials not allowed!"
            #             elif not bool(inputs["lot_number"]):
            #                 exception_found = True
            #                 _res["msg"] = "The product code " + str(
            #                     inputs["product_code"]) + " was received as lot-based last time, but no lot found!"
            #         elif _last_received_as == "serial":
            #             if not bool(inputs["serial"]):
            #                 exception_found = True
            #                 _res["msg"] = "The product code " + str(inputs[
            #                                                             "product_code"]) + " was received as serial-based last time, so serials required!"
            #         else:
            #             if bool(inputs["lot_number"]) or bool(inputs["serial"]):
            #                 exception_found = True
            #                 _res["msg"] = "The product code " + str(inputs[
            #                                                             "product_code"]) + " was received as no-tracking last time, so no lots or serials allowed!"
            if not bool(exception_found):
                if not bool(inputs["lot_number"]) and not bool(inputs["serial"]):
                    _res["is_ok"] = True
                    _res["msg"] = None
                    _res["product_tracking"] = "none"
                else:
                    if bool(inputs["serial"]):
                        _conds = list()
                        _conds.append(("name", "=", inputs["serial"]))
                        _conds.append(("company_id", "=", self.company_id))
                        _conds.append(("product_id", "=", int(product_id)))
                        _found = self.request.env["stock.lot"].sudo().search(_conds)
                        if bool(_found):
                            _res["msg"] = "The serial " + str(inputs["serial"]) + " is already in use!"
                        else:
                            if self.is_expiration_valid(None, inputs["expiry_date"]):
                                _res["is_ok"] = True
                                _res["product_tracking"] = "serial"
                                _res["msg"] = None
                            else:
                                _res["msg"] = "The serial " + str(
                                    inputs["serial"]) + " is valid but invalid expiration date(" + str(
                                    inputs["expiry_date"]) + ")!"
                    elif bool(inputs["lot_number"]):
                        # _conds = list()
                        # _conds.append(("name", "=", inputs["lot_number"]))
                        # _conds.append(("company_id", "=", self.company_id))
                        # _found = self.request.env["stock.lot"].sudo().search(_conds)
                        # if bool(_found):
                        #     if _found[-1].product_id[0].id != product_id:
                        #         _res["msg"] = "The lot " + str(
                        #             inputs["lot_number"]) + " is not associated with the product code " + str(
                        #             inputs["product_code"]) + "!"
                        #     else:
                        #         if self.is_expiration_valid(_found[-1].expiration_date, inputs["expiry_date"]):
                        #             _res["is_ok"] = True
                        #             _res["product_tracking"] = "lot"
                        #             _res["msg"] = None
                        #         else:
                        #             _res["msg"] = "The lot " + str(inputs[
                        #                                                "lot_number"]) + " is valid but it is already in use with an expiration date(" + str(
                        #                 _found[-1].expiration_date) + ")!"
                        # else:
                        #     if self.is_expiration_valid(None, inputs["expiry_date"]):
                        #         _res["is_ok"] = True
                        #         _res["product_tracking"] = "lot"
                        #         _res["msg"] = None
                        #     else:
                        #         _res["msg"] = "The lot " + str(
                        #             inputs["lot_number"]) + " is valid but invalid expiration date(" + str(
                        #             inputs["expiry_date"]) + ")!"

                        if self.is_expiration_valid(None, inputs["expiry_date"]):
                            _res["is_ok"] = True
                            _res["product_tracking"] = "lot"
                            _res["msg"] = None
                        else:
                            _res["msg"] = "The lot " + str(
                                inputs["lot_number"]) + " is valid but invalid expiration date(" + str(
                                inputs["expiry_date"]) + ")!"
                    else:
                        _res["is_ok"] = True
                        _res["msg"] = None
        else:
            if bool(inputs["is_source_erp"]):
                _res["msg"] = "The product code " + str(inputs["product_code"]) + " does not exist!"
            else:
                _res["is_ok"] = True
                _res["product_tracking"] = "none"
                if bool(inputs["lot_number"]):
                    _res["product_tracking"] = "lot"
                if bool(inputs["serial"]):
                    _res["product_tracking"] = "serial"
                _res["msg"] = None
        return _res

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

    def get_item_inbounds(self, _locations, _product, start_date, end_date, *, lot_serial=None):
        partners = Partners(company_id=self.company_id, user_id=self.user_id)
        users = Users(company_id=self.company_id, user_id=self.user_id)
        products = Products(company_id=self.company_id, user_id=self.user_id)
        locations = Locations(company_id=self.company_id, user_id=self.user_id)

        _tuple_list = list()
        query = """SELECT SML.company_id, SML.product_id, SM.origin, SM.warehouse_id, PO.partner_id, POL.product_qty AS ordered_qty, SML.quantity AS received_qty, SML.location_dest_id AS location_id, SML.lot_id, SML.write_date, SML.write_uid FROM stock_move_line AS SML JOIN stock_move AS SM ON SML.move_id = SM.id JOIN purchase_order_line AS POL ON SM.purchase_line_id = POL.id JOIN purchase_order AS PO ON POL.order_id = PO.id WHERE SML.state = 'done' AND SML.reference LIKE '%s' AND SML.company_id = %d AND SML.product_id = %d AND SML.location_dest_id IN (%s) AND SML.write_date BETWEEN '%s' AND '%s'"""
        _tuple_list.append("%/IN/%")
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
            _temp["purchase_order"] = _rec["origin"]
            _temp["vendor"] = partners.get_partner_name(_rec["partner_id"], email=True)
            _temp["ordered_qty"] = int(_rec["ordered_qty"])
            _temp["received_qty"] = int(_rec["received_qty"])
            _temp["location"] = locations.get_location_name_id(location_id=_rec["location_id"], stock_location=True)
            _temp["lot"] = None
            _temp["serial"] = None
            _temp["expiry_date"] = None
            _tracking = self.get_tracking(_rec["product_id"], _rec["lot_id"])
            if _tracking == "lot":
                (_temp["lot"], _temp["expiry_date"]) = self.get_lot_n_expiry(_rec["product_id"], lot_id=_rec["lot_id"])
            elif _tracking == "serial":
                (_temp["serial"], _temp["expiry_date"]) = self.get_lot_n_expiry(_rec["product_id"],
                                                                                lot_id=_rec["lot_id"])
            _temp["received_by"] = users.get_user_name(_rec["write_uid"], email=True)
            _temp["received_on"] = _rec["write_date"]
            _history.append(_temp)
        return _history

    def return_in_shipment(self, inputs):
        pass
