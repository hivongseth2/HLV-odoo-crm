from odoo import api, fields, models

from .pickup_line import OPEN_RUN_STATES


class PurchaseOrder(models.Model):
    """Nối đơn mua hàng với lịch sử đi nhận.

    Chỉ THÊM thông tin, không đổi hành vi nào của luồng mua hàng: không field nào ở đây
    tham gia vào trạng thái đơn, vào phiếu kho hay vào kế toán.
    """

    _inherit = 'purchase.order'

    x_pickup_line_ids = fields.One2many(
        'hlv.pickup.line', 'purchase_order_id', string='Lượt đi nhận',
    )
    x_pickup_count = fields.Integer(compute='_compute_pickup_state', string='Số lượt đi nhận')
    x_pickup_state = fields.Selection(
        [
            ('none', 'Chưa xếp chuyến'),
            ('scheduled', 'Đã xếp chuyến'),
            ('received', 'Đã nhận'),
            ('partial', 'Nhận một phần'),
            ('not_ready', 'Chưa lấy được'),
        ],
        string='Tình trạng đi nhận', compute='_compute_pickup_state',
        help='Trạng thái của việc ĐI LẤY hàng về, không phải trạng thái đơn mua.',
    )

    @api.depends('x_pickup_line_ids.state', 'x_pickup_line_ids.run_id.state')
    def _compute_pickup_state(self):
        """Trạng thái lấy theo kết quả TỐT NHẤT từng đạt được, không theo dòng mới nhất.

        Đơn đã nhận về rồi mà sau đó bị xếp nhầm vào một chuyến mới thì vẫn là đã nhận —
        lấy dòng mới nhất sẽ làm trạng thái tụt ngược về "đã xếp chuyến".
        """
        for order in self:
            lines = order.x_pickup_line_ids
            order.x_pickup_count = len(lines)
            states = set(lines.mapped('state'))
            if 'received' in states:
                order.x_pickup_state = 'received'
            elif 'partial' in states:
                order.x_pickup_state = 'partial'
            elif lines.filtered(lambda l: l.run_id.state in OPEN_RUN_STATES):
                order.x_pickup_state = 'scheduled'
            elif 'not_ready' in states:
                order.x_pickup_state = 'not_ready'
            else:
                order.x_pickup_state = 'none'

    def action_open_pickup_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lượt đi nhận — %s' % self.name,
            'res_model': 'hlv.pickup.line',
            'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
        }
