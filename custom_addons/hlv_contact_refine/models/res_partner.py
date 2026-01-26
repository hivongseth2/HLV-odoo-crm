# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    child_contact_count = fields.Integer(compute='_compute_child_contact_count', string="Number of Child Contacts")

    @api.depends('child_ids')
    def _compute_child_contact_count(self):
        for partner in self:
            partner.child_contact_count = len(partner.child_ids)
