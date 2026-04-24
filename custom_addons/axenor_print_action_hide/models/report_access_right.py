# -*- coding: utf-8 -*-
from odoo import models, fields


class ReportAccessRight(models.Model):
    _name = "report.access.right"
    _description = "Report Access Rights"
    _rec_name = "report_id"

    report_id = fields.Many2one(
        "ir.actions.report",
        string="Report",
        required=True,
        ondelete="cascade",
    )
    hide_based_on = fields.Selection(
        [
            ("user", "Users"),
            ("company", "Companies"),
        ],
        string="Hide Report Based On",
    )
    hide_user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Hidden for Users",
    )
    hide_company_ids = fields.Many2many(
        comodel_name="res.company",
        string="Hidden for Companies",
    )

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("inactive", "Inactive"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    # --- Button Actions ---
    def action_activate(self):
        self.write(
            {
                "status": "active",
            }
        )

    def action_inactivate(self):
        self.write(
            {
                "status": "inactive",
            }
        )

    def action_reset_draft(self):
        self.write(
            {
                "status": "draft",
            }
        )
