# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pinguin module for Odoo REST Api - Unified version for Rest Api Pragmatic.

This module implements plumbing code to the REST interface concerning
authentication, validation, ORM access and error codes.
It combines functionality from base_api and openapi modules into one cohesive library.
"""

import base64
import collections
import collections.abc
import datetime
import functools
import traceback

import werkzeug.wrappers
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED

import odoo
from odoo import _
from odoo.http import request
from odoo.service import security
from odoo.modules.registry import Registry
from odoo.exceptions import ValidationError

try:
    import simplejson as json
except ImportError:
    import json

# Import six for Python 2/3 compatibility (deprecated in Odoo 18, using native strings)
import sys
if sys.version_info[0] >= 3:
    string_types = str
else:
    string_types = basestring

####################################
# Definition of global error codes #
####################################

# 2xx Success
CODE__success = 200
CODE__created = 201
CODE__accepted = 202
CODE__ok_no_content = 204

# 4xx Client Errors
CODE__server_rejects = (400, "Server rejected", "Welcome to Rest Api Pragmatic!")
CODE__no_user_auth = (401, "Authentication", "Your token could not be authenticated.")
CODE__user_no_perm = (403, "Permissions", "%s")
CODE__method_blocked = (403, "Blocked Method", "This method is not whitelisted on this model.")
CODE__db_not_found = (404, "Db not found", "Database not found on this instance.")
CODE__canned_ctx_not_found = (404, "Canned context not found", 
                             "The requested canned context is not configured on this model")
CODE__obj_not_found = (404, "Object not found", "This object is not available on this instance.")
CODE__res_not_found = (404, "Resource not found", "There is no resource with this id.")
CODE__act_not_executed = (409, "Action not executed", "The requested action was not executed.")

# 5xx Server errors
CODE__invalid_method = (501, "Invalid Method", "This method is not implemented.")
CODE__invalid_spec = (501, "Invalid Field Spec", "The field spec supplied is not valid.")
CODE__no_api_worker = (503, "API worker sleeping", "The API worker is currently not at work.")


def error_response(status, error, error_descrip):
    """Error responses wrapper.
    
    Args:
        status (int): The error code.
        error (str): The error summary.
        error_descrip (str): The error description.
        
    Returns:
        werkzeug.wrappers.Response: The response object.
    """
    return werkzeug.wrappers.Response(
        status=status,
        content_type="application/json; charset=utf-8",
        response=json.dumps({"error": error, "error_descrip": error_descrip}),
    )


def successful_response(status, data=None):
    """Successful responses wrapper.
    
    Args:
        status (int): The success code.
        data: The data that can be converted to JSON.
        
    Returns:
        werkzeug.wrappers.Response: The response object.
    """
    try:
        data = data.ids
    except AttributeError:
        pass
    return request.make_json_response(data, status=status)


##########################
# Validation Functions   #
##########################

def validate_extra_field(field):
    """Validates extra fields on the fly.
    
    Args:
        field (str): The name of the field.
        
    Raises:
        werkzeug.exceptions.HTTPException: If field is invalid.
    """
    if not isinstance(field, str):
        raise werkzeug.exceptions.HTTPException(
            response=error_response(*CODE__invalid_spec)
        )


def validate_spec(model, spec):
    """Validates a spec for a given model.
    
    Args:
        model: The model against which to validate.
        spec (list): The spec to validate.
        
    Raises:
        Exception: Various validation errors.
    """
    self = model
    for field in spec:
        if isinstance(field, tuple):
            # Syntax checks
            if len(field) != 2:
                raise Exception(f"Tuples representing fields must have length 2. ({field!r})")
            if not isinstance(field[1], (tuple, list)):
                raise Exception(f"Tuples representing fields must have a tuple wrapped in "
                              f"a list or a bare tuple as it's second item. ({field!r})")
            # Validity checks
            fld = self._fields[field[0]]
            if not fld.relational:
                raise Exception(f"Tuples representing fields can only specify relational fields. ({field!r})")
            if isinstance(field[1], tuple) and fld.type in ["one2many", "many2many"]:
                raise Exception(f"Specification of a 2many record cannot be a bare tuple. ({field!r})")
        elif not isinstance(field, string_types):
            raise Exception(f"Fields are represented by either strings or tuples. Found: {type(field)!r}")


##########################
# Utility Functions      #
##########################

def update(d, u):
    """Update value of a nested dictionary of varying depth.
    
    Args:
        d (dict): Dictionary to update.
        u (dict): Dictionary with updates.
        
    Returns:
        dict: Merged dictionary.
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, collections.OrderedDict([])), v)
        else:
            d[k] = v
    return d


