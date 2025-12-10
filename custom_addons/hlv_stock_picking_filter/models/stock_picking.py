# -*- coding: utf-8 -*-
from odoo import models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def search_by_field_text(self, field_name, search_value, limit=None):
        """
        Tìm kiếm stock.picking theo field text (ilike).
        Trả về danh sách IDs.
        
        :param field_name: Tên field cần tìm (name, origin, partner_id.name, etc.)
        :param search_value: Giá trị cần tìm
        :param limit: Giới hạn số kết quả
        :return: List of picking IDs
        """
        if not search_value:
            return []
        
        # Handle relational fields
        if '.' in field_name:
            parts = field_name.split('.')
            if parts[0] == 'partner_id' and parts[1] == 'name':
                domain = [('partner_id.name', 'ilike', search_value)]
            elif parts[0] == 'location_id' and parts[1] == 'name':
                domain = [('location_id.complete_name', 'ilike', search_value)]
            elif parts[0] == 'location_dest_id' and parts[1] == 'name':
                domain = [('location_dest_id.complete_name', 'ilike', search_value)]
            elif parts[0] == 'batch_id' and parts[1] == 'name':
                domain = [('batch_id.name', 'ilike', search_value)]
            else:
                domain = [(field_name, 'ilike', search_value)]
        else:
            domain = [(field_name, 'ilike', search_value)]
        
        pickings = self.search(domain, limit=limit)
        return pickings.ids

    @api.model
    def search_by_date_range(self, field_name, date_from, date_to):
        """
        Tìm kiếm stock.picking theo khoảng ngày.
        
        :param field_name: Tên field ngày (scheduled_date, date_deadline, etc.)
        :param date_from: Ngày bắt đầu (string YYYY-MM-DD)
        :param date_to: Ngày kết thúc (string YYYY-MM-DD)
        :return: List of picking IDs
        """
        domain = []
        
        if date_from:
            domain.append((field_name, '>=', date_from + ' 00:00:00'))
        if date_to:
            domain.append((field_name, '<=', date_to + ' 23:59:59'))
        
        if not domain:
            return []
        
        pickings = self.search(domain)
        return pickings.ids

    @api.model
    def search_by_state(self, state_value):
        """
        Tìm kiếm stock.picking theo trạng thái.
        
        :param state_value: Giá trị state (draft, waiting, confirmed, assigned, done, cancel)
        :return: List of picking IDs
        """
        if not state_value:
            return []
        
        pickings = self.search([('state', '=', state_value)])
        return pickings.ids
