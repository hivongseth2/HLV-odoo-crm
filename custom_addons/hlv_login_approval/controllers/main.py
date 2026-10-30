from werkzeug.urls import url_encode

from odoo import http
from odoo.http import request
from odoo.addons.auth_totp.controllers.home import Home

from ..models.res_users import SESSION_DEVICE_KEY, WAIT_URL


class LoginApprovalHome(Home):

    @http.route(WAIT_URL, type='http', auth='public', sitemap=False, website=True, multilang=False)
    def hlv_login_approval_wait(self, redirect=None, **kw):
        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))
        user = self._hlv_pre_login_user()
        if not user:
            return request.redirect('/web/login')
        if not user._login_device_pending():
            return request.redirect(self._hlv_continue_url(redirect))
        device = user._login_device_in_session()
        return request.render('hlv_login_approval.login_wait', {
            'device': device,
            'waiting_state': device._waiting_state(),
            'request_minutes': device._request_minutes(),
            'continue_url': self._hlv_continue_url(redirect),
        })

    @http.route(WAIT_URL + '/status', type='http', auth='public', sitemap=False, methods=['GET'])
    def hlv_login_approval_status(self, **kw):
        user = self._hlv_pre_login_user()
        device = user._login_device_in_session() if user else None
        state = device._waiting_state() if device else 'none'
        return request.make_json_response({'state': state})

    @http.route(WAIT_URL + '/continue', type='http', auth='public', sitemap=False, website=True, multilang=False)
    def hlv_login_approval_continue(self, redirect=None, **kw):
        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))
        user = self._hlv_pre_login_user()
        if not user:
            return request.redirect('/web/login')
        # Còn chờ duyệt (về trang chờ) hoặc còn bước 2FA (sang trang nhập mã): để core điều hướng.
        if user._mfa_url():
            return request.redirect(self._login_redirect(user.id, redirect=redirect))
        request.session.pop(SESSION_DEVICE_KEY, None)
        request.session.finalize(request.env)
        request.update_env(user=request.session.uid)
        request.update_context(**request.session.context)
        return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))

    @http.route()
    def web_totp(self, redirect=None, **kwargs):
        # Bước 2FA tự hoàn tất phiên (kể cả thiết bị 2FA tin cậy), nên phải chặn ở đây;
        # không thì user có 2FA gõ thẳng /web/login/totp là vượt qua bước duyệt.
        user = self._hlv_pre_login_user()
        if not request.session.uid and user and user._login_device_pending():
            return request.redirect(self._login_redirect(user.id, redirect=redirect))
        return super().web_totp(redirect=redirect, **kwargs)

    def _hlv_pre_login_user(self):
        pre_uid = request.session.pre_uid
        return request.env['res.users'].sudo().browse(pre_uid).exists() if pre_uid else None

    def _hlv_continue_url(self, redirect):
        query = f"?{url_encode({'redirect': redirect})}" if redirect else ''
        return f"{WAIT_URL}/continue{query}"
