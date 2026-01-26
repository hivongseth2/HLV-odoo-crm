# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    child_contact_count = fields.Integer(compute='_compute_child_contact_count', string="Number of Child Contacts")
    hlv_filter_tag_ids = fields.Many2many('hlv.contact.filter.tag', compute='_compute_hlv_filter_tag_ids', 
                                          string="Filter Tags", store=True)

    @api.depends('child_ids')
    def _compute_child_contact_count(self):
        for partner in self:
            partner.child_contact_count = len(partner.child_ids)

    @api.depends('customer_rank', 'supplier_rank', 'parent_id', 'type')
    def _compute_hlv_filter_tag_ids(self):
        tag_obj = self.env['hlv.contact.filter.tag']
        customer_tag = self.env.ref('hlv_contact_refine.tag_customer', raise_if_not_found=False)
        vendor_tag = self.env.ref('hlv_contact_refine.tag_vendor', raise_if_not_found=False)
        main_tag = self.env.ref('hlv_contact_refine.tag_main', raise_if_not_found=False)
        delivery_tag = self.env.ref('hlv_contact_refine.tag_delivery', raise_if_not_found=False)

        for partner in self:
            tag_ids = []
            if partner.customer_rank > 0 and customer_tag:
                tag_ids.append(customer_tag.id)
            if partner.supplier_rank > 0 and vendor_tag:
                tag_ids.append(vendor_tag.id)
            if not partner.parent_id and main_tag:
                tag_ids.append(main_tag.id)
            if partner.type == 'delivery' and delivery_tag:
                tag_ids.append(delivery_tag.id)
            partner.hlv_filter_tag_ids = [(6, 0, tag_ids)]
