# -*- coding: utf-8 -*-
"""
Bridge between misa.crm.tools (abstract registry) and llm.tool (DB model).

Each MISA tool is registered as an llm.tool implementation so it appears
in the "Công cụ AI" list view and can be discovered by the LLM framework.
"""
import json
import logging

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

    def _misa_dispatch(self, tool_name, parameters):
        """Delegate execution to misa.crm.tools registry."""
        return self.env['misa.crm.tools'].sudo().execute(tool_name, parameters)

    def misa_search_product_execute(self, **kwargs):
        return self._misa_dispatch('search_product_misa', kwargs)

    def misa_create_product_execute(self, **kwargs):
        return self._misa_dispatch('create_product_misa', kwargs)

    def misa_update_product_execute(self, **kwargs):
        return self._misa_dispatch('update_product_misa', kwargs)

    def misa_get_category_execute(self, **kwargs):
        return self._misa_dispatch('get_category_info', kwargs)

    def misa_search_category_execute(self, **kwargs):
        return self._misa_dispatch('search_category_misa', kwargs)

    def misa_search_purchase_execute(self, **kwargs):
        return self._misa_dispatch('search_purchase_voucher', kwargs)
