# -*- coding: utf-8 -*-
import json
import logging
from itertools import groupby

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_hlv_pos_source_location(self, line):
        location = line.hlv_source_location_id
        if not location or line.qty <= 0 or location.usage != 'internal':
            return self.env['stock.location']
        return location

    def _get_hlv_pos_source_allocations(self, line):
        if line.qty <= 0:
            return []
        raw = line.hlv_source_location_allocations
        if not raw:
            location = self._get_hlv_pos_source_location(line)
            return [{'location': location, 'qty': abs(line.qty)}] if location else []
        try:
            data = json.loads(raw) or []
        except Exception:
            _logger.warning('[HLV POS SOURCE] Invalid allocation JSON on POS line %s', line.id)
            return []

        allocations = []
        Location = self.env['stock.location'].sudo()
        for item in data:
            location_id = int(item.get('location_id') or 0)
            qty = float(item.get('qty') or 0.0)
            if not location_id or qty <= 0:
                continue
            location = Location.browse(location_id).exists()
            if location and location.usage == 'internal':
                allocations.append({'location': location, 'qty': qty})
        return allocations

    def _hlv_pos_grouping_key(self, line):
        location = self._get_hlv_pos_source_location(line)
        return (
            line.product_id.id,
            tuple(sorted(line.attribute_value_ids.ids)),
            location.id or False,
        )

    def _prepare_hlv_allocated_stock_move_vals(self, line, allocation):
        vals = super()._prepare_stock_move_vals(line, line)
        vals['product_uom_qty'] = allocation['qty']
        vals['location_id'] = allocation['location'].id
        return vals

    def _get_hlv_available_qty(self, product, location):
        grouped = self.env['stock.quant'].sudo().read_group(
            [
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ],
            ['quantity:sum', 'reserved_quantity:sum'],
            [],
        )
        row = grouped and grouped[0] or {}
        return (row.get('quantity', 0.0) or 0.0) - (row.get('reserved_quantity', 0.0) or 0.0)

    def _validate_hlv_pos_source_allocations(self, stockable_lines):
        requested = {}
        for line in stockable_lines.filtered(lambda item: item.qty > 0):
            allocations = self._get_hlv_pos_source_allocations(line)
            if not allocations:
                continue
            allocated_qty = sum(item['qty'] for item in allocations)
            expected_qty = abs(line.qty)
            if abs(allocated_qty - expected_qty) > 0.0001:
                raise UserError(_(
                    'POS source locations for %s allocate %.2f but the sold quantity is %.2f.'
                ) % (line.product_id.display_name, allocated_qty, expected_qty))
            for allocation in allocations:
                key = (line.product_id.id, allocation['location'].id)
                requested.setdefault(key, {
                    'product': line.product_id,
                    'location': allocation['location'],
                    'qty': 0.0,
                })
                requested[key]['qty'] += allocation['qty']

        for item in requested.values():
            available = self._get_hlv_available_qty(item['product'], item['location'])
            if item['qty'] > available + 0.0001:
                raise UserError(_(
                    'Not enough stock for %s at %s. Requested %.2f, available %.2f.'
                ) % (
                    item['product'].display_name,
                    item['location'].complete_name,
                    item['qty'],
                    available,
                ))

    def _create_move_from_pos_order_lines(self, lines):
        self.ensure_one()
        stockable_lines = lines.filtered(
            lambda line: line.product_id.type == 'consu'
            and not float_is_zero(line.qty, precision_rounding=line.product_id.uom_id.rounding)
        )
        if not stockable_lines:
            return

        self._validate_hlv_pos_source_allocations(stockable_lines)

        allocated_lines = stockable_lines.filtered(lambda line: line.qty > 0 and line.hlv_source_location_allocations)
        normal_lines = stockable_lines - allocated_lines
        move_vals = []

        for line in allocated_lines:
            for allocation in self._get_hlv_pos_source_allocations(line):
                move_vals.append(self._prepare_hlv_allocated_stock_move_vals(line, allocation))

        lines_by_key = groupby(
            sorted(normal_lines, key=self._hlv_pos_grouping_key),
            key=self._hlv_pos_grouping_key,
        )
        for _key, order_lines_group in lines_by_key:
            order_lines = self.env['pos.order.line'].concat(*order_lines_group)
            move_vals.append(self._prepare_stock_move_vals(order_lines[0], order_lines))

        if not move_vals:
            return

        moves = self.env['stock.move'].create(move_vals)
        confirmed_moves = moves._action_confirm()
        confirmed_moves._add_mls_related_to_order(lines, are_qties_done=True)
        confirmed_moves.picked = True
        self._link_owner_on_return_picking(lines)

    def _prepare_stock_move_vals(self, first_line, order_lines):
        res = super()._prepare_stock_move_vals(first_line, order_lines)

        source_location = self._get_hlv_pos_source_location(first_line)
        if source_location:
            res['location_id'] = source_location.id

        if first_line.qty < 0 and first_line.refunded_orderline_id:
            try:
                orig_line = first_line.refunded_orderline_id
                orig_order = orig_line.order_id
                all_ml = orig_order.sudo().picking_ids.move_line_ids.filtered(
                    lambda ml: ml.product_id == first_line.product_id and ml.quantity > 0
                )
                orig_move_lines = all_ml.filtered(lambda ml: ml.location_dest_id.usage == 'customer')
                if not orig_move_lines:
                    orig_move_lines = all_ml

                if orig_move_lines:
                    target_ml = sorted(
                        orig_move_lines,
                        key=lambda x: len(x.location_id.complete_name.split('/')),
                        reverse=True,
                    )[0]
                    target_loc = target_ml.location_id
                    if target_loc:
                        _logger.info(
                            '[HLV POS RETURN] Move dest -> %s for %s',
                            target_loc.complete_name,
                            first_line.product_id.name,
                        )
                        res['location_dest_id'] = target_loc.id
            except Exception as e:
                _logger.error('[HLV POS RETURN] Error in _prepare_stock_move_vals: %s', str(e))

        return res
