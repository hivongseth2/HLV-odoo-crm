# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _prepare_stock_move_vals(self, first_line, order_lines):
        """
        Odoo 18 hook: Chuẩn bị giá trị cho Stock Move từ POS Line.
        Nếu là hàng trả về, tìm kệ gốc để gán vào location_dest_id.
        Cho trường hợp nhiều vị trí, đặt vị trí đầu tiên ở đây;
        pos_order._fix_multi_location_returns() sẽ tách move lines sau.
        """
        res = super()._prepare_stock_move_vals(first_line, order_lines)

        if first_line.qty < 0 and first_line.refunded_orderline_id:
            try:
                orig_line = first_line.refunded_orderline_id
                orig_order = orig_line.order_id

                # Tìm move lines xuất gốc cho sản phẩm này
                all_ml = orig_order.sudo().picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == first_line.product_id and ml.quantity > 0
                )

                # Ưu tiên lấy dòng di chuyển đến Customer
                orig_move_lines = all_ml.filtered(lambda ml: ml.location_dest_id.usage == 'customer')
                if not orig_move_lines:
                    orig_move_lines = all_ml

                if orig_move_lines:
                    # Lấy kệ chi tiết nhất (deepest path) làm dest mặc định cho move header
                    target_ml = sorted(
                        orig_move_lines,
                        key=lambda x: len(x.location_id.complete_name.split('/')),
                        reverse=True,
                    )[0]
                    target_loc = target_ml.location_id

                    if target_loc:
                        _logger.info(
                            "[HLV POS RETURN] Move dest → %s for %s",
                            target_loc.complete_name,
                            first_line.product_id.name,
                        )
                        res['location_dest_id'] = target_loc.id
            except Exception as e:
                _logger.error("[HLV POS RETURN] Error in _prepare_stock_move_vals: %s", str(e))

        return res
