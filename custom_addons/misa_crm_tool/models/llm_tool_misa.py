# -*- coding: utf-8 -*-
"""
Bridge between misa.crm.tools (abstract registry) and llm.tool (DB model).

Each MISA tool is registered as an llm.tool implementation so it appears
in the "Công cụ AI" list view and can be discovered by the LLM framework.

NOTE: execute methods MUST have explicit parameter signatures (not **kwargs)
because llm.tool.execute() uses Pydantic to validate from method signature.
"""
import json
import logging
from typing import Optional

from odoo import api, models

_logger = logging.getLogger(__name__)


class LLMToolMisa(models.Model):
    _inherit = "llm.tool"

    # -- Register 6 implementation types ------------------------------------
    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [
            ("misa_search_product", "MISA Search Product"),
            ("misa_create_product", "MISA Create Product"),
            ("misa_update_product", "MISA Update Product"),
            ("misa_get_category", "MISA Get Category Info"),
            ("misa_search_category", "MISA Search Category"),
            ("misa_search_purchase", "MISA Search Purchase Voucher"),
        ]

    # -- Execution methods (delegate to misa.crm.tools) --------------------
    # Signatures MUST match the input_schema in llm_tool_data.xml exactly.

    def _misa_dispatch(self, tool_name, parameters):
        """Delegate execution to misa.crm.tools registry."""
        return self.env['misa.crm.tools'].sudo().execute(tool_name, parameters)

    def misa_search_product_execute(self, name: str) -> str:
        return self._misa_dispatch('search_product_misa', {'name': name})

    def misa_create_product_execute(
        self,
        code: str,
        name: str,
        price: float,
        price_pu: float,
        tax: float,
        unit: str,
        category: str,
        category_id: int,
        type: str,
    ) -> str:
        return self._misa_dispatch('create_product_misa', {
            'code': code, 'name': name, 'price': price,
            'price_pu': price_pu, 'tax': tax, 'unit': unit,
            'category': category, 'category_id': category_id, 'type': type,
        })

    def misa_update_product_execute(
        self,
        misa_id: str,
        field: str,
        new_value: str,
        old_value: str,
    ) -> str:
        return self._misa_dispatch('update_product_misa', {
            'misa_id': misa_id, 'field': field,
            'new_value': new_value, 'old_value': old_value,
        })

    def misa_get_category_execute(self, category_id: str) -> str:
        return self._misa_dispatch('get_category_info', {'category_id': category_id})

    def misa_search_category_execute(self, name: str) -> str:
        return self._misa_dispatch('search_category_misa', {'name': name})

    def misa_search_purchase_execute(
        self,
        journal_memo: str,
        limit: int = 20,
    ) -> str:
        return self._misa_dispatch('search_purchase_voucher', {
            'journal_memo': journal_memo, 'limit': limit,
        })
