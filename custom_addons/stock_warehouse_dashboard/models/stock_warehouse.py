from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # Trường chứa dữ liệu JSON để hiển thị lên Kanban
    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids', 'picking_type_ids.count_picking_ready', 
                 'picking_type_ids.count_picking_late', 'picking_type_ids.count_picking_waiting')
    def _compute_warehouse_dashboard_data(self):
        for warehouse in self:
            data = []
            # Lặp qua tất cả các loại hoạt động thuộc kho này (Dynamic, không hardcode)
            # Sắp xếp theo sequence để đảm bảo thứ tự hiển thị đúng cấu hình
            operations = warehouse.picking_type_ids.sorted(key=lambda r: r.sequence)
            
            for op in operations:
                # Logic màu sắc tương tự Odoo chuẩn
                color_class = 'text-primary'
                if op.code == 'incoming': color_class = 'text-primary' # Nhập - Xanh
                elif op.code == 'outgoing': color_class = 'text-success' # Xuất - Xanh lá
                elif op.code == 'internal': color_class = 'text-warning' # Nội bộ - Vàng
                else: color_class = 'text-muted'

                data.append({
                    'id': op.id,
                    'name': op.name,
                    'code': op.code,
                    'count_ready': op.count_picking_ready, # Cần xử lý
                    'count_late': op.count_picking_late,   # Trễ
                    'count_waiting': op.count_picking_waiting, # Đang chờ
                    'color_class': color_class,
                })
            
            # Dump dữ liệu ra chuỗi JSON để View XML đọc được
            warehouse.warehouse_dashboard_data = json.dumps(data)