# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActions(models.Model):
    _inherit = "ir.actions.actions"

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

    def _extract_active_ids(self):
        active_ids = self.env.context.get("active_ids") or []
        if not active_ids and self.env.context.get("active_id"):
            active_ids = [self.env.context.get("active_id")]
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

    def _extract_picking_type_ids(self):
        picking_type_ids = set()

        active_ids = self._extract_active_ids()
        if active_ids:
            pickings = self.env["stock.picking"].sudo().browse(active_ids).exists()
            picking_type_ids = set(pickings.mapped("picking_type_id").ids)

        if not picking_type_ids:
            default_picking_type_id = self.env.context.get("default_picking_type_id")
            try:
                if default_picking_type_id:
                    picking_type_ids.add(int(default_picking_type_id))
            except (TypeError, ValueError):
                pass

        return picking_type_ids

    def get_bindings(self, model_name):
        res = super().get_bindings(model_name)
        reports = res.get("reports") or res.get("report") or []
        user = self.env.user
        company = self.env.company
        Report = self.env["ir.actions.report"].sudo()

        picking_type_ids = set()
        picking_type_sequence_codes = set()
        if model_name == "stock.picking":
            picking_type_ids = self._extract_picking_type_ids()
            if picking_type_ids:
                picking_types = (
                    self.env["stock.picking.type"]
                    .sudo()
                    .browse(list(picking_type_ids))
                    .exists()
                )
                picking_type_sequence_codes = set(
                    code
                    for code in picking_types.mapped("sequence_code")
                    if code
                )

        custom_reports = (
            self.env["report.access.right"]
            .sudo()
            .search(
                [
                    ("status", "=", "active"),
                ]
            )
        )

        for rec in custom_reports:
            if rec.report_id:
                existing_report_ids = {
                    report_id
                    for report_id in (self._extract_report_id(item) for item in reports)
                    if report_id
                }
                if rec.report_id.id not in existing_report_ids:
                    reports.append({"id": rec.report_id.id})

        visible_reports = []
        for rep in reports:
            rep_id = self._extract_report_id(rep)

            add_to_visible = True
            if rep_id:
                r = Report.browse(rep_id)
                if r.exists():
                    access_rules = (
                        self.env["report.access.right"]
                        .sudo()
                        .search(
                            [
                                ("report_id", "=", rep_id),
                                ("status", "=", "active"),
                            ]
                        )
                    )
                    for rule in access_rules:
                        if rule.hide_based_on == "user" and user in rule.hide_user_ids:
                            add_to_visible = False
                        elif (
                            rule.hide_based_on == "company"
                            and company in rule.hide_company_ids
                        ):
                            add_to_visible = False
                        elif (
                            rule.hide_based_on == "operation_type"
                            and model_name == "stock.picking"
                            and picking_type_ids
                            and (
                                bool(picking_type_ids & set(rule.hide_picking_type_ids.ids))
                                or bool(
                                    picking_type_sequence_codes
                                    & set(
                                        code
                                        for code in rule.hide_picking_type_ids.mapped("sequence_code")
                                        if code
                                    )
                                )
                            )
                        ):
                            add_to_visible = False

                        if not add_to_visible:
                            break

            if add_to_visible:
                visible_reports.append(rep)

        res["report"] = visible_reports
        res["reports"] = visible_reports
        return res
