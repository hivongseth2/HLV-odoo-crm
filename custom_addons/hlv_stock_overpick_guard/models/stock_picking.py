from collections import defaultdict

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

# Picking/move fields whose write may add or change move lines.
PICKING_TRIGGER_FIELDS = {
    'move_ids', 'move_ids_without_package', 'move_line_ids',
    'move_line_ids_without_package', 'location_id',
}
MOVE_TRIGGER_FIELDS = {'move_line_ids', 'quantity', 'location_id'}
LINE_KEY_FIELDS = {'location_id', 'lot_id', 'package_id', 'owner_id', 'product_id', 'product_uom_id'}

# Context set while a picking/move write is running: nested move-line writes skip
# their own check, and the parent checks once at the end. Otherwise one2many
# commands (create the new 22 line before setting the old line to 0) would raise
# on an intermediate state.
DEFER_CTX = 'hlv_overpick_defer'
SKIP_CTX = 'hlv_skip_overpick_check'


def _line_key(ml):
    return ml.product_id, ml.location_id, ml.lot_id, ml.package_id, ml.owner_id


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _hlv_check_overpick(self, keys=None, validating=False):
        """For each picking, the total move-line qty taken from one quant
        (product, location, lot, package, owner) must not exceed that quant's on-hand qty.

        keys: only check these keys (None = all of them).
        validating: only count lines that _action_done will actually process (mirrors the core picked logic).
        """
        if self.env.context.get(SKIP_CTX):
            return
        Quant = self.env['stock.quant']
        errors = []
        for picking in self.filtered(lambda p: p.state not in ('done', 'cancel')):
            lines = picking.move_line_ids.filtered(
                lambda ml: ml.state not in ('done', 'cancel')
                and ml.quantity > 0
                and ml.location_id.usage == 'internal'
                and ml.product_id.is_storable
            )
            if validating and any(picking.move_ids.mapped('picked')):
                # Core: if any move is picked, only picked lines of picked moves are processed.
                lines = lines.filtered(lambda ml: ml.picked and ml.move_id.picked)
            totals = defaultdict(float)
            for ml in lines:
                totals[_line_key(ml)] += ml.quantity_product_uom
            for key, qty in totals.items():
                if keys is not None and key not in keys:
                    continue
                product, location, lot, package, owner = key
                on_hand = sum(Quant._gather(
                    product, location, lot_id=lot, package_id=package, owner_id=owner, strict=True,
                ).mapped('quantity'))
                if float_compare(qty, on_hand, precision_rounding=product.uom_id.rounding) > 0:
                    errors.append(_(
                        '• %(picking)s | %(product)s%(lot)s tại %(location)s: lấy %(qty)s nhưng tồn chỉ có %(on_hand)s %(uom)s',
                        picking=picking.name,
                        product=product.display_name,
                        lot=_(' (lô %s)', lot.name) if lot else '',
                        location=location.complete_name,
                        qty=qty,
                        on_hand=on_hand,
                        uom=product.uom_id.name,
                    ))
        if errors:
            raise UserError(_(
                'Tổng số lượng lấy vượt quá tồn kho thực tế tại vị trí (sẽ gây âm kho):\n\n%s\n\n'
                'Vui lòng kiểm tra các dòng chi tiết: có thể đang lấy trùng cùng một vị trí/lô ở nhiều dòng.',
                '\n'.join(errors),
            ))

    def write(self, vals):
        if self.env.context.get(DEFER_CTX) or not PICKING_TRIGGER_FIELDS & set(vals):
            return super().write(vals)
        res = super(StockPicking, self.with_context(**{DEFER_CTX: True})).write(vals)
        self._hlv_check_overpick()
        return res

    def button_validate(self):
        # Stock may have dropped between entering the qty and validating (another picking was validated).
        self._hlv_check_overpick(validating=True)
        return super().button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        if self.env.context.get(DEFER_CTX) or not MOVE_TRIGGER_FIELDS & set(vals):
            return super().write(vals)
        res = super(StockMove, self.with_context(**{DEFER_CTX: True})).write(vals)
        self.picking_id._hlv_check_overpick()
        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _hlv_check_lines_overpick(self):
        lines = self.filtered(lambda ml: ml.picking_id and ml.quantity > 0)
        if lines:
            lines.picking_id._hlv_check_overpick(keys={_line_key(ml) for ml in lines})

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get(DEFER_CTX):
            lines._hlv_check_lines_overpick()
        return lines

    def write(self, vals):
        if self.env.context.get(DEFER_CTX) or not ({'quantity'} | LINE_KEY_FIELDS) & set(vals):
            return super().write(vals)
        old_qty = {ml.id: ml.quantity for ml in self}
        res = super().write(vals)
        if LINE_KEY_FIELDS & set(vals):
            changed = self
        else:
            # Quantity-only write: only increases can cause an overpick. Skipping decreases
            # avoids false alarms when core frees reservations during another picking's _action_done.
            changed = self.filtered(lambda ml: ml.quantity > old_qty[ml.id])
        changed._hlv_check_lines_overpick()
        return res
