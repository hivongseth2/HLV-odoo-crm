from odoo import api, models
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_other_pickings_total_done(self, product, location):
        """
        Tính tổng qty từ CÁC MOVE KHÁC cùng product + location.
        Dùng self._origin.id (move id thực trên DB) thay vì picking_id
        vì trong onchange context, self.picking_id có thể trả về False.
        """
        current_move_id = self._origin.id  # Stable DB id kể cả trong onchange

        other_move_lines = self.env['stock.move.line'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
            ('move_id', '!=', current_move_id),  # Loại trừ theo move, không theo picking
        ])

        total = sum(ml.quantity for ml in other_move_lines)

        _logger.info(
            '[CROSS_PICK] product=%s | location=%s | '
            'other_moves_qty=%s | current_move_id=%s',
            product.display_name, location.display_name,
            total, current_move_id,
        )

        return total

    @api.onchange('quantity')
    def _onchange_move_quantity_check_stock(self):
        """
        Khi user nhập tay vào cột 'SL thực' (stock.move.quantity) ở list view,
        kiểm tra tổng available tại location (bao gồm sub-locations).

        Công thức:
          available = on_hand - other_pickings_done
        KHÔNG dùng quant.reserved_quantity (dễ bị ghost reservation).
        """
        if not self.location_id or not self.product_id:
            return

        if self.location_id.usage != 'internal':
            return

        if self.state in ['done', 'cancel']:
            return

        # Tổng tồn kho vật lý (on-hand) tại tất cả sub-locations
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
        ])
        total_on_hand = sum(q.quantity for q in quants)

        # Tổng qty đã nhập tay từ CÁC PICKING KHÁC (chưa validate)
        other_done = self._get_other_pickings_total_done(
            self.product_id, self.location_id
        )

        # Available = tồn kho vật lý - hàng đã "claim" bởi picking khác
        total_available = total_on_hand - other_done

        _logger.info(
            '[MOVE_QTY] onchange | product=%s | location=%s | '
            'on_hand=%s | other_pickings_done=%s | '
            'total_available=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            total_on_hand,
            other_done,
            total_available,
            self.quantity,
        )

        if self.quantity > total_available:
            _logger.warning(
                '[MOVE_QTY] OVER_LIMIT | product=%s | qty_entered=%s | max_available=%s',
                self.product_id.display_name, self.quantity, total_available,
            )

            # Breakdown per location để user biết hàng ở đâu
            loc_details = '\n'.join(
                '  • %s: tồn kho %s cái' % (q.location_id.display_name, q.quantity)
                for q in quants if q.quantity > 0
            )

            # NOTE: KHÔNG tự reset self.quantity vì đây là computed field (aggregate từ move.lines).
            # Việc reset thực sự do stock.move.line onchange xử lý ở cấp line.
            return {
                'warning': {
                    'title': _('Vượt quá tồn kho khả dụng!'),
                    'message': _(
                        'Sản phẩm "%s" chỉ còn %s cái khả dụng tại "%s".\n'
                        'Tồn kho vật lý: %s | Đang giữ bởi đơn khác: %s\n\n'
                        'Chi tiết theo vị trí:\n%s'
                    ) % (
                        self.product_id.display_name,
                        max(0.0, total_available),
                        self.location_id.display_name,
                        total_on_hand,
                        other_done,
                        loc_details or '  (không có)',
                    )
                }
            }
