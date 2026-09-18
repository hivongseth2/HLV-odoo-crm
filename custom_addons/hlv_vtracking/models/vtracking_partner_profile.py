"""Thói quen giao hàng của một điểm giao — thứ người điều phối biết mà Odoo không biết.

Treo vào **điểm giao** chứ không vào từng mã khách. Một khách có nhiều liên hệ con, mỗi
liên hệ là một địa chỉ giao — đo 18/09/2026 trên 6404 phiếu OUT (01/06→18/09): 3282 mã
khách trên phiếu, trong đó 836 mã là liên hệ con. Gắn thói quen vào mã khách thì mỗi địa
chỉ giao của cùng một nhà máy có một bộ riêng, và chúng lệch nhau ngay lần sửa đầu tiên.

Cũng không gắn vào pháp nhân gốc: ``procedure_required`` là tính chất của **chỗ giao**
(khu chế xuất thì phải khai hải quan), không phải của công ty. Một khách có kho ngoài khu
và nhà máy trong khu thì hai nơi có thủ tục khác nhau.
"""

from odoo import api, fields, models

from ..tools.vtracking_channel import CHANNEL_LABELS, needs_company_truck

PROCEDURE_LABELS = {
    'none': 'Không cần',
    'customs': 'Khai hải quan',
    'register': 'Đăng ký trước',
    'both': 'Hải quan + đăng ký',
}


class HlvVtrackingPartnerProfile(models.Model):
    _name = 'hlv.vtracking.partner.profile'
    _description = 'Thói quen giao hàng của điểm giao'
    _inherit = ['mail.thread']
    _rec_name = 'place_id'
    _order = 'place_id'

    place_id = fields.Many2one(
        'hlv.vtracking.place', string='Điểm giao', required=True, index=True,
        ondelete='cascade', tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        default=lambda self: self.env.company,
    )

    # --- Đọc từ điểm giao, để lọc và soát ngay trên màn thói quen -----------
    partner_id = fields.Many2one(related='place_id.partner_id', store=True, readonly=True)
    partner_ref = fields.Char(related='place_id.partner_ref', readonly=True, string='Mã khách')
    zone_id = fields.Many2one(related='place_id.zone_id', store=True, readonly=True)

    # --- Thủ tục: cột giá trị nhất bảng này ---------------------------------
    procedure_required = fields.Selection(
        [(key, PROCEDURE_LABELS[key]) for key in ('none', 'customs', 'register', 'both')],
        string='Thủ tục trước khi giao', default='none', required=True, index=True,
        tracking=True,
        help='Xe tới nơi mà thủ tục chưa xong là mất trắng một lượt chạy: bảo vệ không cho '
             'vào cổng, hàng phải chở về. Đã xảy ra thật, nên kế hoạch chặn ở bước xác nhận.',
    )

    # --- Kênh giao ----------------------------------------------------------
    delivery_method = fields.Selection(
        [(key, CHANNEL_LABELS[key]) for key in ('company', 'pickup', 'express', 'grab')],
        string='Kênh giao thường dùng', tracking=True,
        help='Để trống nghĩa là xe công ty giao. Khách tự lấy / gửi CPN / book Grab thì '
             'đơn của họ không nên chiếm một điểm dừng trên xe.',
    )
    needs_truck = fields.Boolean(
        string='Cần xe công ty', compute='_compute_needs_truck', store=True,
        help='Suy từ kênh giao. Dùng để lọc nhanh đơn nào đáng xếp lên xe.',
    )

    default_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe thường chạy', tracking=True,
        help='Gợi ý khi lập kế hoạch, không phải ràng buộc.',
    )

    # --- Thời gian tại điểm -------------------------------------------------
    extra_service_minutes = fields.Integer(
        string='Phút lâu hơn thường lệ', default=0, tracking=True,
        help='CỘNG THÊM so với điểm thường trong cùng cụm, không phải tổng thời gian tại '
             'điểm. Định mức cụm (phút/chặng) ĐÃ gồm thời gian dỡ hàng và ký nhận của một '
             'điểm bình thường; điền tổng vào đây sẽ cộng đôi. Chỉ điền khi điểm này thật '
             'sự lâu hơn — cổng xa, chờ cân, phải qua nhiều lớp bảo vệ.',
    )
    receiving_from = fields.Float(
        string='Nhận hàng từ', help='Giờ trong ngày, ví dụ 8.5 là 08:30. 0 = không giới hạn.',
    )
    receiving_to = fields.Float(
        string='Nhận hàng đến', help='Giờ trong ngày. 0 = không giới hạn.',
    )

    payment_method = fields.Selection(
        [('none', 'Không thu tiền'), ('cod', 'Thu tiền khi giao')],
        string='Thu tiền', default='none',
    )
    free_note = fields.Text(
        string='Ghi chú cho tài xế',
        help='Cổng vào, số điện thoại người nhận, đường khó, chỗ quay đầu…',
    )

    _sql_constraints = [
        # Một điểm một bộ thói quen. Hai bộ thì không ai biết bộ nào đang có hiệu lực, và
        # mọi chỗ đọc ``place.profile_id`` sẽ lấy bừa một cái.
        ('place_uniq', 'unique(place_id)', 'Điểm giao này đã có bộ thói quen rồi.'),
    ]

    @api.depends('delivery_method')
    def _compute_needs_truck(self):
        for profile in self:
            profile.needs_truck = needs_company_truck(profile.delivery_method)

    def blocking_procedure(self):
        """Thủ tục chặn của điểm này, hoặc ``''`` nếu không cần thủ tục gì.

        Tách thành hàm để mọi chỗ hỏi "điểm này có chặn không" dùng chung một câu trả lời.
        """
        self.ensure_one()
        return '' if self.procedure_required in (False, 'none') else self.procedure_required
