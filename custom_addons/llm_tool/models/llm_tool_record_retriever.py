import json
import logging
from typing import Any

from odoo import api, models

_logger = logging.getLogger(__name__)

# Explicit input schema to guide LLM on correct parameter types
RECORD_RETRIEVER_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {
            "type": "string",
            "description": "The Odoo model technical name (e.g., 'sale.order', 'product.product', 'res.partner')",
        },
        "domain": {
            "type": "array",
            "description": (
                "Odoo domain filter. Each element is either a string operator "
                "('&', '|', '!') or a 3-element array [field, operator, value]. "
                "Examples: [['id', '=', 123]], [['name', 'ilike', 'test']], "
                "[['state', 'in', ['sale', 'done']]], "
                "['&', ['partner_id', '=', 5], ['state', '=', 'sale']]"
            ),
            "items": {
                "oneOf": [
                    {
                        "type": "string",
                        "enum": ["&", "|", "!"],
                        "description": "Logical operator to combine domain conditions",
                    },
                    {
                        "type": "array",
                        "items": {},
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "A domain leaf: [field_name, operator, value]. "
                        "field_name is a string, operator is one of "
                        "'=', '!=', '>', '>=', '<', '<=', 'like', 'ilike', "
                        "'in', 'not in', '=like', '=ilike', 'child_of', 'parent_of'. "
                        "value type depends on the field: integer for id/Many2one fields, "
                        "string for Char/Text fields, boolean, or array for 'in' operators.",
                    },
                ],
            },
            "default": [],
        },
        "fields": {
            "type": "array",
            "description": "List of field names to retrieve. If empty, returns all fields.",
            "items": {"type": "string"},
            "default": [],
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of records to return (default: 100)",
            "default": 100,
        },
    },
    "required": ["model"],
    "additionalProperties": False,
}


class LLMToolRecordRetriever(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("odoo_record_retriever", "Odoo Record Retriever")]

    def get_input_schema(self):
        """Return explicit schema for odoo_record_retriever."""
        self.ensure_one()
        if self.implementation == "odoo_record_retriever" and not self.input_schema:
            return RECORD_RETRIEVER_SCHEMA
        return super().get_input_schema()

    def odoo_record_retriever_execute(
        self,
        model: str,
        domain: list = None,
        fields: list[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Retrieve records from any Odoo model with filtering capabilities.

        Parameters:
            model: The Odoo model to retrieve records from (e.g., 'sale.order')
            domain: Domain to filter records. Array of conditions, each is [field, operator, value].
                    id values MUST be integers, not strings. Example: [["id", "=", 123]]
            fields: List of field names to retrieve
            limit: Maximum number of records to retrieve
        """
        if domain is None:
            domain = []
        if fields is None:
            fields = []

        # Sanitize and validate domain
        domain = self._sanitize_domain(domain)

        # Ensure limit is integer
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100

        _logger.info(
            "Executing Odoo Record Retriever with: model=%s, domain=%s, fields=%s, limit=%s",
            model, domain, fields, limit,
        )

        if model not in self.env:
            return {"error": f"Model '{model}' does not exist"}

        model_obj = self.env[model]

        try:
            if fields:
                result = model_obj.search_read(domain=domain, fields=fields, limit=limit)
            else:
                records = model_obj.search(domain=domain, limit=limit)
                result = records.read()
        except Exception as e:
            _logger.error("Error retrieving records from %s: %s", model, e)
            return {"error": str(e)}

        # Convert to serializable format
        return json.loads(json.dumps(result, default=str))

    def _sanitize_domain(self, domain):
        """Validate and fix common LLM mistakes in Odoo domain format.

        Common issues:
        - Passing string IDs like "123" instead of integer 123
        - Passing "]" or other garbage as values
        - Wrapping domain in extra arrays
        - Passing flat list instead of nested list
        """
        if not domain:
            return []

        # If domain is a flat 3-element list like ['field', '=', value],
        # wrap it in an outer list
        if (
            len(domain) == 3
            and isinstance(domain[0], str)
            and domain[0] not in ("&", "|", "!")
        ):
            domain = [domain]

        sanitized = []
        for item in domain:
            # String operators (&, |, !) pass through
            if isinstance(item, str) and item in ("&", "|", "!"):
                sanitized.append(item)
                continue

            # Domain leaf must be a list/tuple with exactly 3 elements
            if not isinstance(item, (list, tuple)):
                _logger.warning("Skipping invalid domain element: %s", item)
                continue

            if len(item) != 3:
                _logger.warning("Skipping domain leaf with %d elements: %s", len(item), item)
                continue

            field, operator, value = item

            # Validate field is a string
            if not isinstance(field, str):
                _logger.warning("Skipping domain leaf with non-string field: %s", item)
                continue

            # Validate operator
            valid_ops = (
                "=", "!=", ">", ">=", "<", "<=",
                "like", "ilike", "not like", "not ilike",
                "in", "not in", "=like", "=ilike",
                "child_of", "parent_of",
            )
            if not isinstance(operator, str) or operator not in valid_ops:
                _logger.warning("Invalid operator '%s', defaulting to '='", operator)
                operator = "="

            # Fix value types for ID-like fields
            value = self._sanitize_domain_value(field, operator, value)

            sanitized.append([field, operator, value])

        return sanitized

    @staticmethod
    def _sanitize_domain_value(field, operator, value):
        """Fix common value type issues from LLM output."""
        # For 'in' / 'not in' operators, value must be a list
        if operator in ("in", "not in"):
            if not isinstance(value, list):
                value = [value]
            # Try to convert list items to int for id-like fields
            if field == "id" or field.endswith("_id") or field.endswith("_ids"):
                cleaned = []
                for v in value:
                    try:
                        cleaned.append(int(v))
                    except (ValueError, TypeError):
                        cleaned.append(v)
                return cleaned
            return value

        # For id fields, ensure integer type
        if field == "id" or (
            field.endswith("_id") and operator in ("=", "!=", ">", ">=", "<", "<=")
        ):
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                # Strip non-numeric garbage
                cleaned = "".join(c for c in value if c.isdigit() or c == "-")
                if cleaned:
                    try:
                        return int(cleaned)
                    except (ValueError, TypeError):
                        pass
                _logger.warning(
                    "Cannot convert '%s' to integer for field '%s', returning 0",
                    value, field,
                )
                return 0

        # General type coercion: try numeric conversion for string values
        if isinstance(value, str) and operator in ("=", "!=", ">", ">=", "<", "<="):
            stripped = value.strip()
            try:
                return int(stripped)
            except (ValueError, TypeError):
                pass
            try:
                return float(stripped)
            except (ValueError, TypeError):
                pass

        return value
