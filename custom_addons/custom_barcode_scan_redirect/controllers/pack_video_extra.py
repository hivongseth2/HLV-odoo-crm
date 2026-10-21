# -*- coding: utf-8 -*-
"""Trang quay video bổ sung cho phiếu PACK đã đóng gói xong (/custom_barcode_scan/pack_video_extra/<id>)."""
from odoo import http
from odoo.http import request

from ._shared import EXTRA_VIDEO_PURPOSE, find_origin_pick, recording_page_flags


class PackVideoExtraController(http.Controller):

    @http.route('/custom_barcode_scan/pack_video_extra/<int:picking_id>', type='http', auth='user')
    def pack_video_extra(self, picking_id):
        """Chỉ quay video, không quét hàng.

        Không gọi mark_pack_actual_started và không kiểm người được giao: phiếu
        đã đóng xong, ai quay thêm cũng không đổi số liệu đóng gói của phiếu.
        """
        picking = request.env['stock.picking'].sudo().browse(picking_id).exists()
        if not picking:
            return request.not_found()
        if picking.state != 'done':
            # Chưa xong thì quay trong màn hình đóng gói như thường.
            return request.redirect(f'/custom_barcode_scan/pack_view/{picking.id}')

        origin_pick = find_origin_pick(request.env, picking)
        drive_connected = bool(request.env['ir.config_parameter'].sudo()
                               .get_param('gdrive.user_credentials_json'))

        response = request.render("custom_barcode_scan_redirect.pack_video_extra_template", {
            'picking': picking,
            # sale_id đến từ sale_stock, module này không phụ thuộc nên đọc mềm.
            'order_name': getattr(picking, 'sale_id', False) and picking.sale_id.name
                          or picking.origin or '',
            'origin_pick_name': origin_pick.name or '',
            'done_moves': picking.move_ids.filtered(lambda m: m.product_id and m.quantity),
            'drive_connected': drive_connected,
            'video_purpose': EXTRA_VIDEO_PURPOSE,
            **recording_page_flags(request.env),
        })
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response
