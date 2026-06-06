# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HlvContactSplitWizard(models.TransientModel):
    _name = 'hlv.contact.split.wizard'
    _description = 'Tách liên hệ thành root company mới'

    source_partner_id = fields.Many2one(
        'res.partner',
        string='Liên hệ nguồn',
        required=True,
    )
    new_name = fields.Char(string='Tên công ty mới', required=True)
    new_ref = fields.Char(string='Mã khách MISA', required=True)
    new_vat = fields.Char(string='Mã số thuế')
    child_partner_ids = fields.Many2many(
        'res.partner',
        string='Liên hệ con chuyển sang công ty mới',
    )
    sale_order_ids = fields.Many2many(
        'sale.order',
        string='Đơn bán chuyển sang công ty mới',
    )
    purchase_order_ids = fields.Many2many(
        'purchase.order',
        string='Đơn mua chuyển sang công ty mới',
    )
    new_partner_id = fields.Many2one(
        'res.partner',
        string='Công ty mới',
        readonly=True,
    )
    note = fields.Text(
        string='Ghi chú',
        default=(
            'Dùng khi cùng tên công ty nhưng MISA có nhiều mã khách. '
            'Root mới sẽ được tạo theo khóa MST + mã khách; ref và '
            'company_registry đều nhận mã khách MISA.'
        ),
        readonly=True,
    )

    @api.onchange('source_partner_id')
    def _onchange_source_partner_id(self):
        if not self.source_partner_id:
            return
        self.new_name = self.source_partner_id.name
        self.new_vat = self.source_partner_id.vat

    def action_split(self):
        self.ensure_one()
        source = self.source_partner_id.sudo()
        code = (self.new_ref or '').strip()
        vat = (self.new_vat or '').strip()
        if not code:
            raise UserError(_('Cần nhập mã khách MISA để tách.'))

        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        domain = [
            ('parent_id', '=', False),
            ('is_company', '=', True),
            '|',
            ('ref', '=', code),
            ('company_registry', '=', code),
        ]
        existing = Partner.search(domain)
        if vat:
            existing = existing.filtered(lambda p: not p.vat or (p.vat or '').strip() == vat)
        if existing:
            new_partner = existing[:1]
        else:
            vals = {
                'name': self.new_name,
                'is_company': True,
                'customer_rank': max(source.customer_rank, 1),
                'supplier_rank': source.supplier_rank,
                'ref': code,
                'company_registry': code,
                'vat': vat or False,
                'street': source.street,
                'street2': source.street2,
                'city': source.city,
                'state_id': source.state_id.id,
                'country_id': source.country_id.id,
                'phone': source.phone,
                'mobile': source.mobile,
                'email': source.email,
            }
            new_partner = Partner.create(vals)
            new_partner.message_post(body=_(
                'Tạo root company mới từ %s theo khóa %s-%s.'
            ) % (source.display_name, vat or '-', code))

        if self.child_partner_ids:
            self.child_partner_ids.sudo().write({'parent_id': new_partner.id})
        if self.sale_order_ids:
            self.sale_order_ids.sudo().write({'partner_id': new_partner.id})
        if self.purchase_order_ids:
            self.purchase_order_ids.sudo().write({'partner_id': new_partner.id})

        self.new_partner_id = new_partner.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': new_partner.id,
            'view_mode': 'form',
            'target': 'current',
        }
