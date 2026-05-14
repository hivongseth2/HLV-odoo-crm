from odoo import models, fields


class HlvInventoryReportConfig(models.Model):
    _name = 'hlv.inventory.report.config'
    _description = 'Cấu hình báo cáo tồn kho đã lưu'
    _order = 'sequence, name'

    name = fields.Char('Tên báo cáo', required=True)
    sequence = fields.Integer('Thứ tự', default=10)
    active = fields.Boolean(default=True)
    note = fields.Text('Ghi chú')

    group_ids = fields.Many2many(
        'hlv.product.report.group',
        'hlv_report_config_group_rel',
        'config_id', 'group_id',
        string='Nhóm sản phẩm',
    )
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'hlv_report_config_wh_rel',
        'config_id', 'warehouse_id',
        string='Kho hàng',
        help='Để trống = tất cả kho',
    )
    show_zero = fields.Boolean('Hiển thị SP tồn = 0', default=True)
    show_location_detail = fields.Boolean('Chi tiết theo vị trí')

    def action_open_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'hlv.inventory.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_config_id': self.id,
                'default_group_ids': [(6, 0, self.group_ids.ids)],
                'default_warehouse_ids': [(6, 0, self.warehouse_ids.ids)],
                'default_show_zero': self.show_zero,
                'default_show_location_detail': self.show_location_detail,
            },
        }
