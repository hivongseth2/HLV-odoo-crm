# -*- coding: utf-8 -*-
"""
Base tool registry for Zalo LLM tools.
Same pattern as misa.crm.tools — each tool group inherits and extends _get_tool_map().
"""
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ZaloTools(models.AbstractModel):
    _name = 'zalo.llm.tools'
    _description = 'Zalo Tool Registry for LLM'

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def _get_tool_map(self):
        """Return {tool_name: {'schema': dict, 'handler': callable}}."""
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_all_schemas(self):
        return [t['schema'] for t in self._get_tool_map().values()]

    def execute(self, tool_name, args):
        tool_map = self._get_tool_map()
        entry = tool_map.get(tool_name)
        if not entry:
            _logger.warning("Unknown Zalo tool: %s", tool_name)
            return json.dumps(
                {"status": "error", "message": f"Tool '{tool_name}' không tồn tại"},
                ensure_ascii=False,
            )
        try:
            return entry['handler'](args)
        except Exception as e:
            _logger.exception("Zalo tool '%s' failed", tool_name)
            return json.dumps(
                {"status": "error", "message": str(e)},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def _ok(self, **data):
        return json.dumps({"status": "success", **data}, ensure_ascii=False)

    def _fail(self, message, **extra):
        return json.dumps({"status": "error", "message": message, **extra}, ensure_ascii=False)
