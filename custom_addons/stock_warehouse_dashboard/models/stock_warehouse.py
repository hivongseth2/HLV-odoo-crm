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
                # Đếm số lượng
                count_draft = Picking.search_count([('picking_type_id', '=', op.id), ('state', '=', 'draft')])
                # Nếu muốn đếm Done thì mở dòng dưới ra, nhưng cẩn thận nếu dữ liệu nhiều sẽ chậm
                # count_done = Picking.search_count([('picking_type_id', '=', op.id), ('state', '=', 'done')])
                
                # Màu sắc nút chính
                btn_color = 'btn-secondary'
                if op.code == 'incoming': btn_color = 'btn-primary'
                elif op.code == 'outgoing': btn_color = 'btn-success'
                elif op.code == 'internal': btn_color = 'btn-warning'

                data.append({
                    'id': op.id,
                    'name': op.name,
                    'code': op.code,
                    'count_ready': op.count_picking_ready,
                    'count_waiting': op.count_picking_waiting,
                    'count_late': op.count_picking_late,
                    'count_draft': count_draft,
                    'btn_color': btn_color,
                })
            warehouse.warehouse_dashboard_data = json.dumps(data)

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

    def open_warehouse_operations(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_type_action")
        # Lọc danh sách loại hoạt động THEO KHO hiện tại
        action['domain'] = [('warehouse_id', '=', self.id)]
        action['display_name'] = f"Hoạt động: {self.name}"
        return action