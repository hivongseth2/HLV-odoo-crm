# -*- coding: utf-8 -*-
from odoo import models, fields


class ReportAccessRight(models.Model):
    _name = "report.access.right"
    _description = "Quyền truy cập báo cáo"
    _rec_name = "report_id"

    report_id = fields.Many2one(
        "ir.actions.report",
        string="Báo cáo",
        required=True,
        ondelete="cascade",
    )
    hide_based_on = fields.Selection(
        [
            ("user", "Người dùng"),
            ("company", "Công ty"),
            ("operation_type", "Loại hoạt động"),
        ],
        string="Ẩn báo cáo theo",
    )
    hide_user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Ẩn cho người dùng",
    )
    hide_company_ids = fields.Many2many(
        comodel_name="res.company",
        string="Ẩn cho công ty",
    )
    hide_picking_type_ids = fields.Many2many(
        comodel_name="stock.picking.type",
        string="Ẩn cho loại hoạt động",
    )

    status = fields.Selection(
        [
            ("draft", "Nháp"),
            ("active", "Hoạt động"),
            ("inactive", "Ngừng"),
        ],
        string="Trạng thái",
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
