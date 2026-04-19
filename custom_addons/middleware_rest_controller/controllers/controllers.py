# -*- coding: utf-8 -*-
import sys
import os
import traceback
from odoo import http
from .modules.partners import Partners
from .modules.products import Products
from .modules.locations import Locations
from .modules.inbounds import Inbounds
from .modules.outbounds import Outbounds
from .modules.inventories import Inventories


class OdooRestController(http.Controller):
    api_ver = "/api/v1/"

    def __init__(self) -> None:
        self.mode = None
        self.company_id = None
        self.user_id = None
        self.response = None
        pass

    def response_handler(self, res=None):
        if bool(res) and isinstance(res, str):
            _res = dict()
            _res["status"] = "error"
            _res["message"] = res
            _res["data"] = dict()
            if self.mode == "dev":
                xception_type, xception, xception_tb = sys.exc_info()
                tb = traceback.TracebackException(xception_type, xception, xception_tb)
                for frame in tb.stack:
                    _obj = dict()
                    _obj["details"] = res.split("Odoo: ")[1]
                    _obj["file"] = "Odoo: " + os.path.split(frame.filename)[1]
                    _obj["module"] = frame.name
                    _obj["line"] = frame.lineno
                    _res["data"] = _obj
            self.response = _res
        else:
            _res = ""
            if bool(res):
                _res = res
            else:
                if isinstance(res, dict):
                    _res = dict()
                elif isinstance(res, list):
                    _res = list()

            self.response = {
                "status": "success",
                "message": "Request was successfully executed.",
                "data": _res
            }

    def is_authentic(self, params):
        if "mode" in params and bool(params["mode"]) and isinstance(params["mode"], str):
            self.mode = params["mode"].lower()
        else:
            self.mode = None

        _is_authentic = False
        _err_msg = None
        unames = list()
        unames.append(params["login"])
        unames.append(params["login"].upper())
        unames.append(params["login"].lower())
        for i in range(len(unames)):
            try:
                http.request.session.authenticate(params["db"], login=unames[i], password=params["password"])
                _is_authentic = True
                break
            except Exception as e:
                _err_msg = e.__str__() + "!"
                pass
        if _is_authentic:
            user = http.request.env["res.users"].sudo().search([("login", "ilike", params["login"])])
            if bool(user):
                if user[-1].login.lower() == params["login"].lower():
                    self.user_id = user[-1].id
                    self.company_id = user[-1].company_id[0].id

        if not bool(_is_authentic):
            self.response_handler(_err_msg)
        return _is_authentic

    @http.route(api_ver + "po-creation", type="json", auth="none", methods=["POST"], csrf=False)
    def po_creation(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.create_purchase_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "po-receiving", type="json", auth="none", methods=["POST"], csrf=False)
    def po_receiving(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.po_receiving(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "so-creation-with-delivery", type="json", auth="none", methods=["POST"], csrf=False)
    def so_creation_with_delivery(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.so_creation_with_delivery(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "so-creation", type="json", auth="none", methods=["POST"], csrf=False)
    def so_creation(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.create_sales_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "sale-order-delivery", type="json", auth="none", methods=["POST"], csrf=False)
    def sale_order_delivery(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.sale_order_delivery(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "create-warehouse", type="json", auth="none", methods=["POST"], csrf=False)
    def create_warehouse(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.create_warehouse(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "create-location", type="json", auth="none", methods=["POST"], csrf=False)
    def create_location(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.create_location(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-country-state-ids", type="json", auth="none", methods=["POST"], csrf=False)
    def get_country_state_ids(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_country_state_ids(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "create-partner", type="json", auth="none", methods=["POST"], csrf=False)
    def create_partner(self, **params):
        if self.is_authentic(params):
            try:
                partners = Partners(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = partners.create_partner(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "create-product", type="json", auth="none", methods=["POST"], csrf=False)
    def create_product(self, **params):
        if self.is_authentic(params):
            try:
                products = Products(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = products.product_creation(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "link-suppliers-to-product", type="json", auth="none", methods=["POST"], csrf=False)
    def link_suppliers_to_product(self, **params):
        if self.is_authentic(params):
            try:
                products = Products(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = products.link_suppliers_to_product(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-purchase-orders", type="json", auth="none", methods=["POST"], csrf=False)
    def list_purchase_orders(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.list_purchase_orders(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-sale-orders", type="json", auth="none", methods=["POST"], csrf=False)
    def list_sale_orders(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.list_sale_orders(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-line-items-by-purchase-order", type="json", auth="none", methods=["POST"], csrf=False)
    def list_line_items_by_purchase_order(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.list_line_items_by_purchase_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "receiving-by-purchase-order", type="json", auth="none", methods=["POST"], csrf=False)
    def receiving_by_purchase_order(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.receiving_by_purchase_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-line-items-by-sale-order", type="json", auth="none", methods=["POST"], csrf=False)
    def list_line_items_by_sale_order(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.list_line_items_by_sale_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "picking-by-sale-order", type="json", auth="none", methods=["POST"], csrf=False)
    def picking_by_sale_order(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.picking_by_sale_order(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-purchase-order-location-n-vendor-addresses", type="json", auth="none", methods=["POST"],
                csrf=False)
    def get_purchase_order_location_n_vendor_addresses(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.get_purchase_order_location_n_vendor_addresses(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-sale-order-location-n-customer-addresses", type="json", auth="none", methods=["POST"],
                csrf=False)
    def get_sale_order_location_n_customer_addresses(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.get_sale_order_location_n_customer_addresses(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-if-partner-exists", type="json", auth="none", methods=["POST"], csrf=False)
    def check_if_partner_exists(self, **params):
        if self.is_authentic(params):
            try:
                partners = Partners(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = partners.check_if_partner_exists(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-if-location-exists", type="json", auth="none", methods=["POST"], csrf=False)
    def check_if_location_exists(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.check_if_location_exists(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-warehouse-code", type="json", auth="none", methods=["POST"], csrf=False)
    def check_warehouse_code(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.check_warehouse_code(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-if-po-exists", type="json", auth="none", methods=["POST"], csrf=False)
    def check_if_po_exists(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.check_if_po_exists(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-if-so-exists", type="json", auth="none", methods=["POST"], csrf=False)
    def check_if_so_exists(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.check_if_so_exists(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-if-product-exists", type="json", auth="none", methods=["POST"], csrf=False)
    def check_if_product_exists(self, **params):
        if self.is_authentic(params):
            try:
                products = Products(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = products.check_if_product_exists(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "validate-receiving-lot-serial", type="json", auth="none", methods=["POST"], csrf=False)
    def validate_receiving_lot_serial(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.validate_receiving_lot_serial(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "validate-picking-lot-serial", type="json", auth="none", methods=["POST"], csrf=False)
    def validate_picking_lot_serial(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.validate_picking_lot_serial(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "check-duplicate-line-items", type="json", auth="none", methods=["POST"], csrf=False)
    def check_duplicate_line_items(self, **params):
        if self.is_authentic(params):
            try:
                has_duplicate = False
                if "po_id" in params["inputs"]:
                    inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                    has_duplicate = inbounds.check_duplicate_po_line_items(params["inputs"])
                elif "so_id" in params["inputs"]:
                    outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                    has_duplicate = outbounds.check_duplicate_so_line_items(params["inputs"])
                self.response_handler({"duplicate_line_items": has_duplicate})
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-suggestive-lots", type="json", auth="none", methods=["POST"], csrf=False)
    def list_suggestive_lots(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.list_suggestive_lots(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-all-lots", type="json", auth="none", methods=["POST"], csrf=False)
    def list_all_lots(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.list_all_lots(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-active-products-list", type="json", auth="none", methods=["POST"], csrf=False)
    def get_active_products_list(self, **params):
        if self.is_authentic(params):
            try:
                products = Products(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = products.get_active_products_list(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-locations-list", type="json", auth="none", methods=["POST"], csrf=False)
    def get_locations_list(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_locations_list()
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-receiving-destinations", type="json", auth="none", methods=["POST"], csrf=False)
    def get_receiving_destinations(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_receiving_destination_locations(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-picking-sources", type="json", auth="none", methods=["POST"], csrf=False)
    def get_picking_sources(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_picking_source_locations(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-receiving-destination-name", type="json", auth="none", methods=["POST"], csrf=False)
    def get_receiving_destination_name(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_receiving_destination_location_name(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-picking-source-name", type="json", auth="none", methods=["POST"], csrf=False)
    def get_picking_source_name(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_picking_source_location_name(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-receiving-destination-id", type="json", auth="none", methods=["POST"], csrf=False)
    def get_receiving_destination_id(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_receiving_destination_location_id(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-picking-source-id", type="json", auth="none", methods=["POST"], csrf=False)
    def get_picking_source_id(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_picking_source_location_id(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "item-wise-inventory", type="json", auth="none", methods=["POST"], csrf=False)
    def item_wise_inventory(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.get_item_wise_inventory(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "item-inventory-by-lots", type="json", auth="none", methods=["POST"], csrf=False)
    def item_inventory_by_lots(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.get_item_inventory_by_lots(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "item-inventory-by-locations", type="json", auth="none", methods=["POST"], csrf=False)
    def item_inventory_by_locations(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.get_item_inventory_by_locations(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "handle-inventory-audit-session", type="json", auth="none", methods=["POST"], csrf=False)
    def handle_inventory_audit_session(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.handle_inventory_audit_session(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-inventory-count", type="json", auth="none", methods=["POST"], csrf=False)
    def get_inventory_count(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.get_item_inventory_count(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-location-by-scan", type="json", auth="none", methods=["POST"], csrf=False)
    def get_location_by_scan(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_location_by_scan(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-product-by-scan", type="json", auth="none", methods=["POST"], csrf=False)
    def get_product_by_scan(self, **params):
        if self.is_authentic(params):
            try:
                products = Products(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = products.get_product_by_scan(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-instant-inventory", type="json", auth="none", methods=["POST"], csrf=False)
    def get_instant_inventory(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.get_item_instant_inventory_details(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "handle-open-picking", type="json", auth="none", methods=["POST"], csrf=False)
    def handle_open_picking(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.handle_middleware_open_picking(True, params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-warehouse-by-stock-location", type="json", auth="none", methods=["POST"], csrf=False)
    def get_warehouse_by_stock_location(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_warehouse_by_stock_location(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "get-stock-locations", type="json", auth="none", methods=["POST"], csrf=False)
    def get_stock_locations(self, **params):
        if self.is_authentic(params):
            try:
                locations = Locations(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = locations.get_stock_locations(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "internal-transfer", type="json", auth="none", methods=["POST"], csrf=False)
    def internal_transfer(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.internal_transfer(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "stock-quarantine", type="json", auth="none", methods=["POST"], csrf=False)
    def stock_quarantine(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.stock_quarantine(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "return-in-shipment", type="json", auth="none", methods=["POST"], csrf=False)
    def return_in_shipment(self, **params):
        if self.is_authentic(params):
            try:
                inbounds = Inbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inbounds.return_in_shipment(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "return-out-shipment", type="json", auth="none", methods=["POST"], csrf=False)
    def return_out_shipment(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.return_out_shipment(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "validate-transfer-lot-serial", type="json", auth="none", methods=["POST"], csrf=False)
    def validate_transfer_lot_serial(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.validate_transfer_lot_serial(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-sales-orders-delivered", type="json", auth="none", methods=["POST"], csrf=False)
    def list_sales_orders_delivered(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.list_sales_orders_delivered(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-sales-order-shipments", type="json", auth="none", methods=["POST"], csrf=False)
    def list_sales_order_shipments(self, **params):
        if self.is_authentic(params):
            try:
                outbounds = Outbounds(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = outbounds.list_sales_order_shipments(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-customers", type="json", auth="none", methods=["POST"], csrf=False)
    def list_customers(self, **params):
        if self.is_authentic(params):
            try:
                partners = Partners(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = partners.list_customers(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "validate-multi-scan-lot-serial", type="json", auth="none", methods=["POST"], csrf=False)
    def validate_multi_scan_lot_serial(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.validate_multi_scan_lot_serial(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "list-suppliers", type="json", auth="none", methods=["POST"], csrf=False)
    def list_suppliers(self, **params):
        if self.is_authentic(params):
            try:
                partners = Partners(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = partners.list_suppliers(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response

    @http.route(api_ver + "finder-search", type="json", auth="none", methods=["POST"], csrf=False)
    def finder_search(self, **params):
        if self.is_authentic(params):
            try:
                inventories = Inventories(company_id=self.company_id, user_id=self.user_id, mode=self.mode)
                res = inventories.finder_search(params["inputs"])
                self.response_handler(res)
            except Exception as e:
                self.response_handler("Odoo: " + e.__str__())
        return self.response
