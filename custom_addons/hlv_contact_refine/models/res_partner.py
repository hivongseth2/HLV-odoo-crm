# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    child_contact_count = fields.Integer(compute='_compute_child_contact_count', string="Number of Child Contacts")
    hlv_filter_tag_ids = fields.Many2many('hlv.contact.filter.tag', compute='_compute_hlv_filter_tag_ids', 
                                          string="Filter Tags", store=True)
    hlv_partner_type = fields.Selection([
        ('company', 'Công ty'),
        ('person', 'Cá nhân')
    ], compute='_compute_hlv_partner_type', string="Loại liên hệ", store=True)

    @api.depends('is_company')
    def _compute_hlv_partner_type(self):
        for partner in self:
            partner.hlv_partner_type = 'company' if partner.is_company else 'person'

    @api.depends('child_ids')
    def _compute_child_contact_count(self):
        for partner in self:
            partner.child_contact_count = len(partner.child_ids)

    @api.depends('customer_rank', 'supplier_rank', 'parent_id', 'type')
    def _compute_hlv_filter_tag_ids(self):
        try:
            customer_tag = self.env.ref('hlv_contact_refine.tag_customer', raise_if_not_found=False)
            vendor_tag = self.env.ref('hlv_contact_refine.tag_vendor', raise_if_not_found=False)
            main_tag = self.env.ref('hlv_contact_refine.tag_main', raise_if_not_found=False)
            delivery_tag = self.env.ref('hlv_contact_refine.tag_delivery', raise_if_not_found=False)
        except Exception:
            # Fallback nếu transaction đã fail hoặc data chưa load
            for partner in self:
                partner.hlv_filter_tag_ids = [(5, 0, 0)]
            return

        for partner in self:
            tag_ids = []
            cus_rank = getattr(partner, 'customer_rank', 0)
            sup_rank = getattr(partner, 'supplier_rank', 0)
            
            # 1. Customer: check rank OR actual sales order
            if cus_rank > 0:
                if customer_tag: tag_ids.append(customer_tag.id)
            elif partner.id:
                if self.env['sale.order'].search_count([('partner_id', 'child_of', partner.id)], limit=1):
                    if customer_tag: tag_ids.append(customer_tag.id)

            # 2. Vendor: check rank OR actual purchase order
            if sup_rank > 0:
                if vendor_tag: tag_ids.append(vendor_tag.id)
            elif partner.id:
                if self.env['purchase.order'].search_count([('partner_id', 'child_of', partner.id)], limit=1):
                    if vendor_tag: tag_ids.append(vendor_tag.id)
            
            # 3. Main Contact vs Delivery Address
            if not partner.parent_id:
                if main_tag: tag_ids.append(main_tag.id)
            
            if partner.type == 'delivery':
                if delivery_tag: tag_ids.append(delivery_tag.id)
                
            partner.hlv_filter_tag_ids = [(6, 0, tag_ids)]
