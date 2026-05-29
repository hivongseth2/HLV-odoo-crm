from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    hlv_barcode_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        relation='res_company_stock_picking_type_barcode_rel',
        column1='company_id',
        column2='picking_type_id',
        string='Barcode Picking Types'
    )
    hlv_barcode_print_after_pack = fields.Boolean(
        string='Print Label after Put in Pack',
        default=False
    )

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hlv_barcode_picking_type_ids = fields.Many2many(
        related='company_id.hlv_barcode_picking_type_ids',
        readonly=False,
    )
    hlv_barcode_print_after_pack = fields.Boolean(
        related='company_id.hlv_barcode_print_after_pack',
        readonly=False,
    )
    hlv_barcode_use_independent_permissions = fields.Boolean(
        string='Sử dụng phân quyền quét độc lập',
        config_parameter='hlv_mobile_barcode.hlv_barcode_use_independent_permissions',
        help='Nếu bật, hệ thống sẽ sử dụng cấu hình phân quyền quét của riêng module Mobile Barcode. Nếu tắt, sẽ dùng chung cấu hình của module hlv_warehouse_permission.'
    )
    hlv_barcode_allow_package_scan = fields.Boolean(
        string='Cho phép quét Kiện hàng (Package)',
        config_parameter='hlv_mobile_barcode.hlv_barcode_allow_package_scan',
        help='Nếu bật, cho phép quét mã vạch của kiện hàng (PACKxxx) để tự động nhận dạng và xử lý hàng loạt tất cả sản phẩm bên trong kiện.'
    )
    hlv_barcode_show_qty_buttons = fields.Boolean(
        string='Hiển thị nút điều chỉnh số lượng nhanh',
        help='Nếu bật, sẽ hiển thị các nút -10, -1, +1, +10 để chỉnh số lượng nhanh trong ứng dụng quét mã vạch.'
    )

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        res.update(
            hlv_barcode_show_qty_buttons=self.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_show_qty_buttons', 'True') == 'True',
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param('hlv_mobile_barcode.hlv_barcode_show_qty_buttons', str(self.hlv_barcode_show_qty_buttons))

    def action_open_warehouse_permissions(self):
        self.ensure_one()
        action = self.env.ref('hlv_warehouse_permission.action_warehouse_permission', raise_if_not_found=False)
        if action:
            return action.read()[0]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Không tìm thấy',
                'message': 'Module hlv_warehouse_permission chưa được cài đặt hoặc không tìm thấy cấu hình!',
                'type': 'warning',
                'sticky': False,
            }
        }
