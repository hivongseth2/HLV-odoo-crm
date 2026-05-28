from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    restrict_pack_to_assigned_user = fields.Boolean(
        string='Chỉ người được assign mới được đóng gói',
        config_parameter='hlv_sale_delivery_planning.restrict_pack_to_assigned_user',
        help='Khi bật, chỉ người được assign lúc in phiếu lấy hàng hoặc quản lý kho mới được vào/validate phiếu PACK.',
    )
    pick_print_time_mode = fields.Selection(
        selection=[
            ('first', 'Ghi nhận lần đầu in'),
            ('latest', 'Ghi nhận lần in gần nhất'),
        ],
        string='Chế độ ghi nhận thời gian in',
        config_parameter='hlv_sale_delivery_planning.pick_print_time_mode',
        default='first',
        help='first: chỉ ghi thời gian in lần đầu tiên (giữ nguyên nếu đã có). latest: luôn cập nhật với lần in mới nhất.',
    )
