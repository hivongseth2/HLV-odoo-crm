from odoo import api, fields, models


class DeliveryPlannerMessage(models.Model):
    _name = 'hlv.sale.plan.message'
    _description = 'HLV Sale Plan Message Notification'
    _order = 'last_message_date desc, id desc'
    _sql_constraints = [
        ('uniq_sale_order_notification', 'unique(sale_order_id)', 'Each sale order can have only one notification row.'),
    ]

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
    def upsert_for_sale_order(self, sale_order, author_name='', preview='', message_type='customer'):
        order = sale_order if getattr(sale_order, '_name', False) == 'sale.order' else self.env['sale.order'].browse(int(sale_order))
        if not order.exists():
            return self

        values = {
            'sale_order_id': order.id,
            'last_message_author': (author_name or '').strip(),
            'last_message_preview': (preview or '').strip(),
            'last_message_date': fields.Datetime.now(),
            'is_read': False,
            'message_type': message_type or 'customer',
        }
        record = self.search([('sale_order_id', '=', order.id)], limit=1)
        if record:
            record.write(values)
        else:
            record = self.create(values)
        return record

    @api.model
    def mark_read_for_sale_order(self, sale_order_id):
        record = self.search([('sale_order_id', '=', int(sale_order_id))], limit=1)
        if record:
            record.write({'is_read': True})
        return record

    @api.model
    def unread_count(self):
        return self.search_count([('is_read', '=', False)])