def transform_strfields_to_dict(fields_list, delim="/"):
    """Transform string fields to dictionary.
    
    Example:
        ['name', 'email', 'bank_ids/bank_id/id', 'bank_ids/bank_name']
        becomes:
        {
            'name': None,
            'email': None,
            'bank_ids': {
                'bank_name': None,
                'bank_id': {'id': None}
            }
        }
        
    Args:
        fields_list (list): The list of string fields.
        delim (str): Delimiter for nested fields.
        
    Returns:
        dict: The dict of transformed fields.
    """
    dct = {}
    for field in fields_list:
        parts = field.split(delim)
        data = None
        for part in parts[::-1]:
            if part == ".id":
                part = "id"
            data = {part: data}
        update(dct, data)
    return dct


def transform_dictfields_to_list_of_tuples(record, dct, ENV=False):
    """Transform fields dictionary to list.
    
    Args:
        record: The model object.
        dct (dict): The dictionary.
        ENV: Model's environment.
        
    Returns:
        list: The list of transformed fields.
    """
    fields_with_meta = {
        k: meta for k, meta in record.fields_get().items() if k in dct.keys()
    }
    result = {}
    for key, value in dct.items():
        if isinstance(value, dict):
            model_obj = get_model_for_read(fields_with_meta[key]["relation"], ENV)
            inner_result = transform_dictfields_to_list_of_tuples(model_obj, value, ENV)
            is_2many = fields_with_meta[key]["type"].endswith("2many")
            result[key] = list(inner_result) if is_2many else tuple(inner_result)
        else:
            result[key] = value
    return [(key, value) if value else key for key, value in result.items()]


##########################
# Authentication         #
##########################

def authenticate_token_for_user(token):
    """Authenticate against the database and setup user session corresponding to the token.
    
    Args:
        token (str): The raw access token.
        
    Returns:
        odoo.models.Model: User if token is authorized.
        
    Raises:
        werkzeug.exceptions.HTTPException: If user not found.
    """
    user = request.env["res.users"].sudo().search([("api_token", "=", token)])
    if user.exists():
        # Ensure we work with a single user record
        if len(user) > 1:
            user = user[0]
        # Setup session
        request.session.uid = user.id
        request.session.login = user.login
        request.session.session_token = user.id and security.compute_session_token(
            request.session, request.env
        )
        request.update_env(user=user.id)
        return user
    raise werkzeug.exceptions.HTTPException(
        response=error_response(*CODE__no_user_auth)
    )


def get_auth_header(headers, raise_exception=False):
    """Check and get basic authentication header from headers.
    
    Args:
        headers: All headers in request.
        raise_exception (bool): Whether to raise exception.
        
    Returns:
        str or None: Found raw authentication header.
        
    Raises:
        werkzeug.exceptions.HTTPException: If auth header is invalid.
    """
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        if raise_exception:
            raise werkzeug.exceptions.HTTPException(
                response=error_response(*CODE__no_user_auth)
            )
    return auth_header


def get_data_from_auth_header(header):
    """Decode basic auth header and get data.
    
    Args:
        header (str): The raw auth header.
        
    Returns:
        tuple: (database_name, user_token).
        
    Raises:
        werkzeug.exceptions.HTTPException: If header is invalid.
    """
    normalized_token = header.replace("Basic ", "").replace("\\n", "").encode("utf-8")
    try:
        decoded_token_parts = (
            base64.b64decode(normalized_token).decode("utf-8").split(":")
        )
    except TypeError as e:
        raise werkzeug.exceptions.HTTPException(
            response=error_response(500, "Invalid header", 
                                   "Basic auth header must be valid base64 string")
        ) from e

    if len(decoded_token_parts) == 1:
        db_name, user_token = None, decoded_token_parts[0]
    elif len(decoded_token_parts) == 2:
        db_name, user_token = decoded_token_parts
    else:
        err_descrip = ('Basic auth header payload must be of the form "<%s>" '
                      '(encoded to base64)' % ("user_token" if odoo.tools.config["dbfilter"]
                                               else "db_name:user_token"))
        raise werkzeug.exceptions.HTTPException(
            response=error_response(500, "Invalid header", err_descrip)
        )
    return db_name, user_token


