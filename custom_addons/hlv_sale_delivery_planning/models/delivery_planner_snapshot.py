from odoo import api, fields, models


class DeliveryPlannerSnapshot(models.Model):
    _name = 'hlv.delivery.planner.snapshot'
    _description = 'Delivery Planner Snapshot'
    _rec_name = 'sale_order_id'

    sale_order_id = fields.Many2one(
        'sale.order',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one('res.company', index=True)
    warehouse_id = fields.Many2one('stock.warehouse', index=True)
    partner_id = fields.Many2one('res.partner', index=True)
    state = fields.Selection(
        related='sale_order_id.state',
        store=True,
        index=True,
    )
    commitment_date = fields.Datetime(index=True)
    date_order = fields.Datetime(index=True)
    misa_order_date = fields.Date(index=True)

    stock_status = fields.Selection([
        ('ready', 'Ready'),
        ('partial_ready', 'Partial Ready'),
        ('out_of_stock', 'Out of Stock'),
        ('delivered', 'Delivered'),
        ('unknown', 'Unknown'),
    ], default='unknown', index=True)
    packing_status = fields.Selection([
        ('fully_packed', 'Fully Packed'),
        ('unpacked', 'Unpacked'),
        ('waiting_stock', 'Waiting Stock'),
        ('delivered', 'Delivered'),
        ('unknown', 'Unknown'),
    ], default='unknown', index=True)
    real_delivery_status = fields.Selection([
        ('unshipped', 'Unshipped'),
        ('partial', 'Partial'),
        ('full', 'Full'),
        ('unknown', 'Unknown'),
    ], default='unknown', index=True)

    is_returned_or_stopped = fields.Boolean(index=True)
    has_active_pick_printed = fields.Boolean(index=True)
    has_shipper_received = fields.Boolean(index=True)
    has_delivered_today = fields.Boolean(index=True)
    has_assigned_pick = fields.Boolean(index=True)

    dirty = fields.Boolean(default=True, index=True)
    dirty_reason = fields.Char()
    last_computed_at = fields.Datetime(index=True)

    _sql_constraints = [
        (
            'sale_order_unique',
            'unique(sale_order_id)',
            'Each sale order can only have one delivery planner snapshot.',
        ),
    ]

    @api.model
    def mark_dirty_for_sale_orders(self, sale_order_ids, reason=''):
        ids = [int(so_id) for so_id in (sale_order_ids or []) if so_id]
        if not ids:
            return

        existing = self.sudo().search([('sale_order_id', 'in', ids)])
        existing.write({
            'dirty': True,
            'dirty_reason': reason or 'changed',
        })

        existing_so_ids = set(existing.mapped('sale_order_id').ids)
        missing_ids = [so_id for so_id in ids if so_id not in existing_so_ids]
        if missing_ids:
            orders = self.env['sale.order'].sudo().browse(missing_ids).exists()
            self.sudo().create([self._snapshot_base_vals(order, dirty=True, reason=reason) for order in orders])

    @api.model
    def upsert_from_status_data(self, sales, status_by_so):
        sales = sales.exists()
        if not sales:
            return

        snapshots = self.sudo().search([('sale_order_id', 'in', sales.ids)])
        by_so_id = {snap.sale_order_id.id: snap for snap in snapshots}
        now = fields.Datetime.now()

        to_create = []
        for order in sales:
            status = status_by_so.get(order.id, {})
            vals = self._snapshot_base_vals(order, dirty=False)
            vals.update({
                'stock_status': status.get('stock_status') or 'unknown',
                'packing_status': status.get('packing_status') or 'unknown',
                'real_delivery_status': status.get('real_delivery_status') or 'unknown',
                'is_returned_or_stopped': bool(status.get('is_returned_or_stopped')),
                'has_active_pick_printed': bool(status.get('has_active_pick_printed')),
                'has_shipper_received': bool(status.get('has_shipper_received')),
                'has_delivered_today': bool(status.get('has_delivered_today')),
                'has_assigned_pick': bool(status.get('has_assigned_pick')),
                'dirty': False,
                'dirty_reason': False,
                'last_computed_at': now,
            })
            snap = by_so_id.get(order.id)
            if snap:
                snap.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            self.sudo().create(to_create)

    @api.model
    def _snapshot_base_vals(self, order, dirty=False, reason=''):
        return {
            'sale_order_id': order.id,
            'company_id': order.company_id.id if order.company_id else False,
            'warehouse_id': order.warehouse_id.id if order.warehouse_id else False,
            'partner_id': order.partner_id.id if order.partner_id else False,
            'commitment_date': order.commitment_date or False,
            'date_order': order.date_order or False,
            'misa_order_date': order.x_studio_misa_order_date or False,
            'dirty': dirty,
            'dirty_reason': reason or False,
        }
