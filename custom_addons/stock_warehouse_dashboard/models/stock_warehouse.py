from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    picking_type_ids = fields.One2many('stock.picking.type', 'warehouse_id', string='Operation Types')
    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids')
    def _compute_warehouse_dashboard_data(self):
        SaleOrder = self.env['sale.order']
        today = fields.Date.context_today(self)

        for warehouse in self:
            misa_domain = [
                ('warehouse_id', '=', warehouse.id),
                ('x_studio_misa_order_date', '=', today),
                ('state', 'in', ['sale', 'done'])
            ]
            orders = SaleOrder.search(misa_domain)
            total_orders = len(orders)
            
            # Logic tính toán (giữ nguyên)
            full_orders = len(orders.filtered(lambda o: o.delivery_status == 'full'))
            partial_orders = len(orders.filtered(lambda o: o.delivery_status == 'partial'))
            # not_full = Tổng - Full (tức là gồm cả Partial và Pending)
            not_full_count = total_orders - full_orders

            final_data = {
                'misa': {
                    'total': total_orders,
                    'full': full_orders,
                    'partial': partial_orders,
                    'not_full': not_full_count
                }
            }
            warehouse.warehouse_dashboard_data = json.dumps(final_data)

    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        action['context'] = {'default_warehouse_id': self.id}
        return action

    def open_misa_sale_orders(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        filter_type = self.env.context.get('misa_filter', 'all')
        
        domain = [
            ('warehouse_id', '=', self.id),
            ('x_studio_misa_order_date', '=', today),
            ('state', 'in', ['sale', 'done'])
        ]
        
        name = f"Đơn MISA {today}"

        if filter_type == 'full':
            domain.append(('delivery_status', '=', 'full'))
            name += " (Đã xong)"
        elif filter_type == 'partial':
            domain.append(('delivery_status', '=', 'partial'))
            name += " (1 Phần)"
        elif filter_type == 'not_full':
            domain.append(('delivery_status', '!=', 'full'))
            # SỬA TÊN CỬA SỔ Ở ĐÂY
            name += " (Chưa giao / Chưa xong)"
            
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'create': False}
        }