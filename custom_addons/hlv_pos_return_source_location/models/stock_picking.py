# -*- coding: utf-8 -*-
from itertools import groupby

from odoo import models, api, fields
from odoo.tools import float_is_zero
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'


    def _get_hlv_pos_source_location(self, line):
        location = line.hlv_source_location_id
        if not location or line.qty <= 0 or location.usage != 'internal':
            return self.env['stock.location']
        return location

    def _hlv_pos_grouping_key(self, line):
        location = self._get_hlv_pos_source_location(line)
        return (
            line.product_id.id,
            tuple(sorted(line.attribute_value_ids.ids)),
            location.id or False,
        )

    def _create_move_from_pos_order_lines(self, lines):
        self.ensure_one()
        stockable_lines = lines.filtered(
            lambda line: line.product_id.type == 'consu'
            and not float_is_zero(line.qty, precision_rounding=line.product_id.uom_id.rounding)
        )
        if not stockable_lines:
            return

        lines_by_key = groupby(
            sorted(stockable_lines, key=self._hlv_pos_grouping_key),
            key=self._hlv_pos_grouping_key,
        )
        move_vals = []
        for _key, order_lines_group in lines_by_key:
            order_lines = self.env['pos.order.line'].concat(*order_lines_group)
            move_vals.append(self._prepare_stock_move_vals(order_lines[0], order_lines))
        moves = self.env['stock.move'].create(move_vals)
        confirmed_moves = moves._action_confirm()
        confirmed_moves._add_mls_related_to_order(lines, are_qties_done=True)
        confirmed_moves.picked = True
        self._link_owner_on_return_picking(lines)

    def _prepare_stock_move_vals(self, first_line, order_lines):
        """
        Odoo 18 hook: Chuẩn bị giá trị cho Stock Move từ POS Line.
        Nếu là hàng trả về, tìm kệ gốc để gán vào location_dest_id.
        Cho trường hợp nhiều vị trí, đặt vị trí đầu tiên ở đây;
        pos_order._fix_multi_location_returns() sẽ tách move lines sau.
        """
        res = super()._prepare_stock_move_vals(first_line, order_lines)

        source_location = self._get_hlv_pos_source_location(first_line)
        if source_location:
            res['location_id'] = source_location.id

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
