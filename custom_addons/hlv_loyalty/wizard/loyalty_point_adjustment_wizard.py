# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class HlvLoyaltyPointAdjustmentWizard(models.TransientModel):
    _name = 'hlv.loyalty.point.adjustment.wizard'
    _description = 'Wizard Điều chỉnh điểm thủ công'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, readonly=True,
    )
    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản Loyalty', required=True,
        domain="[('partner_id', '=', partner_id), ('active', '=', True)]",
        help='Điểm được cộng/trừ trực tiếp ở tài khoản này (mỗi công ty có thể có nhiều tài khoản).',
    )
    point_type = fields.Selection([
        ('ranking', 'Điểm xếp hạng'),
        ('exchange', 'Điểm đổi thưởng'),
    ], string='Loại điểm', required=True, default='exchange',
        help='Ranking: ảnh hưởng tới hạng thành viên.\nExchange: dùng để đổi voucher/tiền.')
    point_amount = fields.Integer(
        string='Số điểm điều chỉnh', required=True,
        help='Nhập số dương để cộng điểm, số âm để trừ điểm. VD: 100 hoặc -50',
    )
    description = fields.Char(
        string='Lý do / Ghi chú', required=True,
        placeholder='VD: Tặng điểm sự kiện, Thu hồi điểm sai,...',
    )

    @api.onchange('partner_id')
    def _onchange_partner_id_default_account(self):
        if self.partner_id:
            root = self.partner_id._get_loyalty_root()
            self.account_id = (
                root.loyalty_portal_account_ids.filtered('is_default')[:1]
                or root.loyalty_portal_account_ids[:1]
            )

    @api.constrains('point_amount')
    def _check_point_amount(self):
        for rec in self:
            if rec.point_amount == 0:
                raise UserError('Số điểm điều chỉnh không được bằng 0!')

    def action_adjust(self):
        self.ensure_one()
        root = self.partner_id._get_loyalty_root()
        self.env['hlv.loyalty.history'].sudo().create({
            'partner_id': root.id,
            'account_id': self.account_id.id,
            'transaction_type': 'manual',
            'point_type': self.point_type,
            'point_amount': self.point_amount,
            'description': self.description,
            'state': 'confirmed',
            'company_id': self.env.company.id,
        })
        return {'type': 'ir.actions.act_window_close'}
