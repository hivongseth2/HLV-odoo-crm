# -*- coding: utf-8 -*-
"""
models/stock_picking_ext.py

Trigger đồng bộ tồn kho Shopee sau khi phiếu kho được xác nhận.

Khi stock.picking._action_done() hoàn thành (phiếu kho validate — kể cả qua
app barcode), các sản phẩm có tồn kho thay đổi sẽ được đánh dấu
pending_stock_sync = True trên shopee.product tương ứng.

Cron "Shopee: Xử lý hàng đợi đồng bộ tồn kho" sẽ đọc danh sách này
và đẩy tồn kho lên Shopee theo chu kỳ (mặc định 15 phút).
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPickingShopeeExt(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        result = super()._action_done()
        # Sau khi hoàn thành phiếu, lấy tất cả product_id có trong done moves
        done_moves = self.move_ids.filtered(lambda m: m.state == 'done')
        if done_moves:
            product_ids = done_moves.mapped('product_id').ids
            if product_ids:
                try:
                    self.env['shopee.product']._mark_for_stock_sync(product_ids)
                except Exception as e:
                    # Không để lỗi Shopee ảnh hưởng đến việc xác nhận phiếu kho
                    _logger.warning(
                        "Shopee stock sync trigger: lỗi đánh dấu cho picking %s: %s",
                        self.name, str(e),
                    )
        return result
