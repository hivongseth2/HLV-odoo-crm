# -*- coding: utf-8 -*-
{
    'name': 'MISA CRM Tools for LLM',
    'version': '18.0.1.0.0',
    'category': 'Tools',
    'summary': 'Centralized MISA CRM tool registry for LLM function calling',
    'depends': ['base', 'product', 'uom', 'account', 'point_of_sale', 'llm_tool'],
    'data': [
        'security/ir.model.access.csv',
        'data/llm_tool_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
