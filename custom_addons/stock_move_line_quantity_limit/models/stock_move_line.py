from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity')
    def _onchange_quantity_check_stock(self):
        """
        Kiểm tra số lượng nhập tay không vượt quá tồn kho tại vị trí.
        
        Công thức đơn giản: max = sum(quant.quantity) tại location (child_of).
        Dùng quant.quantity (on-hand vật lý, không bao giờ sai) thay vì query move lines.
        
        Không dựa vào move_id, picking_id, _origin — tránh hết các bug NewId/False 
        trong onchange context.
        """
        if not self.location_id or not self.product_id:
            return
        if self.location_id.usage != 'internal':
            return
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Tồn kho vật lý tại location + sub-locations
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
        ])
        stock_at_location = sum(q.quantity for q in quants)

        _logger.info(
            '[QTY_LIMIT] onchange | product=%s | location=%s (id=%s) | '
            'on_hand=%s | qty_entered=%s',
            self.product_id.display_name,
            self.location_id.display_name,
            self.location_id.id,
            stock_at_location,
            self.quantity,
        )

        if self.quantity > stock_at_location:
            old_qty = self.quantity
            self.quantity = max(0.0, stock_at_location)

            _logger.warning(
                '[QTY_LIMIT] BLOCKED | product=%s | location=%s | '
                'qty_entered=%s | on_hand=%s | adjusted_to=%s',
                self.product_id.display_name,
                self.location_id.display_name,
                old_qty,
                stock_at_location,
                self.quantity,
            )

            return {
                'warning': {
                    'title': _('Vượt quá tồn kho tại vị trí!'),
                    'message': _(
                        'Vị trí "%s" chỉ có %s cái trong kho.\n'
                        'Hệ thống đã tự động điều chỉnh từ %s thành %s cái.'
                    ) % (
                        self.location_id.display_name,
                        stock_at_location,
                        old_qty,
                        self.quantity,
                    )
                }
            }
