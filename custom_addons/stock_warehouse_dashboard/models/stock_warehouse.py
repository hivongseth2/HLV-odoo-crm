from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    picking_type_ids = fields.One2many('stock.picking.type', 'warehouse_id', string='Operation Types')
    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids')
    def _compute_warehouse_dashboard_data(self):
        Picking = self.env['stock.picking']
        today = fields.Date.context_today(self)

        for warehouse in self:
            # 1. Lọc các phiếu xuất kho (Outgoing) thuộc kho này & Ngày MISA hôm nay
            domain = [
                ('picking_type_id.warehouse_id', '=', warehouse.id),
                ('picking_type_id.code', '=', 'outgoing'), # Chỉ lấy phiếu xuất
                ('x_misa_date', '=', today),
                ('state', 'not in', ['cancel', 'draft']) # Đã xác nhận trở lên
            ]
            
            # 2. Lấy dữ liệu
            pickings = Picking.search(domain)
            total = len(pickings)
            
            # Phân loại theo trạng thái in ấn
            not_printed = len(pickings.filtered(lambda p: p.print_count == 0))
            printed = total - not_printed

            # Phân loại theo trạng thái kho (Xong / Chưa xong)
            done = len(pickings.filtered(lambda p: p.state == 'done'))
            pending = total - done

            final_data = {
                'misa': {
                    'total': total,
                    'not_printed': not_printed, # Chưa in
                    'printed': printed,         # Đã in
                    'done': done,               # Đã xuất kho xong
                    'pending': pending          # Đang chờ xuất
                }
            }
            warehouse.warehouse_dashboard_data = json.dumps(final_data)

    # --- HÀM MỞ DANH SÁCH PHIẾU KHO ---
    def open_misa_pickings(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        filter_type = self.env.context.get('misa_filter', 'all')
        
        # Domain cơ bản: Kho này + Xuất kho + Ngày MISA
        domain = [
            ('picking_type_id.warehouse_id', '=', self.id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('x_misa_date', '=', today),
            ('state', 'not in', ['cancel', 'draft'])
        ]
        
        name = f"Phiếu xuất {today}"
        ctx = {'create': False}

        # Xử lý các bộ lọc khi bấm vào số liệu
        if filter_type == 'not_printed':
            domain.append(('print_count', '=', 0))
            name += " (Chưa in)"
        elif filter_type == 'printed':
            domain.append(('print_count', '>', 0))
            name += " (Đã in)"
        elif filter_type == 'done':
            domain.append(('state', '=', 'done'))
            name += " (Đã xuất)"
        elif filter_type == 'pending':
            domain.append(('state', '!=', 'done'))
            name += " (Chờ xuất)"
            
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking', # Mở model stock.picking thay vì sale.order
            'view_mode': 'list,form',
            'domain': domain,
            'context': ctx
        }
    
    # Giữ lại hàm mở cấu hình hoạt động kho
    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        action['context'] = {'default_warehouse_id': self.id}
        return action