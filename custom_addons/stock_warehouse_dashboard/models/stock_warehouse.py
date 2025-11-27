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
            # 1. Tìm đơn hàng MISA hôm nay
            misa_domain = [
                ('warehouse_id', '=', warehouse.id),
                ('x_studio_misa_order_date', '=', today),
                ('state', 'in', ['sale', 'done'])
            ]
            
            orders = SaleOrder.search(misa_domain)
            total = len(orders)
            
            # 2. Thống kê theo trạng thái giao hàng
            full = len(orders.filtered(lambda o: o.delivery_status == 'full'))
            partial = len(orders.filtered(lambda o: o.delivery_status == 'partial'))
            not_full = total - full

            # 3. Thống kê in ấn (Optional: để hiển thị con số chưa in lên dashboard nếu cần)
            not_printed = len(orders.filtered(lambda o: o.picking_slip_print_count == 0))

            final_data = {
                'misa': {
                    'total': total,
                    'full': full,
                    'partial': partial,
                    'not_full': not_full,
                    'not_printed': not_printed # Số lượng chưa in
                }
            }
            warehouse.warehouse_dashboard_data = json.dumps(final_data)

    # Hàm mở danh sách Đơn hàng (Sale Order)
    def open_misa_sale_orders(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        filter_type = self.env.context.get('misa_filter', 'all')
        
        # Domain cơ bản
        domain = [
            ('warehouse_id', '=', self.id),
            ('x_studio_misa_order_date', '=', today),
            ('state', 'in', ['sale', 'done'])
        ]
        
        name = f"Đơn MISA {today}"
        ctx = {'create': False}

        # Xử lý Filter
        if filter_type == 'full':
            domain.append(('delivery_status', '=', 'full'))
            name += " (Đã xong)"
        elif filter_type == 'partial':
            domain.append(('delivery_status', '=', 'partial'))
            name += " (1 Phần)"
        elif filter_type == 'not_full':
            domain.append(('delivery_status', '!=', 'full'))
            name += " (Tồn/Chưa giao)"
        elif filter_type == 'not_printed':
            # Nếu bấm vào nút in -> Lọc ra đơn chưa in
            # Cách dùng search_default trong context để kích hoạt bộ lọc XML
            ctx['search_default_filter_not_printed'] = 1
            name += " (Chưa in)"
            
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': domain,
            'context': ctx
        }
        
    # Giữ hàm mở hoạt động kho
    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        action['context'] = {'default_warehouse_id': self.id}
        return action