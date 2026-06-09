import logging

from werkzeug.exceptions import Forbidden

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        path = request.httprequest.path.rstrip('/')
        if (
            (path == '/odoo/barcode' or path.startswith('/odoo/barcode/'))
            and request.session.uid
            and not request.env.user._is_superuser()
            and not request.env.user.has_group('hlv_mobile_barcode.group_stock_barcode_default_user')
        ):
            _logger.warning(
                "Blocked default Odoo barcode access for user %s (%s)",
                request.env.user.login,
                request.env.user.id,
            )
            raise Forbidden("You are not allowed to access the default Odoo Barcode app.")

        return super()._dispatch(endpoint)
