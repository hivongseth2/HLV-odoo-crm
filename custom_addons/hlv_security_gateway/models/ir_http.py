import re
import logging
from werkzeug.exceptions import Forbidden
from odoo import models, api
from odoo.http import request

_logger = logging.getLogger(__name__)

# Common malicious patterns derived from logs
DEFAULT_BLOCKED_PATTERNS = [
    r'\.php$', r'\.jsp$', r'\.asp$', r'\.war$', r'\.bkp$', r'\.bak$', r'\.swp$', r'\.swo$',
    r'\.\./', r'etc/passwd', r'wp-config\.php', r'wp-admin', r'union select', r'sqli-test'
]

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        # 1. Get client IP
        ip = request.httprequest.remote_addr
        path = request.httprequest.path

        # 2. Check for manual IP blocks (including the one from logs)
        # In a real scenario, we would fetch from Cache or Model, but for immediate protection:
        if ip == '34.87.32.244':
            _logger.warning("Blocked malicious IP: %s accessing %s", ip, path)
            raise Forbidden("Your IP is blacklisted due to suspicious activity.")

        # 3. Check for malicious patterns in the path
        for pattern in DEFAULT_BLOCKED_PATTERNS:
            if re.search(pattern, path, re.I):
                _logger.warning("Blocked malicious pattern '%s' in path: %s from IP: %s", pattern, path, ip)
                raise Forbidden("Malicious request pattern detected and blocked.")

        return super()._dispatch(endpoint)
