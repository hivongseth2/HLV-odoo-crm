# -*- coding: utf-8 -*-
"""
Base tool registry for MISA CRM LLM tools.

Pattern:
    - Each tool group inherits 'misa.crm.tools' and extends _get_tool_map()
    - Adding new tools = new file + _inherit + override _get_tool_map with super()
    - Consumer calls get_all_schemas() for OpenAI tool definitions
    - Consumer calls execute(tool_name, args) for dispatch
"""
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MisaCrmTools(models.AbstractModel):
    _name = 'misa.crm.tools'
    _description = 'MISA CRM Tool Registry for LLM'

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def _get_tool_map(self):
        """Return {tool_name: {'schema': dict, 'handler': callable}}.
        Override via super() in mixins to register tools."""
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_all_schemas(self):
        """Return list of OpenAI function-calling schemas."""
        return [t['schema'] for t in self._get_tool_map().values()]

    def execute(self, tool_name, args):
        """Dispatch a tool call by name. Returns JSON string."""
        tool_map = self._get_tool_map()
        entry = tool_map.get(tool_name)
        if not entry:
            _logger.warning("Unknown tool requested: %s", tool_name)
            return json.dumps(
                {"status": "error", "message": f"Tool '{tool_name}' không tồn tại"},
                ensure_ascii=False,
            )
        try:
            return entry['handler'](args)
        except Exception as e:
            _logger.exception("Tool '%s' failed", tool_name)
            return json.dumps(
                {"status": "error", "message": str(e)},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # Shared helpers (available to all tool mixins)
    # ------------------------------------------------------------------
    def _api(self):
        """Access MISA CRM API facade (single dependency point)."""
        return self.env['misa.crm.api'].sudo()

    def _ok(self, **data):
        return json.dumps({"status": "success", **data}, ensure_ascii=False)

    def _fail(self, message, **extra):
        return json.dumps({"status": "error", "message": message, **extra}, ensure_ascii=False)
