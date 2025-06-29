from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class LoginMisa(models.TransientModel):
    _name = "login.misa"
    _description = "Login MISA"
    username = fields.Char(string="Tài khoản", required=True)
    password = fields.Char(string="Mật khẩu", required=True)

    def login_misa (self):
        misa_utils = self.env['misa.api.utils']
        access_token = misa_utils._get_misa_token(self.username, self.password)
        if access_token:
            _logger.info("✅ Đăng nhập MISA thành công")
        else:
            _logger.warning("❌ Đăng nhập MISA thất bại")

