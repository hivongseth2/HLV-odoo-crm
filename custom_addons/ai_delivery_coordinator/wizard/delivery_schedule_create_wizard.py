from odoo import models, fields, api, _
from odoo.exceptions import UserError

class DeliveryScheduleCreateWizard(models.TransientModel):
    _name = 'delivery.schedule.create.wizard'
    _description = 'Wizard Tạo Chuyến Xe Hàng Loạt'

    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today)
    route_id = fields.Many2one('delivery.route', string='Tuyến Giao Thực Tế', required=True)
    vehicle_type = fields.Selection([
        ('van_xe_may', 'Van/Xe máy'),
        ('tai_nho', 'Tải Nhỏ'),
        ('tai_lon', 'Tải Lớn (1.5 - 2.5T)')
    ], string='Loại xe', required=True, default='van_xe_may')
    session = fields.Selection([
        ('morning', 'Sáng'),
        ('afternoon', 'Chiều'),
        ('evening', 'Tối'),
        ('other', 'Khác (Theo ghi chú)')
    ], string='Phiên giao', required=True, default='morning')
    driver_name = fields.Char(string='Tài xế / Ghi chú điều phối')
    note = fields.Text(string='Ghi chú chuyến xe')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        
        # Lấy route phổ biến nhất trong các line đang chọn để gán mặc định
        if active_ids:
            lines = self.env['delivery.schedule.line'].browse(active_ids)
            if any(l.schedule_id for l in lines):
                raise UserError(_("Một số đơn hàng được chọn đã có chuyến xe. Vui lòng bỏ chọn!"))
            
            # Gợi ý dựa trên đơn đầu tiên
            first_route = next((l.route_id for l in lines if l.route_id), False)
            if first_route:
                res['route_id'] = first_route.id
                
            first_date = next((l.assigned_date for l in lines if l.assigned_date), False)
            if first_date:
                res['date'] = first_date
                
        return res

    def action_create_schedule(self):
        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_("Không có đơn hàng nào được chọn!"))

        lines = self.env['delivery.schedule.line'].browse(active_ids)

        # 1. Tạo Chuyến Xe Mới (Schedule)
        # Sử dụng warehouse_code tĩnh như logic cũ hoặc thiết lập từ user
        warehouse_code = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.default_warehouse_code', 'WH_MAIN')
        
        sched_vals = {
            'date': self.date,
            'warehouse_code': warehouse_code,
            'route': self.route_id.name, # Tạm map name vào route (Char) cũ để khỏi lỗi
            'vehicle_type': self.vehicle_type,
            'session': self.session,
            'driver_name': self.driver_name,
            'note': self.note,
        }
        
        new_sched = self.env['delivery.schedule'].create(sched_vals)
        new_sched.name = f"DC-{new_sched.id:04d}"

        # 2. Gắn các lines vào schedule này
        for line in lines:
            line.write({
                'schedule_id': new_sched.id,
                'assigned_date': self.date,
                'route_id': self.route_id.id
            })

        return {
            'name': _('Chuyến Xe Vừa Tạo'),
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.schedule',
            'res_id': new_sched.id,
            'view_mode': 'form',
            'target': 'current',
        }
