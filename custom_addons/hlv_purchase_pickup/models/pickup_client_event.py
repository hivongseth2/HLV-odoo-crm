from odoo import api, fields, models


class HlvPickupClientEvent(models.Model):
    """Sổ ghi các lần bấm nút đã xử lý — để bấm lại không sinh mốc thứ hai.

    Người đi nhận đứng trong khu công nghiệp, sóng chập chờn. Điện thoại gửi request xong
    mất mạng trước khi nhận được trả lời, người dùng thấy quay vòng mãi nên bấm lại. Không
    có sổ này thì một lần bấm "đã tới" hoá thành hai, và mốc thứ hai (muộn hơn) có thể ghi
    đè mốc thật.

    Client sinh ``event_uid`` một lần cho mỗi lần BẤM (không phải mỗi lần gửi), nên mọi lần
    gửi lại đều mang cùng một uid và chỉ lần đầu được tính.
    """

    _name = 'hlv.pickup.client.event'
    _description = 'Lần bấm đã xử lý (chống bấm trùng)'
    _order = 'id desc'

    event_uid = fields.Char(required=True, index=True, string='Mã lần bấm')
    route = fields.Char(required=True, string='Thao tác')
    user_id = fields.Many2one(
        'res.users', string='Người bấm', required=True, default=lambda self: self.env.user,
    )
    res_model = fields.Char(string='Model')
    res_id = fields.Integer(string='Bản ghi')

    _sql_constraints = [
        ('event_uid_uniq', 'unique(event_uid)', 'Lần bấm này đã được ghi nhận.'),
    ]

    @api.model
    def claim(self, event_uid, route, record=None):
        """Đăng ký một lần bấm. Trả True nếu là lần đầu (được phép làm tiếp), False nếu đã xử lý.

        ``event_uid`` rỗng thì luôn trả True: client cũ chưa gửi uid vẫn phải dùng được,
        chỉ là không được bảo vệ chống bấm trùng.
        """
        event_uid = (event_uid or '').strip()
        if not event_uid:
            return True
        if self.sudo().search_count([('event_uid', '=', event_uid)]):
            return False
        self.sudo().create({
            'event_uid': event_uid,
            'route': route,
            'user_id': self.env.user.id,
            'res_model': record._name if record else False,
            'res_id': record.id if record else 0,
        })
        return True

    @api.model
    def cron_clean_old(self, days=30):
        """Xoá sổ cũ. Bấm trùng chỉ xảy ra trong vài phút, giữ 30 ngày là quá dư."""
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        self.sudo().search([('create_date', '<', limit)]).unlink()
        return True
