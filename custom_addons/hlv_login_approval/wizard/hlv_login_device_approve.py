from odoo import fields, models


class HlvLoginDeviceApprove(models.TransientModel):
    _name = 'hlv.login.device.approve'
    _description = 'Chọn số khớp để duyệt thiết bị đăng nhập'

    device_id = fields.Many2one('hlv.login.device', required=True, readonly=True, ondelete='cascade')
    user_id = fields.Many2one(related='device_id.user_id')
    ip_address = fields.Char(related='device_id.ip_address')
    platform = fields.Char(related='device_id.platform')
    browser = fields.Char(related='device_id.browser')
    request_date = fields.Datetime(related='device_id.request_date')
    # Chỉ lưu các số để hiện lên nút; số nào đúng chỉ device biết.
    choice_1 = fields.Char(readonly=True)
    choice_2 = fields.Char(readonly=True)
    choice_3 = fields.Char(readonly=True)

    def action_pick(self):
        self.ensure_one()
        if self.device_id._approve_with_code(self.env.context.get('hlv_pick')):
            title, message, kind = (
                self.env._("Đã duyệt"),
                self.env._("%s sẽ tự vào hệ thống trên thiết bị vừa duyệt.", self.user_id.name),
                'success')
        else:
            title, message, kind = (
                self.env._("Sai số, đã huỷ yêu cầu"),
                self.env._("%s phải đăng nhập lại để lấy số mới. Nếu người đó không nhắn số cho bạn, "
                           "có thể ai khác đang dùng mật khẩu của họ.", self.user_id.name),
                'danger')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': kind,
                'sticky': kind == 'danger',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
