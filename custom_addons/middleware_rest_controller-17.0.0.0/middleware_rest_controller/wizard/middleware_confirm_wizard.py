# -*- coding: utf-8 -*-
from odoo import models, fields, http, _
from odoo.exceptions import AccessError


class MiddlewareConfirmWizard(models.TransientModel):
    _name = "middleware.confirm.wizard"
    _description = "Middleware Confirm Wizard"
    message = fields.Html("message")

    def is_audit_in_progress(self, _model=None):
        _true = False
        if bool(_model):
            query = """SELECT IR.* FROM ir_rule AS IR JOIN ir_model AS IM ON IR.model_id = IM.id WHERE IM.model = {model} AND IR.active AND IR.perm_write AND (IR.id IN (SELECT RGR.rule_group_id FROM rule_group_rel AS RGR JOIN res_groups_users_rel AS RGUR ON RGR.group_id = RGUR.gid WHERE RGUR.uid = {guid}) OR IR.global) AND LOWER(IR.name) LIKE 'middleware inventory audit%' LIMIT 1""".format(model="'" + str(_model) + "'", guid=self._uid)
            self._cr.execute(query)
            res = self.browse(row[0] for row in self._cr.fetchall())
            if bool(res):
                _true = True
        return _true

    def raise_xception(self):
        raise AccessError(
            _("Access denied! An inventory audit is in progress, please wait until it gets completed."))

    def however_continue(self):
        order = self.env.context.get("order", None)
        if order == "purchase":
            if self.is_audit_in_progress("purchase.order"):
                return self.raise_xception()
            po_id = self.env.context.get("id")
            po = self.env["purchase.order"].sudo().search([("id", "=", int(po_id))])
            if bool(po):
                ctx = self.env.context.copy()
                ctx.update({"is_not_confirmed": False})
                return po.with_context(ctx).button_confirm()
        elif order == "sale":
            if self.is_audit_in_progress("sale.order"):
                return self.raise_xception()
            so_id = self.env.context.get("id")
            so = self.env["sale.order"].sudo().search([("id", "=", int(so_id))])
            if bool(so):
                ctx = self.env.context.copy()
                ctx.update({"is_not_confirmed": False})
                return so.with_context(ctx).action_confirm()
