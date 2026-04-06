# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Main API Controller for Rest Api Pragmatic."""

import logging

from odoo import http
from odoo.http import request

from . import pinguin_controller
from ..lib import pinguin

_logger = logging.getLogger(__name__)

API_ENDPOINT = "/api"
API_ENDPOINT_V1 = "/v1"


class ApiV1Controller(http.Controller):
    """Implements the REST API V1 endpoint.
    
    Methods:
        CRUD Methods:
        - POST     .../<model>               -> CreateOne
        - PUT      .../<model>/<id>          -> UpdateOne
        - GET      .../<model>               -> ReadMulti
        - GET      .../<model>/<id>          -> ReadOne
        - DELETE   .../<model>/<id>          -> UnlinkOne
        
        Auxiliary Methods:
        - PATCH    .../<model>/<id>/<method> -> Call Method on Singleton Record
        - PATCH    .../<model>/<method>      -> Call Method on RecordSet
        - GET      .../report/pdf/<report_external_id>  -> Get Report as PDF
        - GET      .../report/html/<report_external_id> -> Get Report as HTML
    """
    
    _api_endpoint = API_ENDPOINT + API_ENDPOINT_V1
    _api_endpoint = _api_endpoint + "/<namespace>"
    _api_endpoint_model = _api_endpoint + "/<model>"
    _api_endpoint_model_id = _api_endpoint + "/<model>/<int:id>"
    _api_endpoint_model_id_method = _api_endpoint + "/<model>/<int:id>/call/<method_name>"
    _api_endpoint_model_method = _api_endpoint + "/<model>/call/<method_name>"
    _api_endpoint_model_method_ids = _api_endpoint + "/<model>/call/<method_name>/<ids>"
    _api_report_docids = (_api_endpoint + 
                         "/report/<any(pdf, html):converter>/<report_external_id>/<docids>")
    
    # #################
    # # CRUD Methods ##
    # #################
    
    # CreateOne
    @http.route(
        _api_endpoint_model, methods=["POST"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def create_one__POST(self, namespace, model):
        """Create a new record."""
        data = request.get_json_data()
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(
            "api_create", conf["method"], main=True, raise_exception=True
        )
        return pinguin_controller.wrap__resource__create_one(
            modelname=model,
            context=conf["context"],
            data=data,
            success_code=pinguin.CODE__created,
            out_fields=conf["out_fields_read_one"],
        )
    
    # ReadMulti
    @http.route(
        _api_endpoint_model, methods=["GET"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def read_multi__GET(self, namespace, model, **kw):
        """Read multiple records."""
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(
            "api_read", conf["method"], main=True, raise_exception=True
        )
        return pinguin_controller.wrap__resource__read_all(
            modelname=model,
            success_code=pinguin.CODE__success,
            out_fields=conf["out_fields_read_multi"],
        )
    
    # ReadOne
    @http.route(
        _api_endpoint_model_id, methods=["GET"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def read_one__GET(self, namespace, model, id, **kw):
        """Read one record."""
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(
            "api_read", conf["method"], main=True, raise_exception=True
        )
        return pinguin_controller.wrap__resource__read_one(
            modelname=model,
            id=id,
            success_code=pinguin.CODE__success,
            out_fields=conf["out_fields_read_one"],
        )
    
    # UpdateOne
    @http.route(
        _api_endpoint_model_id, methods=["PUT"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def update_one__PUT(self, namespace, model, id):
        """Update one record."""
        data = request.get_json_data()
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(
            "api_update", conf["method"], main=True, raise_exception=True
        )
        return pinguin_controller.wrap__resource__update_one(
            modelname=model,
            id=id,
            success_code=pinguin.CODE__ok_no_content,
            data=data
        )
    
    # UnlinkOne
    @http.route(
        _api_endpoint_model_id, methods=["DELETE"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def unlink_one__DELETE(self, namespace, model, id):
        """Delete one record."""
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(
            "api_delete", conf["method"], main=True, raise_exception=True
        )
        return pinguin_controller.wrap__resource__unlink_one(
            modelname=model,
            id=id,
            success_code=pinguin.CODE__ok_no_content
        )
    
    # ######################
    # # Auxiliary Methods ##
    # ######################
    
    # Call Method on Singleton Record
    @http.route(
        _api_endpoint_model_id_method,
        methods=["PATCH"],
        type="http",
        auth="none",
        csrf=False,
    )
    @pinguin_controller.route
    def call_method_one__PATCH(self, namespace, model, id, method_name):
        """Call method on one record."""
        method_params = request.get_json_data()
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(method=method_name, methods_conf=conf["method"], raise_exception=True)
        return pinguin_controller.wrap__resource__call_method(
            modelname=model,
            ids=[id],
            method=method_name,
            method_params=method_params,
            success_code=pinguin.CODE__success,
        )
    
    # Call Method on RecordSet
    @http.route(
        [_api_endpoint_model_method, _api_endpoint_model_method_ids],
        methods=["PATCH"],
        type="http",
        auth="none",
        csrf=False,
    )
    @pinguin_controller.route
    def call_method_multi__PATCH(self, namespace, model, method_name, ids=None):
        """Call method on multiple records."""
        method_params = request.get_json_data()
        conf = pinguin_controller.get_model_api_access(namespace, model)
        pinguin_controller.method_is_allowed(method=method_name, methods_conf=conf["method"], raise_exception=True)
        ids = ids and ids.split(",") or []
        ids = [int(i) for i in ids]
        return pinguin_controller.wrap__resource__call_method(
            modelname=model,
            ids=ids,
            method=method_name,
            method_params=method_params,
            success_code=pinguin.CODE__success,
        )
    
    # Get Report
    @http.route(
        _api_report_docids, methods=["GET"], type="http", auth="none", csrf=False
    )
    @pinguin_controller.route
    def report__GET(self, converter, namespace, report_external_id, docids):
        """Get report in PDF or HTML format."""
        return pinguin_controller.wrap__resource__get_report(
            namespace=namespace,
            report_external_id=report_external_id,
            docids=docids,
            converter=converter,
            success_code=pinguin.CODE__success,
        )
