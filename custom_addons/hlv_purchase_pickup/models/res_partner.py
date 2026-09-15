from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_pickup_point_id = fields.Many2one(
        'hlv.pickup.point', string='Điểm nhận hàng mặc định', index=True,
        help='Nơi mặc định tới lấy hàng của nhà cung cấp này. Khi xếp đơn vào chuyến, hệ '
             'thống dùng điểm này; người lập chuyến vẫn đổi được cho từng lượt.',
    )
    x_pickup_point_ids = fields.One2many(
        'hlv.pickup.point', 'partner_id', string='Các điểm nhận hàng',
        help='Một công ty có thể có nhiều nơi lấy hàng. Mỗi nơi là một điểm riêng vì toạ độ, '
             'giờ mở cửa và định mức thời gian của chúng khác nhau.',
    )
    x_pickup_point_count = fields.Integer(
        compute='_compute_x_pickup_point_count', string='Số điểm nhận',
    )

    @api.depends('x_pickup_point_ids')
    def _compute_x_pickup_point_count(self):
        for partner in self:
            partner.x_pickup_point_count = len(partner.x_pickup_point_ids)

    def action_open_pickup_points(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điểm nhận hàng — %s' % self.display_name,
            'res_model': 'hlv.pickup.point',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
