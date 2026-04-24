# -*- coding: utf-8 -*-
from odoo import api, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    @staticmethod
    def _extract_report_id(report_item):
        if isinstance(report_item, int):
            return report_item

        if isinstance(report_item, str) and report_item.strip().isdigit():
            return int(report_item)

        if isinstance(report_item, (list, tuple)) and report_item:
            first = report_item[0]
            if isinstance(first, int):
                return first
            if isinstance(first, str) and first.strip().isdigit():
                return int(first)

        if isinstance(report_item, dict) and "id" in report_item:
            report_id = report_item.get("id")
            if isinstance(report_id, int):
                return report_id
            if isinstance(report_id, str) and report_id.strip().isdigit():
                return int(report_id)

        return None

    @api.model
    def _extract_active_ids(self):
        active_ids = self.env.context.get("active_ids") or []
        if not active_ids and self.env.context.get("active_id"):
            active_ids = [self.env.context.get("active_id")]

        if not active_ids:
            for key in ("id", "res_id", "resId"):
                value = self.env.context.get(key)
                if value:
                    active_ids = [value]
                    break

        if not active_ids:
            params = self.env.context.get("params") or {}
            for key in ("id", "resId", "res_id", "active_id"):
                if params.get(key):
                    active_ids = [params.get(key)]
                    break

            if not active_ids:
                for key in ("ids", "resIds", "res_ids", "active_ids"):
                    value = params.get(key)
                    if isinstance(value, (list, tuple)) and value:
                        active_ids = list(value)
                        break

        normalized_ids = []
        for value in active_ids:
            try:
                normalized_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return normalized_ids

    @api.model
    def _get_current_picking_types(self):
        picking_type_ids = set()
        picking_type_sequence_codes = set()

        active_ids = self._extract_active_ids()
        if active_ids:
            pickings = self.sudo().browse(active_ids).exists()
            picking_type_ids = set(pickings.mapped("picking_type_id").ids)

        if not picking_type_ids:
            default_picking_type_id = self.env.context.get("default_picking_type_id")
            try:
                if default_picking_type_id:
                    picking_type_ids.add(int(default_picking_type_id))
            except (TypeError, ValueError):
                pass

        if picking_type_ids:
            picking_types = (
                self.env["stock.picking.type"]
                .sudo()
                .browse(list(picking_type_ids))
                .exists()
            )
            picking_type_sequence_codes = {
                code
                for code in picking_types.mapped("sequence_code")
                if code
            }

        return picking_type_ids, picking_type_sequence_codes

    @api.model
    def _get_hidden_report_ids(self):
        user = self.env.user
        company = self.env.company
        picking_type_ids, picking_type_sequence_codes = self._get_current_picking_types()

        hidden_report_ids = set()
        active_rules = self.env["report.access.right"].sudo().search([
            ("status", "=", "active"),
        ])

        for rule in active_rules:
            hide = False
            if rule.hide_based_on == "user" and user in rule.hide_user_ids:
                hide = True
            elif rule.hide_based_on == "company" and company in rule.hide_company_ids:
                hide = True
            elif rule.hide_based_on == "operation_type" and picking_type_ids:
                rule_seq_codes = {
                    code
                    for code in rule.hide_picking_type_ids.mapped("sequence_code")
                    if code
                }
                if (
                    picking_type_ids & set(rule.hide_picking_type_ids.ids)
                    or picking_type_sequence_codes & rule_seq_codes
                ):
                    hide = True

            if hide and rule.report_id and rule.report_id.model == "stock.picking":
                hidden_report_ids.add(rule.report_id.id)

        return hidden_report_ids

    @api.model
    def get_views(self, views, options=None):
        result = super().get_views(views, options=options)

        views_payload = result.get("views") or {}
        form_payload = views_payload.get("form") or {}
        toolbar = form_payload.get("toolbar") or {}
        print_items = toolbar.get("print") or []

        if not print_items:
            return result

        hidden_report_ids = self._get_hidden_report_ids()
        if not hidden_report_ids:
            return result

        filtered_print_items = []
        for item in print_items:
            report_id = self._extract_report_id(item)
            if report_id and report_id in hidden_report_ids:
                continue
            filtered_print_items.append(item)

        toolbar["print"] = filtered_print_items
        form_payload["toolbar"] = toolbar
        views_payload["form"] = form_payload
        result["views"] = views_payload
        return result
