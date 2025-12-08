from odoo import models, fields, api
import json

# 1. Wizard chọn ngày (Popup)
class MisaDateWizard(models.TransientModel):
    _name = 'misa.date.wizard'
    _description = 'Chọn ngày xem Dashboard'

    date = fields.Date(string='Chọn ngày', required=True, default=fields.Date.context_today)

    def action_apply(self):
        # Reload lại trang và gắn ngày vào bộ nhớ tạm (Context)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.warehouse',
            'view_mode': 'kanban,form',
            'target': 'current', 
            'context': {'misa_selected_date': self.date} 
        }

# 2. Logic chính
class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    picking_type_ids = fields.One2many('stock.picking.type', 'warehouse_id', string='Operation Types')
    
    # store=False để luôn tính toán lại khi context thay đổi
    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data', store=False)

    def _compute_warehouse_dashboard_data(self):
        SaleOrder = self.env['sale.order']
        
        # Kiểm tra xem có ngày trong context không
        ctx_date = self.env.context.get('misa_selected_date')
        if ctx_date:
            target_date = fields.Date.to_date(ctx_date)
            is_today_flag = False
        else:
            target_date = fields.Date.context_today(self)
            is_today_flag = True

        for warehouse in self:
            misa_domain = [
                ('warehouse_id', '=', warehouse.id),
                ('x_studio_misa_order_date', '=', target_date),
                ('state', 'in', ['sale', 'done'])
            ]
            orders = SaleOrder.search(misa_domain)
            
            total_orders = len(orders)
            full_orders = len(orders.filtered(lambda o: o.delivery_status == 'full'))
            partial_orders = len(orders.filtered(lambda o: o.delivery_status == 'partial'))
            not_full_count = total_orders - full_orders

            final_data = {
                'misa': {
                    'total': total_orders,
                    'full': full_orders,
                    'partial': partial_orders,
                    'not_full': not_full_count,
                    # Truyền thêm dữ liệu để hiển thị giao diện
                    'is_today': is_today_flag,
                    'date_display': target_date.strftime('%d/%m/%Y')
                }
            }
            warehouse.warehouse_dashboard_data = json.dumps(final_data)

    # Hàm mở popup chọn ngày
    def action_open_date_picker(self):
        ctx_date = self.env.context.get('misa_selected_date')
        return {
            'name': 'Chọn ngày xem báo cáo',
            'type': 'ir.actions.act_window',
            'res_model': 'misa.date.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_date': ctx_date or fields.Date.context_today(self)}
        }

    # Các hàm mở list view giữ nguyên logic cũ, chỉ thêm lấy ngày từ context
    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        action['context'] = {'default_warehouse_id': self.id}
        return action

    def open_misa_sale_orders(self):
        self.ensure_one()
        ctx_date = self.env.context.get('misa_selected_date')
        target_date = fields.Date.to_date(ctx_date) if ctx_date else fields.Date.context_today(self)
        filter_type = self.env.context.get('misa_filter', 'all')
        
        domain = [
            ('warehouse_id', '=', self.id),
            ('x_studio_misa_order_date', '=', target_date),
            ('state', 'in', ['sale', 'done'])
        ]
        
        name = f"Đơn MISA {target_date.strftime('%d/%m')}"

        if filter_type == 'full':
            domain.append(('delivery_status', '=', 'full'))
            name += " (Đã xong)"
        elif filter_type == 'partial':
            domain.append(('delivery_status', '=', 'partial'))
            name += " (1 Phần)"
        elif filter_type == 'not_full':
            domain.append(('delivery_status', '!=', 'full'))
            name += " (Chưa giao / Chưa xong)"
            
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': domain,
            # Truyền tiếp context để giữ ngày khi quay lại
            'context': {'create': False, 'misa_selected_date': target_date}
        }