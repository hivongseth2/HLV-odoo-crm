# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Check if group is not already set
            if not vals.get('x_studio_pos_group'):
                # Get date from date_order (usually set) or use current time
                date_order = vals.get('date_order')
                if date_order:
                    dt = fields.Datetime.to_datetime(date_order)
                else:
                    dt = fields.Datetime.now()
                
                # Convert to user's timezone to get correct date
                # context_timestamp converts UTC naive datetime to user's timezone aware datetime
                try:
                     local_dt = fields.Datetime.context_timestamp(self, dt)
                except Exception:
                     # Fallback to UTC if something goes wrong
                     local_dt = dt
                
                # Format: POS/ddmmyy
                group_name = local_dt.strftime("POS/%d%m%y")
                vals['x_studio_pos_group'] = group_name
                
        return super(PosOrder, self).create(vals_list)
