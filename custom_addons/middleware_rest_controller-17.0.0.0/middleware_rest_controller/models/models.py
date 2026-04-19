# -*- coding: utf-8 -*-
import json
import psycopg2
from odoo.exceptions import AccessError
from odoo import api, models, fields, _


class IrRule(models.Model):
    _inherit = "ir.rule"

    def _make_access_error(self, operation, records):
        _model = records._name
        if bool(_model):
            query = """SELECT IR.* FROM ir_rule AS IR JOIN ir_model AS IM ON IR.model_id = IM.id WHERE IM.model = {model} AND IR.active AND IR.perm_{mode} AND (IR.id IN (SELECT RGR.rule_group_id FROM rule_group_rel AS RGR JOIN res_groups_users_rel AS RGUR ON RGR.group_id = RGUR.gid WHERE RGUR.uid = {guid}) OR IR.global) AND LOWER(IR.name) LIKE 'middleware inventory audit%' LIMIT 1""".format(
                model="'" + str(_model) + "'", mode=operation, guid=self._uid)
            self._cr.execute(query)
            res = self.browse(row[0] for row in self._cr.fetchall())
            if bool(res):
                raise AccessError(_("Access denied! An inventory audit is in progress, please wait until it gets completed."))
        return super(IrRule, self)._make_access_error(operation, records)


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        is_not_confirmed = self.env.context.get("is_not_confirmed", True)
        if bool(is_not_confirmed):
            po_id = self.id
            po = self.env["purchase.order"].sudo().search([("id", "=", int(po_id))])
            if bool(po):
                x_product_name = None
                for order in po:
                    for each in order.order_line:
                        if "product_id" in each:
                            if each.product_id[0].type != "product":
                                for _each in order.order_line:
                                    if _each.product_id[0].type == "product":
                                        x_product_name = each.product_id[0].name
                if bool(x_product_name):
                    _message = _(
                        "A purchase order must contain all line items of type product(i.e. Storable Product). But the type of <b>" + str(
                            x_product_name) + "</b> is different. Are you sure to continue?")
                    wizard = self.env["middleware.confirm.wizard"].sudo().create({"message": _message})
                    if bool(wizard):
                        ctx = {"order": "purchase", "id": self.id}
                        return {
                            "name": _("Middleware Alert"),
                            "type": "ir.actions.act_window",
                            "view_mode": "form",
                            "res_model": "middleware.confirm.wizard",
                            "res_id": wizard.id,
                            "target": "new",
                            'context': ctx
                        }
        return super(PurchaseOrder, self).button_confirm()


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        is_not_confirmed = self.env.context.get("is_not_confirmed", True)
        if bool(is_not_confirmed):
            so_id = self.id
            so = self.env["sale.order"].sudo().search([("id", "=", int(so_id))])
            if bool(so):
                x_product_name = None
                for order in so:
                    for each in order.order_line:
                        if "product_id" in each:
                            if each.product_id[0].type != "product":
                                for _each in order.order_line:
                                    if _each.product_id[0].type == "product":
                                        x_product_name = each.product_id[0].name
                if bool(x_product_name):
                    _message = _(
                        "A sales order must contain all line items of type product(i.e. Storable Product). But the type of <b>" + str(
                            x_product_name) + "</b> is different. Are you sure to continue?")
                    wizard = self.env["middleware.confirm.wizard"].sudo().create({"message": _message})
                    if bool(wizard):
                        ctx = {"order": "sale", "id": self.id}
                        return {
                            "name": _("Middleware Alert"),
                            "type": "ir.actions.act_window",
                            "view_mode": "form",
                            "res_model": "middleware.confirm.wizard",
                            "res_id": wizard.id,
                            "target": "new",
                            'context': ctx
                        }
        return super(SaleOrder, self).action_confirm()


class Jsonb(fields.Field):
    type = "json"
    column_type = ("json", "json")

    def convert_to_column(self, value, record, values=None, validate=True):
        return value if value is None else psycopg2.extras.Json(value)


class MiddlewareOpenPicking(models.Model):
    _name = "middleware.open.picking"
    _description = "Middleware Open Picking"

    so_id = fields.Integer()
    picker_id = fields.Integer()
    assigned_by = fields.Integer()
    line_items = Jsonb()
    lots_serials_nots_quantities = Jsonb()
    status = fields.Char()
    barcode_format = fields.Char()


class ProductTemplate(models.Model):
    _inherit = "product.template"

    middleware_min_stock = fields.Float(string="Minimum Stock")

    @api.model_create_multi
    def create(self, vals_list):
        _vals_list = list()
        for vals in vals_list:
            _tmp = vals
            if "company_id" not in vals or not bool(vals["company_id"]):
                _tmp["company_id"] = self.env.company.id
            _vals_list.append(_tmp)
        return super(ProductTemplate, self).create(_vals_list)
