# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Controller utilities for Rest Api Pragmatic.

This module implements controller-specific functions for the REST interface
concerning authentication, validation, and request/response handling.
"""

import functools
import traceback

import werkzeug.wrappers
from odoo import api
from odoo.http import request
from odoo.modules.registry import Registry
from odoo.addons.web.controllers.report import ReportController

from ..lib import pinguin

try:
    import simplejson as json
except ImportError:
    import json


def get_namespace_by_name_from_users_namespaces(user, namespace_name, raise_exception=False):
    """Check and get namespace from user's namespaces by name.
    
    Args:
        user: The user record.
        namespace_name (str): The name of namespace.
        raise_exception (bool): Raise exception if namespace does not exist.
        
    Returns:
        api.namespace record: Found namespace record.
        
    Raises:
        werkzeug.exceptions.HTTPException: If namespace not found or not authorized.
    """
    namespace = request.env["api.namespace"].search([("name", "=", namespace_name)])
    
    if not namespace.exists() and raise_exception:
        raise werkzeug.exceptions.HTTPException(
            response=pinguin.error_response(*pinguin.CODE__obj_not_found)
        )
    
    if namespace not in user.namespace_ids and raise_exception:
        err = list(pinguin.CODE__user_no_perm)
        err[2] = "The requested namespace (integration) is not authorized."
        raise werkzeug.exceptions.HTTPException(response=pinguin.error_response(*err))
    
    return namespace


def create_log_record(**kwargs):
    """Create log record for API request/response."""
    test_mode = request.registry.test_cr
    # Don't create log in test mode as it's impossible in case of error
    if not test_mode:
        with Registry(request.session.db).cursor() as cr:
            env = api.Environment(cr, request.session.uid, {})
            _create_log_record(env, **kwargs)


def _create_log_record(env, namespace_id=None, namespace_log_request=None,
                      namespace_log_response=None, user_id=None, 
                      user_request=None, user_response=None):
    """Create log for request.
    
    Args:
        env: Odoo environment.
        namespace_id (int): Requested namespace id.
        namespace_log_request (str): Request save option.
        namespace_log_response (str): Response save option.
        user_id (int): User id which requests.
        user_request: Wrapped werkzeug Request object.
        user_response: Wrapped werkzeug Response object.
        
    Returns:
        api.log record: New log record.
    """
    log_data = {
        "namespace_id": namespace_id,
        "request": f"{user_request.url} | {user_request.method} | {user_response.status_code}",
        "request_data": None,
        "response_data": None,
    }
    
    if namespace_log_request == "debug":
        log_data["request_data"] = str(user_request.__dict__)
    elif namespace_log_request == "info":
        log_data["request_data"] = str(user_request.__dict__)
        # Remove sensitive data
        for k in ["form", "files"]:
            try:
                del log_data["request_data"][k]
            except (KeyError, TypeError):
                pass
    
    if namespace_log_response == "debug":
        try:
            log_data["response_data"] = str(user_response.json)
        except Exception:
            log_data["response_data"] = "Could not serialize response data."
            log_data["response_data"] = str(user_response.__dict__)
    
    elif namespace_log_response == "error" and user_response.status_code > 400:
        log_data["response_data"] = str(user_response.__dict__)
    
    return env["api.log"].create(log_data)


def route(controller_method):
    """Set up the environment for route handlers.
    
    Patches the framework and additionally authenticates
    the API token and infers database through a different mechanism.
    
    Args:
        controller_method: The controller method to wrap.
        
    Returns:
        wrapped method
    """
    @functools.wraps(controller_method)
    def controller_method_wrapper(*iargs, **ikwargs):
        auth_header = pinguin.get_auth_header(
            request.httprequest.headers, raise_exception=True
        )
        db_name, user_token = pinguin.get_data_from_auth_header(auth_header)
        
        # Setup database if specified
        #if db_name:
        #    pinguin.setup_db(request.httprequest, db_name)
        
        # Authenticate user
        authenticated_user = pinguin.authenticate_token_for_user(user_token)
        namespace = get_namespace_by_name_from_users_namespaces(
            authenticated_user, ikwargs["namespace"], raise_exception=True
        )
        
        data_for_log = {
            "namespace_id": namespace.id,
            "namespace_log_request": namespace.log_request,
            "namespace_log_response": namespace.log_response,
            "user_id": authenticated_user.id,
            "user_request": None,
            "user_response": None,
        }
        
        try:
            response = controller_method(*iargs, **ikwargs)
        except werkzeug.exceptions.HTTPException as e:
            response = e.response
        except Exception as e:
            traceback.print_exc()
            if hasattr(e, "error") and isinstance(e.error, Exception):
                e = e.error
            response = pinguin.error_response(
                status=500,
                error=type(e).__name__,
                error_descrip=e.name if hasattr(e, "name") else str(e),
            )
        
        data_for_log.update({
            "user_request": request.httprequest,
            "user_response": response
        })
        create_log_record(**data_for_log)
        
        return response
    
    return controller_method_wrapper


def get_model_api_access(namespace, model):
    """Get the model configuration and validate the requested namespace.
    
    Args:
        namespace (str): The namespace to validate against.
        model (str): The model for which we retrieve the configuration.
        
    Returns:
        dict: Model API configuration for this namespace.
        
    Raises:
        werkzeug.exceptions.HTTPException: If no access configuration found.
    """
    cr, uid = request.cr, request.session.uid
    api_access = (
        request.env(cr, uid)["api.access"]
        .sudo()
        .search([("model_id", "=", model), ("namespace_id.name", "=", namespace)])
    )
    
    if not api_access.exists():
        raise werkzeug.exceptions.HTTPException(
            response=pinguin.error_response(*pinguin.CODE__canned_ctx_not_found)
        )
    
    res = {
        "context": {},
        "out_fields_read_multi": (),
        "out_fields_read_one": (),
        "out_fields_create_one": (),
        "method": {
            "public": {"mode": "", "whitelist": []},
            "private": {"mode": "", "whitelist": []},
            "main": {"mode": "", "whitelist": []},
        },
    }
    
    # Infer public method mode
    if api_access.api_public_methods and api_access.public_methods:
        res["method"]["public"]["mode"] = "custom"
        res["method"]["public"]["whitelist"] = api_access.public_methods.split()
    elif api_access.api_public_methods:
        res["method"]["public"]["mode"] = "all"
    else:
        res["method"]["public"]["mode"] = "none"
    
    # Infer private method mode
    if api_access.private_methods:
        res["method"]["private"]["mode"] = "custom"
        res["method"]["private"]["whitelist"] = api_access.private_methods.split()
    else:
        res["method"]["private"]["mode"] = "none"
    
    # Process context
    for c in api_access.create_context_ids.mapped("context"):
        res["context"].update(json.loads(c))
    
    # Process export fields
    res["out_fields_read_multi"] = tuple(
        api_access.read_many_id.export_fields.mapped("name") or ["id"]
    )
    res["out_fields_read_one"] = tuple(
        api_access.read_one_id.export_fields.mapped("name") or ["id"]
    )
    
    # Set main method modes based on CRUD permissions
    if api_access.api_create:
        res["method"]["main"]["whitelist"].append("api_create")
    if api_access.api_read:
        res["method"]["main"]["whitelist"].append("api_read")
    if api_access.api_update:
        res["method"]["main"]["whitelist"].append("api_update")
    if api_access.api_delete:
        res["method"]["main"]["whitelist"].append("api_delete")
    
    if res["method"]["main"]["whitelist"]:
        res["method"]["main"]["mode"] = "custom"
    
    return res


def method_is_allowed(method, methods_conf, main=False, raise_exception=False):
    """Check that the method is allowed for the specified settings.
    
    Args:
        method (str): The name of the method.
        methods_conf (dict): The methods configuration dictionary.
        main (bool): The method is one of access fields.
        raise_exception (bool): Raise exception instead of returning False.
        
    Returns:
        bool: True if method is allowed, otherwise False.
        
    Raises:
        werkzeug.exceptions.HTTPException: If method not allowed and raise_exception is True.
    """
    if main:
        method_type = "main"
    else:
        method_type = "private" if method.startswith("_") else "public"
    
    if methods_conf[method_type]["mode"] == "all":
        return True
    if (methods_conf[method_type]["mode"] == "custom" and 
        method in methods_conf[method_type]["whitelist"]):
        return True
    
    if raise_exception:
        raise werkzeug.exceptions.HTTPException(
            response=pinguin.error_response(*pinguin.CODE__method_blocked)
        )
    return False


# Wrapper functions for API operations
def wrap__resource__create_one(modelname, context, data, success_code, out_fields):
    """Function to create one record."""
    model_obj = pinguin.get_model_for_read(modelname)
    try:
        created_obj = model_obj.with_context(context).create(data)
        test_mode = request.registry.test_cr
        if not test_mode:
            request.env.cr.commit()
    except Exception as e:
        return pinguin.error_response(400, type(e).__name__, str(e))
    
    out_data = pinguin.get_dict_from_record(created_obj, out_fields, (), ())
    return pinguin.successful_response(success_code, out_data)


def wrap__resource__read_all(modelname, success_code, out_fields):
    """Function to read all records."""
    data = pinguin.get_dictlist_from_model(modelname, out_fields)
    return pinguin.successful_response(success_code, data)


def wrap__resource__read_one(modelname, id, success_code, out_fields):
    """Function to read one record."""
    out_data = pinguin.get_dict_from_model(modelname, out_fields, id)
    return pinguin.successful_response(success_code, out_data)


def wrap__resource__update_one(modelname, id, success_code, data):
    """Function to update one record."""
    cr, uid = request.cr, request.session.uid
    record = request.env(cr, uid)[modelname].browse(id)
    if not record.exists():
        return pinguin.error_response(*pinguin.CODE__obj_not_found)
    try:
        record.write(data)
    except Exception as e:
        return pinguin.error_response(400, type(e).__name__, str(e))
    return pinguin.successful_response(success_code)


def wrap__resource__unlink_one(modelname, id, success_code):
    """Function to delete one record."""
    cr, uid = request.cr, request.session.uid
    record = request.env(cr, uid)[modelname].browse([id])
    if not record.exists():
        return pinguin.error_response(*pinguin.CODE__obj_not_found)
    record.unlink()
    return pinguin.successful_response(success_code)


def wrap__resource__call_method(modelname, ids, method, method_params, success_code):
    """Function to call model method for records by IDs."""
    model_obj = pinguin.get_model_for_read(modelname)
    
    if not hasattr(model_obj, method):
        return pinguin.error_response(*pinguin.CODE__invalid_method)
    
    records = model_obj.browse(ids).exists()
    results = []
    args = method_params.get("args", [])
    kwargs = method_params.get("kwargs", {})
    
    for record in records or [model_obj]:
        result = getattr(record, method)(*args, **kwargs)
        results.append(result)
    
    if len(ids) <= 1 and len(results):
        results = results[0]
    model_obj.flush_model()  # to recompute fields
    return pinguin.successful_response(success_code, data=results)


def wrap__resource__get_report(namespace, report_external_id, docids, converter, success_code):
    """Return html or pdf report response."""
    report = request.env.ref(report_external_id)
    
    if isinstance(report, type(request.env["ir.ui.view"])):
        report = request.env["report"]._get_report_from_name(report_external_id)
    
    model = report.model
    report_name = report.report_name
    
    get_model_api_access(namespace, model)
    
    response = ReportController().report_routes(report_name, docids, converter)
    response.status_code = success_code
    return response
