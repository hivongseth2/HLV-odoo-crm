# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActions(models.Model):
    _inherit = "ir.actions.actions"

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
        if model_name == "stock.picking":
            picking_type_ids = self._extract_picking_type_ids()

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
                if rec.report_id.id not in [
                    r["id"] if isinstance(r, dict) else r for r in reports
                ]:
                    reports.append({"id": rec.report_id.id})

        visible_reports = []
        for rep in reports:
            rep_id = None

            if isinstance(rep, int):
                rep_id = rep
            elif isinstance(rep, str) and rep.strip().isdigit():
                rep_id = int(rep)
            elif isinstance(rep, (list, tuple)) and rep and isinstance(rep[0], int):
                rep_id = rep[0]
            elif isinstance(rep, dict) and "id" in rep and isinstance(rep["id"], int):
                rep_id = rep["id"]

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
                            and bool(
                                picking_type_ids
                                & set(rule.hide_picking_type_ids.ids)
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
