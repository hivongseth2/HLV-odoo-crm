# -*- coding: utf-8 -*-
from odoo import models

LOCK_STARTED_PACK_PARAM = 'pack_scan.lock_started_pack'


class StockPickingPackLock(models.Model):
    _inherit = 'stock.picking'

    def lock_pack_against_merge(self):
        """Không cho Odoo nhét thêm hàng vào phiếu đã bắt đầu đóng (nếu bật trong Cài đặt).

        Khi PICK xong, Odoo 18 đẩy dòng hàng sang phiếu PACK cùng đơn còn dở và chỉ chọn
        phiếu có `printed = False` (stock.move._search_picking_for_assignation_domain).
        Đánh dấu `printed` là đúng tín hiệu "phiếu đã vào tay người làm" của Odoo, nên
        hàng về sau tự sang một phiếu PACK mới thay vì đổi số dưới tay người đóng gói.
        """
        enabled = self.env['ir.config_parameter'].sudo().get_param(LOCK_STARTED_PACK_PARAM)
        if enabled not in ('True', 'true', '1'):
            return
        self.filtered(
            lambda p: not p.printed and p.state not in ('done', 'cancel')
        ).write({'printed': True})
