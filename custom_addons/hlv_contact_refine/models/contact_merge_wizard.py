# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HlvContactMergeWizard(models.TransientModel):
    _name = 'hlv.contact.merge.wizard'
    _description = 'Gộp liên hệ'

    source_partner_ids = fields.Many2many(
        'res.partner',
        string='Liên hệ cần gộp',
        required=True,
    )
    destination_partner_id = fields.Many2one(
        'res.partner',
        string='Giữ lại liên hệ',
        required=True,
    )
    note = fields.Text(
        string='Ghi chú',
        default=(
            'Chọn liên hệ chuẩn để giữ lại. Chức năng này gọi cơ chế merge '
            'chuẩn của Odoo nếu hệ thống có model base.partner.merge.automatic.wizard.'
        ),
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        partners = self.env['res.partner'].browse(self.env.context.get('active_ids') or [])
        if partners and 'source_partner_ids' in fields_list and not vals.get('source_partner_ids'):
            vals['source_partner_ids'] = [(6, 0, partners.ids)]
        if partners and 'destination_partner_id' in fields_list and not vals.get('destination_partner_id'):
            root_company = partners.filtered(lambda p: p.is_company and not p.parent_id)[:1]
            vals['destination_partner_id'] = (root_company or partners[:1]).id
        return vals

    def action_merge(self):
        self.ensure_one()
        partners = self.source_partner_ids | self.destination_partner_id
        partners = partners.exists()
        if len(partners) < 2:
            raise UserError(_('Cần chọn ít nhất 2 liên hệ để gộp.'))
        if self.destination_partner_id not in partners:
            raise UserError(_('Liên hệ giữ lại phải nằm trong danh sách cần gộp.'))

        if 'base.partner.merge.automatic.wizard' not in self.env:
            raise UserError(_('Database này chưa có wizard merge chuẩn của Odoo.'))

        MergeWizard = self.env['base.partner.merge.automatic.wizard'].sudo()
        vals = {}
        if 'partner_ids' in MergeWizard._fields:
            vals['partner_ids'] = [(6, 0, partners.ids)]
        if 'dst_partner_id' in MergeWizard._fields:
            vals['dst_partner_id'] = self.destination_partner_id.id
        if 'group_by_email' in MergeWizard._fields:
            vals['group_by_email'] = False
        if 'group_by_name' in MergeWizard._fields:
            vals['group_by_name'] = False

        wizard = MergeWizard.with_context(active_ids=partners.ids).create(vals)
        for method_name in ('action_merge', 'merge_cb', '_merge'):
            if hasattr(wizard, method_name):
                result = getattr(wizard, method_name)()
                self.destination_partner_id.message_post(body=_(
                    'Đã gộp các liên hệ %s vào liên hệ này từ HLV Contact Refine.'
                ) % ', '.join(str(pid) for pid in partners.ids))
                return result or {'type': 'ir.actions.act_window_close'}

        raise UserError(_('Không tìm thấy method merge trên wizard chuẩn của Odoo.'))
