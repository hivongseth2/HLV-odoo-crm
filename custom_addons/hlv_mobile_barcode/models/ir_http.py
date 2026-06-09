import logging

from werkzeug.exceptions import Forbidden

from odoo import SUPERUSER_ID, models
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        path = request.httprequest.path.rstrip('/')
        uid = request.session.uid
        user = request.env['res.users'].browse(uid).exists() if uid else request.env['res.users']
        if (
            (path == '/odoo/barcode' or path.startswith('/odoo/barcode/'))
            and user
            and uid != SUPERUSER_ID
            and not user.has_group('hlv_mobile_barcode.group_stock_barcode_default_user')
        ):
            _logger.warning(
                "Blocked default Odoo barcode access for user %s (%s)",
                user.login,
                user.id,
            )
            raise Forbidden("You are not allowed to access the default Odoo Barcode app.")

        return super()._dispatch(endpoint)
