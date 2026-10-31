from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.login_approval_utils import split_match_choices

PICK_URL = '/hlv_login_approval/pick'


class LoginApprovalPick(http.Controller):
    """Chọn số khớp từ nút trong email người duyệt.

    GET chỉ hiện trang xác nhận, POST mới duyệt: Gmail và bộ quét bảo mật tự mở link trong
    email, nếu mở link là duyệt thì máy quét sẽ "chọn số" thay người và có thể huỷ yêu cầu.
    """

    @http.route(PICK_URL + '/<int:device_id>/<string:choice>', type='http', auth='user',
                methods=['GET'], website=True, multilang=False, sitemap=False)
    def hlv_pick_confirm(self, device_id, choice, **kw):
        device, error = self._hlv_pickable_device(device_id)
        if not error and choice not in split_match_choices(device.sudo().match_choices):
            error = request.env._("Số này không thuộc yêu cầu duyệt. Mở lại email mới nhất.")
        return self._hlv_render(device, choice=choice, error=error)

    @http.route(PICK_URL + '/<int:device_id>', type='http', auth='user',
                methods=['POST'], website=True, multilang=False, sitemap=False)
    def hlv_pick_submit(self, device_id, choice=None, **kw):
        device, error = self._hlv_pickable_device(device_id)
        if error:
            return self._hlv_render(device, error=error)
        try:
            approved = device._approve_with_code(choice)
        except UserError as e:
            return self._hlv_render(device, error=e.args[0])
        return self._hlv_render(device, choice=choice, result='approved' if approved else 'cancelled')

    def _hlv_pickable_device(self, device_id):
        """(thiết bị, lỗi) — lỗi là chuỗi khi người đang đăng nhập không duyệt được yêu cầu này."""
        env = request.env
        Device = env['hlv.login.device']
        if not env.user.has_group('hlv_login_approval.group_login_approver'):
            return Device, env._("Tài khoản %s không thuộc nhóm người duyệt đăng nhập.", env.user.name)
        device = Device.browse(device_id).exists()
        if not device:
            return Device, env._("Không tìm thấy yêu cầu duyệt này.")
        try:
            device._check_can_approve()
        except UserError as e:
            return device, e.args[0]
        return device, None

    def _hlv_render(self, device, choice=None, error=None, result=None):
        return request.render('hlv_login_approval.login_pick', {
            'device': device,
            'choice': choice,
            'error': error,
            'result': result,
            'pick_url': f"{PICK_URL}/{device.id}" if device else '',
            'device_url': f"/odoo/action-hlv_login_approval.action_hlv_login_device/{device.id}" if device else '/odoo',
        })
