from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # 1. Fix lỗi picking_type_ids one2many
    picking_type_ids = fields.One2many(
        'stock.picking.type', 
        'warehouse_id', 
        string='Operation Types'
    )

    # 2. Trường chứa JSON data cho Dashboard
    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids', 'picking_type_ids.count_picking_ready')
    def _compute_warehouse_dashboard_data(self):
        Picking = self.env['stock.picking']
        SaleOrder = self.env['sale.order']
        today = fields.Date.context_today(self)

        for warehouse in self:
            # --- PHẦN 1: TÍNH TOÁN HOẠT ĐỘNG KHO ---
            ops_data = []
            operations = warehouse.picking_type_ids.sorted(key=lambda r: r.sequence)
            
            for op in operations:
                # Đếm số lượng draft (Odoo không đếm sẵn)
                count_draft = Picking.search_count([('picking_type_id', '=', op.id), ('state', '=', 'draft')])
                
                # Màu sắc nút
                btn_color = 'btn-secondary'
                if op.code == 'incoming': btn_color = 'btn-primary'
                elif op.code == 'outgoing': btn_color = 'btn-success'
                elif op.code == 'internal': btn_color = 'btn-warning'

                ops_data.append({
                    'id': op.id,
                    'name': op.name,
                    'code': op.code,
                    'count_ready': op.count_picking_ready,
                    'count_late': op.count_picking_late,
                    'count_waiting': op.count_picking_waiting,
                    'count_draft': count_draft,
                    'btn_color': btn_color,
                })

            # --- PHẦN 2: TÍNH TOÁN ĐƠN HÀNG MISA ---
            # Tìm đơn hàng thuộc kho này & ngày MISA là hôm nay & đã xác nhận
            misa_domain = [
                ('warehouse_id', '=', warehouse.id),
                ('x_studio_misa_order_date', '=', today),
                ('state', 'in', ['sale', 'done'])
            ]
            
            # Lấy danh sách đơn
            orders = SaleOrder.search(misa_domain)
            total_orders = len(orders)
            
            # Phân loại theo trạng thái giao hàng (delivery_status)
            full_orders = orders.filtered(lambda o: o.delivery_status == 'full')
            partial_orders = orders.filtered(lambda o: o.delivery_status == 'partial')
            
            # Số đơn tồn (Chưa giao hoặc Giao chưa hết)
            not_full_count = total_orders - len(full_orders)

            misa_stats = {
                'total': total_orders,
                'full': len(full_orders),
                'partial': len(partial_orders),
                'not_full': not_full_count
            }

            # Đóng gói JSON
            final_data = {
                'operations': ops_data,
                'misa': misa_stats
            }
            warehouse.warehouse_dashboard_data = json.dumps(final_data)

    # --- HÀM 1: MỞ VIEW HOẠT ĐỘNG KHO ---
    def open_picking_type_view(self):
        self.ensure_one()
        p_type_id = self.env.context.get('picking_type_id')
        view_type = self.env.context.get('view_type', 'all')
        
        if not p_type_id: return

        picking_type = self.env['stock.picking.type'].browse(p_type_id)
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action['name'] = f"{picking_type.name} ({view_type})"
        action['context'] = {
            'default_picking_type_id': p_type_id,
            'contact_display': 'partner_address',
        }
        
        base_domain = [('picking_type_id', '=', p_type_id)]
        
        if view_type == 'ready': return picking_type.get_action_picking_tree_ready()
        elif view_type == 'waiting': return picking_type.get_action_picking_tree_waiting()
        elif view_type == 'late': return picking_type.get_action_picking_tree_late()
        elif view_type == 'draft': action['domain'] = base_domain + [('state', '=', 'draft')]
        elif view_type == 'done': action['domain'] = base_domain + [('state', '=', 'done')]
        else: action['domain'] = base_domain
            
        return action

    # --- HÀM 2: MỞ DANH SÁCH Picking Type CỦA KHO ---
    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        action['context'] = {'default_warehouse_id': self.id}
        return action

    # --- HÀM 3: MỞ ĐƠN HÀNG MISA ---
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
            # Khác full nghĩa là pending hoặc partial
            domain.append(('delivery_status', '!=', 'full'))
            name += " (Chưa xong)"
            
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'create': False}
        }