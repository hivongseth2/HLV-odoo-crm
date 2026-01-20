from odoo import models, fields, api
from datetime import timedelta


class BatchPlanningSaleOrderWizard(models.TransientModel):
    _name = 'stock.batch.planning.so.wizard'
    _description = 'Wizard chọn Sale Order cho Kế hoạch Gom Lô'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Kế hoạch', required=True)
    
    # Bộ lọc - Many2many vì SO có nhiều tag
    tag_ids = fields.Many2many('crm.tag', string='Lọc theo Tuyến')
    parent_partner_id = fields.Many2one('res.partner', string='Lọc theo Công ty mẹ',
                                         domain="[('is_company', '=', True)]")
    commitment_date_from = fields.Date(string='Ngày giao từ')
    commitment_date_to = fields.Date(string='Ngày giao đến')
    
    # Danh sách chính (theo bộ lọc)
    sale_order_ids = fields.Many2many('sale.order', 'wizard_so_main_rel', 
                                       'wizard_id', 'order_id', string='Chọn Đơn hàng')
    
    # Danh sách gợi ý (cùng công ty mẹ với SO đã chọn)
    suggested_order_ids = fields.Many2many('sale.order', 'wizard_so_suggested_rel',
                                            'wizard_id', 'order_id', string='Gợi ý cùng Công ty mẹ')

    @api.onchange('tag_ids', 'parent_partner_id', 'commitment_date_from', 'commitment_date_to')
    def _onchange_filters(self):
        """Update domain cho sale_order_ids khi thay đổi bộ lọc"""
        domain = [
            ('state', 'in', ['draft', 'sent', 'sale']),  # SO chưa hoàn thành
            ('batch_plan_id', '=', False),  # Chưa thuộc kế hoạch nào
        ]
        
        # Filter theo tag
        if self.tag_ids:
            domain.append(('tag_ids', 'in', self.tag_ids.ids))
        
        # Filter theo công ty mẹ
        if self.parent_partner_id:
            # Tìm partner có parent_id = công ty mẹ hoặc chính là công ty mẹ
            domain.append('|')
            domain.append(('partner_id.parent_id', '=', self.parent_partner_id.id))
            domain.append(('partner_id', '=', self.parent_partner_id.id))
        
        # Filter theo ngày giao
        if self.commitment_date_from:
            domain.append(('commitment_date', '>=', self.commitment_date_from))
        if self.commitment_date_to:
            domain.append(('commitment_date', '<=', self.commitment_date_to))
        
        return {'domain': {'sale_order_ids': domain}}

    @api.onchange('sale_order_ids')
    def _onchange_sale_order_ids(self):
        """Khi chọn SO, gợi ý các SO khác cùng công ty mẹ"""
        if not self.sale_order_ids:
            self.suggested_order_ids = [(5, 0, 0)]
            return
        
        # Lấy danh sách công ty mẹ của các SO đã chọn
        parent_partners = self.env['res.partner']
        for order in self.sale_order_ids:
            if order.partner_id.parent_id:
                parent_partners |= order.partner_id.parent_id
            elif order.partner_id.is_company:
                parent_partners |= order.partner_id
        
        if not parent_partners:
            self.suggested_order_ids = [(5, 0, 0)]
            return
        
        # Tìm các SO khác cùng công ty mẹ
        domain = [
            ('state', 'in', ['draft', 'sent', 'sale']),
            ('batch_plan_id', '=', False),
            ('id', 'not in', self.sale_order_ids.ids),
            '|',
            ('partner_id.parent_id', 'in', parent_partners.ids),
            ('partner_id', 'in', parent_partners.ids),
        ]
        
        suggested = self.env['sale.order'].search(domain, limit=20)
        self.suggested_order_ids = [(6, 0, suggested.ids)]

    def action_confirm(self):
        """Xác nhận và gán SO vào kế hoạch"""
        self.ensure_one()
        
        # Gộp cả 2 danh sách
        all_orders = self.sale_order_ids | self.suggested_order_ids
        
        if self.batch_plan_id and all_orders:
            # Gán SO vào Plan
            all_orders.write({'batch_plan_id': self.batch_plan_id.id})
            
            # Thêm SO vào Many2many của Plan
            self.batch_plan_id.write({
                'sale_order_ids': [(4, order.id) for order in all_orders]
            })
            
            # Đồng bộ Picking từ SO (nếu đã có)
            self.batch_plan_id._sync_pickings_from_sale_orders()
        
        return {'type': 'ir.actions.act_window_close'}
