from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # --- KHẮC PHỤC LỖI TẠI ĐÂY ---
    # Khai báo trường One2many liên kết ngược từ Picking Type về Warehouse
    # Để hệ thống hiểu 'picking_type_ids' là gì.
    picking_type_ids = fields.One2many(
        'stock.picking.type', 
        'warehouse_id', 
        string='Operation Types'
    )

    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids', 
                 'picking_type_ids.count_picking_ready', 
                 'picking_type_ids.count_picking_late', 
                 'picking_type_ids.count_picking_waiting',
                 'picking_type_ids.sequence') # Thêm sequence để trigger khi sắp xếp lại
    def _compute_warehouse_dashboard_data(self):
        for warehouse in self:
            data = []
            # Bây giờ có thể gọi self.picking_type_ids an toàn
            operations = warehouse.picking_type_ids.sorted(key=lambda r: r.sequence)
            
            for op in operations:
                color_class = 'text-muted'
                if op.code == 'incoming': color_class = 'text-primary'
                elif op.code == 'outgoing': color_class = 'text-success'
                elif op.code == 'internal': color_class = 'text-warning'

                data.append({
                    'id': op.id,
                    'name': op.name,
                    'code': op.code,
                    'count_ready': op.count_picking_ready,
                    'count_late': op.count_picking_late,
                    'count_waiting': op.count_picking_waiting,
                    'color_class': color_class,
                })
            
            warehouse.warehouse_dashboard_data = json.dumps(data)