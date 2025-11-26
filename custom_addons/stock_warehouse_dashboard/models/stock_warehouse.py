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
        Picking = self.env['stock.picking']
        for warehouse in self:
            data = []
            operations = warehouse.picking_type_ids.sorted(key=lambda r: r.sequence)
            for op in operations:
                # Tính toán thêm các chỉ số mà Odoo mặc định không tính sẵn cho Dashboard
                # Lưu ý: search_count có thể ảnh hưởng hiệu năng nếu dữ liệu quá lớn
                count_draft = Picking.search_count([('picking_type_id', '=', op.id), ('state', '=', 'draft')])
                # count_done = Picking.search_count([('picking_type_id', '=', op.id), ('state', '=', 'done')]) # Tạm ẩn Done vì số lượng thường rất lớn, gây chậm
                
                # Logic màu sắc
                color_class = 'text-muted'
                btn_color = 'btn-secondary'
                if op.code == 'incoming': 
                    color_class = 'text-primary'
                    btn_color = 'btn-primary'
                elif op.code == 'outgoing': 
                    color_class = 'text-success'
                    btn_color = 'btn-success'
                elif op.code == 'internal': 
                    color_class = 'text-warning'
                    btn_color = 'btn-warning'

                data.append({
                    'id': op.id,
                    'name': op.name,
                    'code': op.code,
                    'count_ready': op.count_picking_ready,     # Cần làm (Sẵn sàng)
                    'count_waiting': op.count_picking_waiting, # Đang chờ (Chờ hàng)
                    'count_late': op.count_picking_late,       # Trễ
                    'count_draft': count_draft,                # Nháp
                    'color_class': color_class,
                    'btn_color': btn_color,
                })
            warehouse.warehouse_dashboard_data = json.dumps(data)

    def open_picking_type_view(self):
        self.ensure_one()
        p_type_id = self.env.context.get('picking_type_id')
        view_type = self.env.context.get('view_type', 'all')
        
        if not p_type_id:
            return

        picking_type = self.env['stock.picking.type'].browse(p_type_id)
        
        # Tạo action cơ bản mở danh sách phiếu
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action['name'] = f"{picking_type.name} - {view_type.capitalize()}"
        action['context'] = {
            'default_picking_type_id': p_type_id,
            'contact_display': 'partner_address',
        }
        
        # Xử lý các domain theo trạng thái yêu cầu
        base_domain = [('picking_type_id', '=', p_type_id)]
        
        if view_type == 'ready':
            return picking_type.get_action_picking_tree_ready() # Hàm chuẩn của Odoo cho nút "Cần làm"
        elif view_type == 'waiting':
            return picking_type.get_action_picking_tree_waiting() # Hàm chuẩn cho "Đang chờ"
        elif view_type == 'late':
             return picking_type.get_action_picking_tree_late()
        elif view_type == 'draft':
            action['domain'] = base_domain + [('state', '=', 'draft')]
        elif view_type == 'done':
            action['domain'] = base_domain + [('state', '=', 'done')]
        else:
            # Mặc định mở tất cả (khi bấm vào tên hoạt động)
            action['domain'] = base_domain
            
        return action

    # Hàm mới: Mở danh sách Hoạt động (Picking Type) của riêng kho này
    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        return action