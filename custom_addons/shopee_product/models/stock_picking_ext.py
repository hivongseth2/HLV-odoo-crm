# -*- coding: utf-8 -*-
"""
models/stock_picking_ext.py

Trigger đồng bộ tồn kho Shopee sau khi tồn kho Odoo thay đổi.

Hook chính nằm ở stock.move._action_done() để bắt cả phiếu kho lẫn inventory
adjustment (kiểm kê/điều chỉnh tồn) vốn tạo stock.move done nhưng không có
stock.picking. Hook stock.picking._action_done() được giữ lại như lớp bảo vệ
cho barcode/custom flow.

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


class StockMoveShopeeExt(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, *args, **kwargs):
        result = super()._action_done(*args, **kwargs)
        # Inventory Adjustment thường không có picking, nên phải hook tại
        # stock.move để vẫn tạo queue đồng bộ Shopee khi tồn thay đổi.
        done_moves = result if hasattr(result, 'filtered') else self
        done_moves = done_moves.filtered(lambda m: m.state == 'done' and m.product_id)
        product_ids = done_moves.mapped('product_id').ids
        if product_ids:
            try:
                self.env['shopee.product']._mark_for_stock_sync(product_ids)
            except Exception as e:
                _logger.warning(
                    "Shopee stock sync trigger: lỗi đánh dấu từ stock.move ids=%s: %s",
                    done_moves.ids[:20], str(e),
                )
        return result
