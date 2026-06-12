"""Delivery planner per-sale-order status snapshot.

The dashboard uses this model as a warm, indexed cache for delivery/packing
status. It is marked dirty by sale/stock hooks and refreshed by the existing
realtime status pipeline, so the dashboard can avoid recomputing every order
on every request once snapshots are clean.
"""

from odoo import api, fields, models

SNAPSHOT_LOGIC_VERSION = 'service_receipt_amount_v4'


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
    is_new_order = fields.Boolean(index=True)

    dirty = fields.Boolean(default=True, index=True)
    dirty_reason = fields.Char()
    last_computed_at = fields.Datetime(index=True)
    snapshot_date = fields.Date(index=True)
    logic_version = fields.Char(default=SNAPSHOT_LOGIC_VERSION, index=True)

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

        existing = self.sudo().search([
            ('sale_order_id', 'in', ids),
            ('dirty', '=', False),
        ])
        existing.write({
            'dirty': True,
            'dirty_reason': reason or 'changed',
        })

    @api.model
    def upsert_from_status_data(self, sales, status_by_so):
        sales = sales.exists()
        if not sales:
            return

        snapshots = self.sudo().search([('sale_order_id', 'in', sales.ids)])
        by_so_id = {snap.sale_order_id.id: snap for snap in snapshots}
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)

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
                'is_new_order': self._is_order_new_today(order),
                'dirty': False,
                'dirty_reason': False,
                'last_computed_at': now,
                'snapshot_date': today,
                'logic_version': SNAPSHOT_LOGIC_VERSION,
            })
            snap = by_so_id.get(order.id)
            if snap:
                snap.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            self.sudo().create(to_create)

    @api.model
    def cron_refresh_dirty_snapshots(self, limit=50):
        limit = max(int(limit or 50), 1)
        snapshot_model = self.sudo()
        snapshot_model._ensure_missing_active_snapshots(limit=limit)

        today = fields.Date.context_today(self)
        snapshots = snapshot_model.search([
            '|',
            ('dirty', '=', True),
            ('snapshot_date', '!=', today),
        ], order='write_date asc, id asc', limit=limit)
        orders = snapshots.mapped('sale_order_id').exists()
        if not orders:
            return 0

        service = self.env['hlv.delivery.planner.service'].sudo()
        _sales, _matched_ids, _stats, _availability, _on_hand, status_by_so = \
            service._calculate_po_and_stock_status(
                orders,
                po_date_from='',
                po_date_to='',
                po_status='all',
                filter_delivery_status='all',
                filter_stock_status='all',
                filter_packing_status='all',
                show_completed=True,
                filter_need_transfer=False,
                filter_new_orders=False,
                filter_done_date_from='',
                filter_done_date_to='',
                filter_print_status='all',
                filter_shipper_received='all',
            )
        snapshot_model.upsert_from_status_data(orders, status_by_so)
        return len(orders)

    @api.model
    def _ensure_missing_active_snapshots(self, limit=50):
        self.env.cr.execute("""
            SELECT so.id
              FROM sale_order so
             WHERE so.state IN ('sale', 'done')
               AND NOT EXISTS (
                    SELECT 1
                      FROM hlv_delivery_planner_snapshot snap
                     WHERE snap.sale_order_id = so.id
               )
             ORDER BY so.id
             LIMIT %s
        """, [int(limit or 50)])
        order_ids = [row[0] for row in self.env.cr.fetchall()]
        if not order_ids:
            return
        orders = self.env['sale.order'].sudo().browse(order_ids).exists()
        self.sudo().create([
            self._snapshot_base_vals(order, dirty=True, reason='missing')
            for order in orders
        ])

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

    @api.model
    def _is_order_new_today(self, order):
        today = fields.Date.context_today(self)
        order_date = order.x_studio_misa_order_date
        if not order_date and order.date_order:
            order_date = order.date_order.date()
        return bool(order_date and order_date == today)
