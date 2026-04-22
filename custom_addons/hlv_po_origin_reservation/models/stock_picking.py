import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Odoo 18: khong co state 'partially_available' rieng - picking reserve 1 phan van la 'assigned'
NEEDS_RESERVE_STATES = ['confirmed', 'waiting', 'assigned']


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        incoming_pickings = self.filtered(
            lambda p: p.picking_type_code == 'incoming' and p.state != 'done'
        )

        res = super().button_validate()

        for picking in incoming_pickings:
            if picking.state == 'done':
                self._reserve_for_origin_sale_order(picking)

        return res

    def _reserve_for_origin_sale_order(self, picking):
        purchase_order = picking.purchase_id
        incoming_product_ids = picking.move_ids.filtered(
            lambda m: m.state == 'done'
        ).mapped('product_id').ids

        if not incoming_product_ids:
            return

        reserved = False
        origin = (purchase_order.origin or '').strip() if purchase_order else ''

        if origin:
            reserved = self._reserve_by_origin(purchase_order, incoming_product_ids)

        if not reserved:
            self._reserve_for_oldest_waiting_so(picking, incoming_product_ids)

    def _reserve_by_origin(self, purchase_order, incoming_product_ids):
        origin = purchase_order.origin
        origin_parts = [p.strip() for p in origin.split(',') if p.strip()]

        SaleOrder = self.env['sale.order']
        reserved_any = False

        for part in origin_parts:
            sale_order = SaleOrder.search([('name', '=', part)], limit=1)
            if not sale_order or not sale_order.procurement_group_id:
                continue

            delivery_pickings = self.env['stock.picking'].search([
                ('group_id', '=', sale_order.procurement_group_id.id),
                ('state', 'in', NEEDS_RESERVE_STATES),
                ('picking_type_code', 'in', ['outgoing', 'internal']),
            ])

            delivery_pickings = delivery_pickings.filtered(
                lambda p: any(
                    m.product_uom_qty > m.quantity
                    for m in p.move_ids
                    if m.state not in ('done', 'cancel')
                )
            )

            if delivery_pickings:
                _logger.info(
                    'PO %s (origin=%s): Giu hang cho SO %s - phieu giao: %s',
                    purchase_order.name,
                    origin,
                    sale_order.name,
                    ', '.join(delivery_pickings.mapped('name')),
                )
                moves_to_assign = delivery_pickings.move_ids.filtered(
                    lambda m: m.product_uom_qty > m.quantity
                    and m.state not in ('done', 'cancel')
                )
                moves_to_assign._action_assign()
                reserved_any = True

        return reserved_any

    def _reserve_for_oldest_waiting_so(self, picking, incoming_product_ids):
        warehouse = picking.picking_type_id.warehouse_id

        domain = [
            ('picking_type_code', 'in', ['outgoing', 'internal']),
            ('state', 'in', NEEDS_RESERVE_STATES),
        ]
        if warehouse:
            domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))

        waiting_pickings = self.env['stock.picking'].search(
            domain, order='scheduled_date asc, id asc',
        )

        incoming_product_set = set(incoming_product_ids)
        pickings_to_reserve = waiting_pickings.filtered(
            lambda p: (
                bool(
                    set(p.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')
                    ).mapped('product_id').ids) & incoming_product_set
                )
                and any(
                    m.product_uom_qty > m.quantity
                    for m in p.move_ids
                    if m.state not in ('done', 'cancel')
                )
            )
        )

        if pickings_to_reserve:
            _logger.info(
                'Nhap kho %s (fallback oldest): Giu hang cho %d phieu giao (warehouse %s): %s',
                picking.name,
                len(pickings_to_reserve),
                warehouse.name if warehouse else 'all',
                ', '.join(pickings_to_reserve.mapped('name')),
            )
            for p in pickings_to_reserve:
                moves = p.move_ids.filtered(
                    lambda m: m.product_uom_qty > m.quantity
                    and m.state not in ('done', 'cancel')
                )
                moves._action_assign()
