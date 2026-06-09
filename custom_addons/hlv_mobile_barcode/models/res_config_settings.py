from odoo import fields, models


def _str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'on')

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
    hlv_barcode_shopee_default_picker_user_id = fields.Many2one(
        'res.users',
        string='Default Shopee Picker',
        domain="[('share', '=', False), ('active', '=', True)]",
        help='Default user assigned to process Shopee PICK pickings.',
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
    hlv_barcode_shopee_default_picker_user_id = fields.Many2one(
        related='company_id.hlv_barcode_shopee_default_picker_user_id',
        readonly=False,
    )
    hlv_barcode_use_independent_permissions = fields.Boolean(
        string='Dùng Quyền Riêng Cho Máy Quét',
        config_parameter='hlv_mobile_barcode.hlv_barcode_use_independent_permissions',
        help='Bật lên nếu bạn muốn phân quyền cho nhân viên quét mã độc lập với quyền kho bình thường trên máy tính.'
    )
    hlv_barcode_allow_package_scan = fields.Boolean(
        string='Cho Phép Quét Mã Kiện Hàng (PACKxxx)',
        config_parameter='hlv_mobile_barcode.hlv_barcode_allow_package_scan',
        help='Bật để nhân viên có thể quét 1 mã kiện chứa nhiều sản phẩm thay vì phải quét từng cái một.'
    )
    hlv_barcode_show_qty_buttons = fields.Boolean(
        string='Hiện Nút Bấm Cộng/Trừ Số Lượng',
        help='Hiển thị các nút +1, -1, +10, -10 trên màn hình quét để nhân viên bấm nhanh không cần gõ phím.'
    )
    hlv_barcode_camera_default_on = fields.Boolean(
        string='Camera Mặc Định BẬT Khi Vào Phiếu',
        config_parameter='hlv_mobile_barcode.hlv_barcode_camera_default_on',
        help='Bật: Camera tự động mở khi vào phiếu. Tắt: Camera đóng sẵn, người dùng bấm nút để mở khi cần.'
    )
    hlv_barcode_same_warehouse_one_step = fields.Boolean(
        string='Chuyển Nội Bộ Cùng Kho 1 Bước',
        config_parameter='hlv_mobile_barcode.hlv_barcode_same_warehouse_one_step',
        default=True,
        help='Bật: chuyển hàng giữa các vị trí trong cùng kho sẽ hoàn thành trong 1 bước. Tắt: cùng kho khác vị trí cũng đi theo quy trình 2 bước qua Transit.'
    )

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            hlv_barcode_show_qty_buttons=_str_to_bool(
                ICP.get_param('hlv_mobile_barcode.hlv_barcode_show_qty_buttons', 'True'),
                default=True,
            ),
            hlv_barcode_same_warehouse_one_step=_str_to_bool(
                ICP.get_param('hlv_mobile_barcode.hlv_barcode_same_warehouse_one_step', 'True'),
                default=True,
            ),
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('hlv_mobile_barcode.hlv_barcode_show_qty_buttons', 'True' if self.hlv_barcode_show_qty_buttons else 'False')
        ICP.set_param('hlv_mobile_barcode.hlv_barcode_same_warehouse_one_step', 'True' if self.hlv_barcode_same_warehouse_one_step else 'False')

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
