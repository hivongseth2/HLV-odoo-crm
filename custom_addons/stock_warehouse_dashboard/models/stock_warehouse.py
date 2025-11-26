from odoo import models, fields, api
import json

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    picking_type_ids = fields.One2many(
        'stock.picking.type', 
        'warehouse_id', 
        string='Operation Types'
    )

    warehouse_dashboard_data = fields.Text(compute='_compute_warehouse_dashboard_data')

    @api.depends('picking_type_ids', 'picking_type_ids.count_picking_ready', 'picking_type_ids.sequence')
    def _compute_warehouse_dashboard_data(self):
        for warehouse in self:
            data = []
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

    # --- HÀM MỚI THÊM VÀO ĐỂ XỬ LÝ CLICK ---
    def open_picking_type_view(self):
        self.ensure_one()
        # Lấy ID loại hoạt động từ context (do XML gửi lên)
        p_type_id = self.env.context.get('picking_type_id')
        view_type = self.env.context.get('view_type', 'all') # 'ready' hoặc 'all'
        
        if not p_type_id:
            return

        picking_type = self.env['stock.picking.type'].browse(p_type_id)

        if view_type == 'ready':
            # Nếu bấm vào số lượng -> Gọi hàm chuẩn của Odoo để mở các phiếu Cần xử lý
            return picking_type.get_action_picking_tree_ready()
        
        else:
            # Nếu bấm vào tên -> Mở tất cả phiếu của loại này
            action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
            action['name'] = picking_type.name # Đổi tên cửa sổ thành tên hoạt động
            action['domain'] = [('picking_type_id', '=', p_type_id)]
            action['context'] = {
                'default_picking_type_id': p_type_id,
                'contact_display': 'partner_address',
            }
            return action