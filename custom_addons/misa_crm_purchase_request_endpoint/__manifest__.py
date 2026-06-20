# -*- coding: utf-8 -*-
{
    "name": "MISA CRM Purchase Request Endpoint",
    "version": "18.0.1.0.0",
    "category": "Purchase",
    "summary": "Endpoint to import MISA CRM purchase request data into Odoo purchase.request",
    "license": "LGPL-3",
    "depends": ["purchase_request", "product", "stock"],
    "data": [
        "data/ir_config_parameter.xml",
    ],
    "installable": True,
    "application": False,
}