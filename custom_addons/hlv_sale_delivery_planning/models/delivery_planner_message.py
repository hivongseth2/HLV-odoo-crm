from odoo import api, fields, models


class DeliveryPlannerMessage(models.Model):
    _name = 'hlv.sale.plan.message'
    _description = 'HLV Sale Plan Message Notification'
    _order = 'last_message_date desc, id desc'
    _sql_constraints = [
        ('uniq_sale_order_notification_user', 'unique(sale_order_id, user_id)', 'Each user can have only one notification row per sale order.'),
    ]

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        index=True,
        ondelete='cascade',
        default=lambda self: self.env.user.id,
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        index=True,
        ondelete='cascade',
    )
    last_message_author = fields.Char(string='Last Message Author')
    last_message_preview = fields.Text(string='Last Message Preview')
    last_message_date = fields.Datetime(string='Last Message Date', index=True)
    is_read = fields.Boolean(string='Read', default=False, index=True)
    message_type = fields.Selection(
        [('customer', 'Customer'), ('internal', 'Internal')],
        string='Message Type',
        default='customer',
    )

    @api.model
    def _internal_user_ids(self):
        users = self.env['res.users'].sudo().search([
            ('share', '=', False),
            ('active', '=', True),
        ])
        return users.ids

    @api.model
    def upsert_for_sale_order(self, sale_order, author_name='', preview='', message_type='customer'):
        order = sale_order if getattr(sale_order, '_name', False) == 'sale.order' else self.env['sale.order'].browse(int(sale_order))
        if not order.exists():
            return self

        base_values = {
            'sale_order_id': order.id,
            'last_message_author': (author_name or '').strip(),
            'last_message_preview': (preview or '').strip(),
            'last_message_date': fields.Datetime.now(),
            'is_read': False,
            'message_type': message_type or 'customer',
        }
        user_ids = self._internal_user_ids()
        if not user_ids:
            return self

        records = self.search([
            ('sale_order_id', '=', order.id),
            ('user_id', 'in', user_ids),
        ])
        by_uid = {r.user_id.id: r for r in records}

        to_create = []
        for uid in user_ids:
            rec = by_uid.get(uid)
            if rec:
                rec.write(base_values)
            else:
                vals = dict(base_values)
                vals['user_id'] = uid
                to_create.append(vals)
        if to_create:
            self.create(to_create)
        return self.search([
            ('sale_order_id', '=', order.id),
            ('user_id', '=', self.env.uid),
        ], limit=1)

    @api.model
    def list_for_current_user(self, limit=100):
        return self.search_read(
            [('user_id', '=', self.env.uid)],
            ['id', 'sale_order_id', 'last_message_author', 'last_message_preview', 'last_message_date', 'is_read'],
            limit=int(limit or 100),
            order='last_message_date desc, id desc',
        )

    @api.model
    def mark_read_for_sale_order(self, sale_order_id):
        record = self.search([
            ('sale_order_id', '=', int(sale_order_id)),
            ('user_id', '=', self.env.uid),
        ], limit=1)
        if record:
            record.write({'is_read': True})
        return record

    @api.model
    def unread_count(self):
        return self.search_count([
            ('user_id', '=', self.env.uid),
            ('is_read', '=', False),
        ])