def setup_db(httprequest, db_name):
    """Check and setup db in session by db name.
    
    Args:
        httprequest: A wrapped werkzeug Request object.
        db_name (str): Database name.
        
    Raises:
        werkzeug.exceptions.HTTPException: If database not found.
    """
    if httprequest.session.db:
        return
    if db_name not in odoo.service.db.list_dbs(force=True):
        raise werkzeug.exceptions.HTTPException(
            response=error_response(*CODE__db_not_found)
        )
    httprequest.session.db = db_name


###################
# ORM Functions   #
###################

def get_model_for_read(model, ENV=False):
    """Fetch a model object from the environment optimized for read.
    
    Args:
        model (str): The model to retrieve.
        ENV: Environment.
        
    Returns:
        odoo.models.Model: The model if exists.
        
    Raises:
        werkzeug.exceptions.HTTPException: If model not found.
    """
    if ENV:
        return ENV[model]
    cr, uid = request.cr, request.session.uid
    test_mode = request.registry.test_cr
    if not test_mode:
        # Permit parallel query execution on read
        cr._cnx.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
    try:
        return request.env(cr, uid)[model]
    except KeyError as e:
        err = list(CODE__obj_not_found)
        err[2] = f'The "{model}" model is not available on this instance.'
        raise werkzeug.exceptions.HTTPException(response=error_response(*err)) from e


def get_dict_from_record(record, spec, include_fields, exclude_fields, ENV=False, delim="/"):
    """Generates nested python dict representing one record.
    
    Args:
        record: The singleton record to load.
        spec (tuple): The field spec to load.
        include_fields (tuple): Extra fields to include.
        exclude_fields (tuple): Fields to exclude.
        ENV: Environment.
        delim (str): Delimiter for nested fields.
        
    Returns:
        collections.OrderedDict: Dictionary representing the record.
    """
    list(map(validate_extra_field, include_fields + exclude_fields))
    result = collections.OrderedDict([])
    _spec = [fld for fld in spec if fld not in exclude_fields] + list(include_fields)
    
    if list(filter(lambda x: isinstance(x, string_types) and delim in x, _spec)):
        _spec = transform_dictfields_to_list_of_tuples(
            record, transform_strfields_to_dict(_spec, delim), ENV
        )
    validate_spec(record, _spec)

    for field in _spec:
        if isinstance(field, tuple):
            # It's a 2many (or a 2one specified as a list)
            if isinstance(field[1], list):
                result[field[0]] = []
                for rec in record[field[0]]:
                    result[field[0]] += [
                        get_dict_from_record(rec, field[1], (), (), ENV, delim)
                    ]
            # It's a 2one
            if isinstance(field[1], tuple):
                result[field[0]] = get_dict_from_record(
                    record[field[0]], field[1], (), (), ENV, delim
                )
        # Normal field, or unspecified relational
        elif isinstance(field, string_types):
            if not hasattr(record, field):
                raise ValidationError(
                    _('The model "%s" has no such field: "%s".') % (record._name, field)
                )

            if isinstance(record[field], datetime.date):
                value = record[field].strftime("%Y-%m-%d %H:%M:%S")
            else:
                value = record[field]

            result[field] = value
            fld = record._fields[field]
            if fld.relational:
                if fld.type.endswith("2one"):
                    result[field] = value.id
                elif fld.type.endswith("2many"):
                    result[field] = value.ids
            elif (value is False or value is None) and fld.type != "boolean":
                # String field cannot be false in response json
                result[field] = ""
    return result


def get_dictlist_from_model(model, spec, **kwargs):
    """Fetch dictionary from records according to spec.
    
    Args:
        model (str): The model to query.
        spec (tuple): The spec to validate.
        **kwargs: Additional parameters (domain, offset, limit, order, etc.)
        
    Returns:
        list: List of python dictionaries of requested values.
    """
    domain = kwargs.get("domain", [])
    offset = kwargs.get("offset", 0)
    limit = kwargs.get("limit")
    order = kwargs.get("order")
    include_fields = kwargs.get("include_fields", ())
    exclude_fields = kwargs.get("exclude_fields", ())
    delim = kwargs.get("delimeter", "/")
    ENV = kwargs.get("env", False)

    model_obj = get_model_for_read(model, ENV)
    records = model_obj.sudo().search(domain, offset=offset, limit=limit, order=order)

    # Do some optimization for subfields
    _prefetch = {}
    for field in spec:
        if isinstance(field, str):
            continue
        _fld = records._fields[field[0]]
        if _fld.relational:
            _prefetch[_fld.comodel] = records.mapped(field[0]).ids

    for mod, ids in _prefetch.items():
        get_model_for_read(mod, ENV).browse(ids).read()

    result = []
    for record in records:
        result += [
            get_dict_from_record(
                record, spec, include_fields, exclude_fields, ENV, delim
            )
        ]
    return result


