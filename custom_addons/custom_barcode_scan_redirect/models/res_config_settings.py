# -*- coding: utf-8 -*-
from odoo import fields, models

from .stock_picking_pack_lock import LOCK_STARTED_PACK_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pack_scan_lock_started_pack = fields.Boolean(
        string='Không gộp hàng về sau vào phiếu đang đóng',
        config_parameter=LOCK_STARTED_PACK_PARAM,
        help='Bật: khi người đóng gói đã mở phiếu PACK, hàng của PICK lấy bổ sung sau đó sẽ '
             'sang một phiếu PACK mới (hiện ở mục "Đơn hàng cùng Order" trên màn hình đóng '
             'gói) — đơn có thể thành 2 phiếu PACK, 2 lần đóng, 2 video. '
             'Tắt: Odoo gộp hàng về sau vào phiếu đang đóng; màn hình đóng gói sẽ báo '
             '"Phiếu vừa thay đổi" và bắt tải lại.',
    )
