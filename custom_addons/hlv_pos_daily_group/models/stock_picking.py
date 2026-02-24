# -*- coding: utf-8 -*-
from odoo import models, api, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Nếu phiếu đang được tạo không có pos_order_id
            if 'pos_order_id' not in vals or not vals.get('pos_order_id'):
                # 1. Tìm pos_order_id từ phiếu cha (nếu tạo từ procurement/backorder/etc)
                # Odoo chuẩn thường link pickings qua group_id (procurement group)
                group_id = vals.get('group_id')
                if group_id:
                    # Tìm phiếu khác trong cùng group có pos_order_id
                    related_picking = self.env['stock.picking'].sudo().search([
                        ('group_id', '=', group_id),
                        ('pos_order_id', '!=', False)
                    ], limit=1)
                    if related_picking:
                        vals['pos_order_id'] = related_picking.pos_order_id.id
                        continue
                        
                    # Hoặc tìm trực tiếp từ POS order tên giống group name
                    group = self.env['procurement.group'].sudo().browse(group_id)
                    if group.exists() and group.name:
                        pos_order = self.env['pos.order'].sudo().search([('name', '=', group.name)], limit=1)
                        if pos_order:
                            vals['pos_order_id'] = pos_order.id
                            continue
                
                # 2. Tìm pos_order_id từ sale_id nếu group_id map ra POS (nhiều POS module link sale_id)
                # (Dự phòng ngầm)
        
        return super(StockPicking, self).create(vals_list)
