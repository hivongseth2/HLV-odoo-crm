from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class LoginMisa(models.TransientModel):
    _name = "login.misa"
    _description = "Login MISA"

    def login_misa (self):
        misa_utils = self.env['misa.api.utils']
        access_token = misa_utils._fetch_login_crm_token()
        if access_token:
            _logger.info("✅ Đăng nhập MISA thành công")
        else:
            _logger.warning("❌ Đăng nhập MISA thất bại")

