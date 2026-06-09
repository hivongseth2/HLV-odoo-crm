# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HlvContactMergeWizard(models.TransientModel):
    _name = 'hlv.contact.merge.wizard'
    _description = 'Gop lien he'

    source_partner_ids = fields.Many2many(
        'res.partner',
        string='Lien he can gop',
        required=True,
    )
    destination_partner_id = fields.Many2one(
        'res.partner',
        string='Giu lai lien he',
        required=True,
    )
    note = fields.Text(
        string='Ghi chu',
        default=(
            'Chon lien he chuan de giu lai. Field nao tren lien he goc dang trong '
            'thi lay tu lien he bi gop. Don ban, don mua va lien he con se duoc '
            'chuyen ve lien he goc. Lien he bi gop se duoc archive.'
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
        partners = (self.source_partner_ids | self.destination_partner_id).exists()
        if len(partners) < 2:
            raise UserError(_('Can chon it nhat 2 lien he de gop.'))
        if self.destination_partner_id not in partners:
            raise UserError(_('Lien he giu lai phai nam trong danh sach can gop.'))

        destination = self.destination_partner_id.sudo()
        sources = (partners - destination).sudo()
        source_descendants = self.env['res.partner'].sudo().with_context(active_test=False).search([
            ('id', 'child_of', sources.ids),
        ])

        copied_fields = self._copy_missing_partner_fields(destination, sources)

        moved_children = sources.mapped('child_ids')
        if moved_children:
            moved_children.write({'parent_id': destination.id})

        sale_count = self._move_sale_orders(destination, source_descendants)
        purchase_count = self._move_purchase_orders(destination, source_descendants)

        sources.write({'active': False})
        refresh_partners = destination | destination.child_ids | sources
        refresh_partners._compute_hlv_order_flags()
        refresh_partners._compute_hlv_business_role()
        refresh_partners._compute_hlv_relationship_label()
        refresh_partners._compute_hlv_code_flags()
        refresh_partners._compute_hlv_misa_code_key()
        refresh_partners._compute_hlv_filter_tag_ids()

        destination.message_post(body=_(
            'Da gop lien he %s vao lien he nay. Bo sung field trong: %s. '
            'Chuyen %s don ban, %s don mua, %s lien he con.'
        ) % (
            ', '.join('%s:%s' % (p.id, p.display_name) for p in sources),
            ', '.join(copied_fields) or '-',
            sale_count,
            purchase_count,
            len(moved_children),
        ))
        return {'type': 'ir.actions.act_window_close'}

    def _copy_missing_partner_fields(self, destination, sources):
        fields_to_copy = [
            'vat', 'ref', 'company_registry',
            'phone', 'mobile', 'email', 'website',
            'street', 'street2', 'city', 'zip',
            'state_id', 'country_id', 'function', 'comment',
        ]
        vals = {}
        copied = []
        for field_name in fields_to_copy:
            if field_name not in destination._fields or destination[field_name]:
                continue
            source = sources.filtered(lambda p: bool(p[field_name]))[:1]
            if not source:
                continue
            field = destination._fields[field_name]
            vals[field_name] = source[field_name].id if field.type == 'many2one' else source[field_name]
            copied.append(field_name)

        if 'category_id' in destination._fields:
            category_ids = (destination.category_id | sources.mapped('category_id')).ids
            if category_ids:
                vals['category_id'] = [(6, 0, category_ids)]
                copied.append('category_id')

        if vals:
            destination.write(vals)
        return copied

    def _move_sale_orders(self, destination, source_partners):
        SaleOrder = self.env['sale.order'].sudo()
        partner_ids = source_partners.ids
        if not partner_ids:
            return 0

        orders = SaleOrder.search([('partner_id', 'in', partner_ids)])
        if orders:
            orders.write({'partner_id': destination.id})

        for field_name in ('partner_invoice_id', 'partner_shipping_id'):
            if field_name in SaleOrder._fields:
                field_orders = SaleOrder.search([(field_name, 'in', partner_ids)])
                if field_orders:
                    field_orders.write({field_name: destination.id})
                    orders |= field_orders
        return len(orders)

    def _move_purchase_orders(self, destination, source_partners):
        PurchaseOrder = self.env['purchase.order'].sudo()
        partner_ids = source_partners.ids
        if not partner_ids:
            return 0
        orders = PurchaseOrder.search([('partner_id', 'in', partner_ids)])
        if orders:
            orders.write({'partner_id': destination.id})
        return len(orders)
