from odoo import fields, models


class HlvSalePlanMentionNotification(models.Model):
    _name = 'hlv.sale.plan.mention.notification'
    _description = 'Sale Plan Mention Notification'
    _order = 'create_date desc, id desc'

    alias = fields.Char(required=True, index=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', index=True, ondelete='cascade')
    so_name = fields.Char(index=True)
    author_name = fields.Char()
    body = fields.Text()
    preview = fields.Char()
    mentions = fields.Char(help='Comma-separated mention aliases in this event.')
    is_read = fields.Boolean(default=False, index=True)