def get_dict_from_model(model, spec, id, **kwargs):
    """Fetch dictionary from one record according to spec.
    
    Args:
        model (str): The model to query.
        spec (tuple): The spec to validate.
        id (int): The record id.
        **kwargs: Additional parameters.
        
    Returns:
        dict: Python dictionary of requested values.
        
    Raises:
        werkzeug.exceptions.HTTPException: If record does not exist.
    """
    include_fields = kwargs.get("include_fields", ())
    exclude_fields = kwargs.get("exclude_fields", ())
    model_obj = get_model_for_read(model)
    record = model_obj.browse([id])
    
    if not record.exists():
        raise werkzeug.exceptions.HTTPException(
            response=error_response(*CODE__res_not_found)
        )
    return get_dict_from_record(record, spec, include_fields, exclude_fields)


#######################
# OpenAPI Functions   #
#######################

def get_definition_name(modelname, prefix="", postfix="", splitter="-"):
    """Concatenation of the prefix, modelname, postfix.
    
    Args:
        modelname (str): The name of the model.
        prefix (str): The prefix.
        postfix (str): The postfix.
        splitter (str): The splitter.
        
    Returns:
        str: Concatenation of the arguments.
    """
    return splitter.join([s for s in [prefix, modelname, postfix] if s])


def get_OAS_definitions_part(model_obj, export_fields_dict, 
                           definition_prefix="", definition_postfix=""):
    """Recursively gets definition parts of the OAS for model by export fields.
    
    Args:
        model_obj: The model object.
        export_fields_dict (dict): Dictionary with export fields.
        definition_prefix (str): Prefix for definition name.
        definition_postfix (str): Postfix for definition name.
        
    Returns:
        dict: Definitions for the model and relative models.
    """
    definition_name = get_definition_name(
        model_obj._name, definition_prefix, definition_postfix
    )

    definitions = {
        definition_name: {"type": "object", "properties": {}, "required": []},
    }

    fields_meta = model_obj.fields_get(export_fields_dict.keys())

    for field, child_fields in export_fields_dict.items():
        meta = fields_meta[field]
        if child_fields:
            child_model = model_obj.env[meta["relation"]]
            child_definition = get_OAS_definitions_part(
                child_model, child_fields, definition_prefix=definition_name
            )

            if meta["type"].endswith("2one"):
                field_property = child_definition[
                    get_definition_name(child_model._name, prefix=definition_name)
                ]
            else:
                field_property = {
                    "type": "array",
                    "items": child_definition[
                        get_definition_name(child_model._name, prefix=definition_name)
                    ],
                }
        else:
            field_property = {}

            if meta["type"] == "integer":
                field_property.update(type="integer")
            elif meta["type"] in ["float", "monetary"]:
                field_property.update(type="number", format="float")
            elif meta["type"] in ["char", "text"]:
                field_property.update(type="string")
            elif meta["type"] == "binary":
                field_property.update(type="string", format="binary")
            elif meta["type"] == "boolean":
                field_property.update(type="boolean")
            elif meta["type"] == "date":
                field_property.update(type="string", format="date")
            elif meta["type"] == "datetime":
                field_property.update(type="string", format="date-time")
            elif meta["type"] == "many2one":
                field_property.update(type="integer")
            elif meta["type"] == "selection":
                field_property.update({
                    "type": "integer" if isinstance(meta["selection"][0][0], int) else "string",
                    "enum": [i[0] for i in meta["selection"]],
                })
            elif meta["type"] in ["one2many", "many2many"]:
                field_property.update({"type": "array", "items": {"type": "integer"}})

            if meta["readonly"] and (not meta["required"] or meta.get("related")):
                field_property.update(readOnly=True)

        definitions[definition_name]["properties"][field] = field_property

        if meta["required"] and not meta.get("related"):
            fld = model_obj._fields[field]
            # Mark as required only if field doesn't have default value
            if fld.default is None and fld.type != "boolean":
                definitions[definition_name]["required"].append(field)

    if not definitions[definition_name]["required"]:
        del definitions[definition_name]["required"]

    return definitions
