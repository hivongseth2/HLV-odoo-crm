from odoo import api, models, fields
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.onchange('quantity')
    def _onchange_quantity_check_stock(self):
        """
        Validate quantity against actual on-hand quantity when reserved quantity changes.
        - For internal locations only
        - For moves not yet done
        - Automatically caps quantity to available stock
        """
        if not self.location_id or not self.product_id:
            return

        # Only validate for internal locations and non-completed moves
        if self.location_id.usage != 'internal':
            return

        # Skip validation for already completed moves
        if self.move_id and self.move_id.state in ['done', 'cancel']:
            return

        # Get actual on-hand quantity at this location
        real_on_hand = self._get_available_quantity()

        # If quantity exceeds available stock, handle it
        if self.quantity > real_on_hand:
            # Cap the quantity to available stock
            old_quantity = self.quantity
            self.quantity = real_on_hand

            # Return warning notification
            return {
                'warning': {
                    'title': _('Stock Quantity Exceeded!'),
                    'message': _(
                        'Attempted to reserve %s units, but only %s units are available at location "%s".\n'
                        'Quantity has been automatically adjusted to %s units.'
                    ) % (
                        old_quantity,
                        real_on_hand,
                        self.location_id.display_name,
                        real_on_hand
                    )
                }
            }

    @api.constrains('quantity', 'location_id', 'product_id')
    def _check_quantity_not_exceed_stock(self):
        """
        Database-level constraint to prevent saving quantities exceeding available stock.
        This ensures validation even when bypassing UI (API calls, bulk operations, etc).
        """
        for record in self:
            # Skip for empty records
            if not record.product_id or not record.location_id:
                continue

            # Only validate internal locations
            if record.location_id.usage != 'internal':
                continue

            # Skip for completed moves
            if record.move_id and record.move_id.state in ['done', 'cancel']:
                continue

            # Get available quantity
            available_qty = record._get_available_quantity()

            # Check constraint
            if record.quantity > available_qty:
                raise models.ValidationError(
                    _('Cannot reserve %s units of "%s" at location "%s".\n'
                      'Only %s units are available.\n'
                      'Current Location: %s') % (
                        record.quantity,
                        record.product_id.display_name,
                        record.location_id.display_name,
                        available_qty,
                        record.location_id.display_name
                    )
                )

    def _get_available_quantity(self):
        """
        Calculate available on-hand quantity at the specified location.
        This includes:
        - Physical stock quantity
        - Excludes damaged/lost stock
        
        Returns:
            float: Available quantity
        """
        self.ensure_one()

        if not self.product_id or not self.location_id:
            return 0.0

        # Search for stock quant at this location
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ], limit=1)

        if quant:
            # Use the 'quantity' field (on-hand quantity)
            return max(0.0, quant.quantity)
        
        return 0.0

    def _get_quantity_with_reserved(self):
        """
        Get available quantity minus already reserved amounts.
        Useful for checking truly available (unreserved) quantity.
        
        Returns:
            float: Available unreserved quantity
        """
        self.ensure_one()

        available = self._get_available_quantity()

        # Find all other move lines for this product at this location
        # that are not yet done
        reserved_qty = self.env['stock.move.line'].search_read(
            [
                ('product_id', '=', self.product_id.id),
                ('location_id', '=', self.location_id.id),
                ('id', '!=', self.id),  # Exclude current line
                ('state', 'not in', ['done', 'cancel']),
            ],
            fields=['quantity']
        )

        # Sum reserved quantities
        total_reserved = sum(line['quantity'] for line in reserved_qty)

        return max(0.0, available - total_reserved)
