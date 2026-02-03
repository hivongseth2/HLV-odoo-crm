# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zalo_user_id = fields.Char(
        string='Zalo User ID',
        help='Zalo Official Account user identifier',
        index=True,
    )
    zalo_conversation_ids = fields.One2many(
        'zalo.chat.conversation',
        'partner_id',
        string='Zalo Conversations',
    )
    zalo_conversation_count = fields.Integer(
        string='Zalo Conversations',
        compute='_compute_zalo_conversation_count',
    )

    _sql_constraints = [
        ('zalo_user_id_unique', 'UNIQUE(zalo_user_id)', 
         'Another contact already has this Zalo User ID!'),
    ]

    @api.depends('zalo_conversation_ids')
    def _compute_zalo_conversation_count(self):
        """Count Zalo conversations for this partner"""
        for partner in self:
            partner.zalo_conversation_count = len(partner.zalo_conversation_ids)

    def action_view_zalo_conversations(self):
        """Open Zalo conversations for this partner"""
        self.ensure_one()
        return {
            'name': _('Zalo Conversations'),
            'type': 'ir.actions.act_window',
            'res_model': 'zalo.chat.conversation',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'create': False},
        }
