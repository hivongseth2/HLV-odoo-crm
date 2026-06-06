# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def init(self):
        cr = self.env.cr
        cr.execute("""
            UPDATE res_partner
               SET hlv_partner_type = CASE
                   WHEN type = 'delivery' THEN 'delivery'
                   WHEN type = 'invoice' THEN 'invoice'
                   WHEN parent_id IS NOT NULL THEN 'child_contact'
                   WHEN is_company IS TRUE THEN 'root_company'
                   ELSE 'root_person'
               END
        """)
        cr.execute("""
            UPDATE res_partner
               SET hlv_misa_code_key = CASE
                   WHEN COALESCE(NULLIF(TRIM(vat), ''), '') != ''
                    AND COALESCE(NULLIF(TRIM(ref), ''), NULLIF(TRIM(company_registry), '')) IS NOT NULL
                   THEN TRIM(vat) || '-' || COALESCE(NULLIF(TRIM(ref), ''), NULLIF(TRIM(company_registry), ''))
                   ELSE COALESCE(NULLIF(TRIM(ref), ''), NULLIF(TRIM(company_registry), ''))
               END,
                   hlv_dirty_child_code = (
                       parent_id IS NOT NULL
                       AND (
                           COALESCE(NULLIF(TRIM(ref), ''), '') != ''
                           OR COALESCE(NULLIF(TRIM(company_registry), ''), '') != ''
                       )
                   ),
                   hlv_root_code_mismatch = (
                       parent_id IS NULL
                       AND COALESCE(NULLIF(TRIM(ref), ''), '') != ''
                       AND COALESCE(NULLIF(TRIM(company_registry), ''), '') != ''
                       AND TRIM(ref) != TRIM(company_registry)
                   )
        """)
        cr.execute("UPDATE res_partner SET hlv_has_sale_order = customer_rank > 0")
        cr.execute("UPDATE res_partner SET hlv_has_purchase_order = supplier_rank > 0")
        cr.execute("UPDATE res_partner SET hlv_has_shopee_order = FALSE")
        cr.execute("""
            UPDATE res_partner
               SET hlv_has_sale_order = TRUE
             WHERE id IN (
                   SELECT DISTINCT COALESCE(cp.id, so.partner_id)
                     FROM sale_order so
                     JOIN res_partner p ON p.id = so.partner_id
                LEFT JOIN res_partner cp ON cp.id = p.commercial_partner_id
             )
        """)
        cr.execute("""
            UPDATE res_partner
               SET hlv_has_purchase_order = TRUE
             WHERE id IN (
                   SELECT DISTINCT COALESCE(cp.id, po.partner_id)
                     FROM purchase_order po
                     JOIN res_partner p ON p.id = po.partner_id
                LEFT JOIN res_partner cp ON cp.id = p.commercial_partner_id
             )
        """)
        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'sale_order'
                   AND column_name = 'shopee_order_ref'
            )
        """)
        has_shopee_ref = cr.fetchone()[0]
        if has_shopee_ref:
            cr.execute("""
                UPDATE res_partner
                   SET hlv_has_shopee_order = TRUE,
                       hlv_has_sale_order = TRUE
                 WHERE id IN (
                       SELECT DISTINCT COALESCE(cp.id, so.partner_id)
                         FROM sale_order so
                         JOIN res_partner p ON p.id = so.partner_id
                    LEFT JOIN res_partner cp ON cp.id = p.commercial_partner_id
                        WHERE so.shopee_order_ref IS NOT NULL
                          AND so.shopee_order_ref != ''
                 )
            """)
        cr.execute("""
            UPDATE res_partner
               SET hlv_business_role = CASE
                   WHEN hlv_has_shopee_order IS TRUE THEN 'customer_shopee'
                   WHEN hlv_has_sale_order IS TRUE THEN 'customer_crm'
                   WHEN hlv_has_purchase_order IS TRUE THEN 'vendor'
                   ELSE 'other'
               END
        """)

    child_contact_count = fields.Integer(
        compute='_compute_child_contact_count',
        string="Số liên hệ con",
    )
    hlv_partner_type = fields.Selection([
        # Legacy values from 18.0.1.0.0. Keep them valid so stored rows do not
        # break search panel before the classification refresh rewrites them.
        ('company', 'Công ty'),
        ('person', 'Cá nhân'),
        ('root_company', 'Công ty gốc'),
        ('root_person', 'Cá nhân gốc'),
        ('child_contact', 'Liên hệ con'),
        ('delivery', 'Địa chỉ giao hàng'),
        ('invoice', 'Địa chỉ hóa đơn'),
    ], compute='_compute_hlv_partner_type', string="Loại liên hệ", store=True)
    hlv_filter_tag_ids = fields.Many2many(
        'hlv.contact.filter.tag',
        compute='_compute_hlv_filter_tag_ids',
        string="Phân loại",
        store=True,
    )
    hlv_business_role = fields.Selection([
        ('customer_crm', 'Khách CRM'),
        ('customer_shopee', 'Khách Shopee'),
        ('vendor', 'Nhà cung cấp'),
        ('other', 'Khác'),
    ], compute='_compute_hlv_business_role', string="Vai trò", store=True)
    hlv_has_sale_order = fields.Boolean(
        compute='_compute_hlv_order_flags',
        string="Có đơn bán",
        store=True,
    )
    hlv_has_shopee_order = fields.Boolean(
        compute='_compute_hlv_order_flags',
        string="Có đơn Shopee",
        store=True,
    )
    hlv_has_purchase_order = fields.Boolean(
        compute='_compute_hlv_order_flags',
        string="Có đơn mua",
        store=True,
    )
    hlv_misa_code_key = fields.Char(
        compute='_compute_hlv_misa_code_key',
        string="Khóa MST-Mã khách",
        store=True,
    )
    hlv_dirty_child_code = fields.Boolean(
        compute='_compute_hlv_code_flags',
        string="Mã nằm trên liên hệ con",
        store=True,
    )
    hlv_root_code_mismatch = fields.Boolean(
        compute='_compute_hlv_code_flags',
        string="Root lệch ref/company_registry",
        store=True,
    )

    @api.depends('is_company', 'parent_id', 'type')
    def _compute_hlv_partner_type(self):
        for partner in self:
            if partner.type == 'delivery':
                partner.hlv_partner_type = 'delivery'
            elif partner.type == 'invoice':
                partner.hlv_partner_type = 'invoice'
            elif partner.parent_id:
                partner.hlv_partner_type = 'child_contact'
            elif partner.is_company:
                partner.hlv_partner_type = 'root_company'
            else:
                partner.hlv_partner_type = 'root_person'

    @api.depends('child_ids')
    def _compute_child_contact_count(self):
        for partner in self:
            partner.child_contact_count = len(partner.child_ids)

    def _hlv_sale_order_shopee_domain(self, partner):
        SaleOrder = self.env['sale.order'].sudo()
        if 'shopee_order_ref' not in SaleOrder._fields:
            return False
        return [
            ('partner_id', 'child_of', partner.id),
            ('shopee_order_ref', '!=', False),
        ]

    @api.depends('customer_rank', 'supplier_rank')
    def _compute_hlv_order_flags(self):
        SaleOrder = self.env['sale.order'].sudo()
        PurchaseOrder = self.env['purchase.order'].sudo()
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        partners = self.filtered('id')
        partner_ids = set(partners.ids)
        sale_partner_ids = set()
        shopee_partner_ids = set()
        purchase_partner_ids = set()

        if partners:
            descendants = Partner.search([('id', 'child_of', partners.ids)])
            descendant_to_roots = {}
            for descendant in descendants:
                current = descendant
                roots = []
                while current:
                    if current.id in partner_ids:
                        roots.append(current.id)
                    current = current.parent_id
                if roots:
                    descendant_to_roots[descendant.id] = roots

            sale_groups = SaleOrder.read_group(
                [('partner_id', 'in', descendants.ids)],
                ['partner_id'],
                ['partner_id'],
            )
            for group in sale_groups:
                direct_id = group.get('partner_id') and group['partner_id'][0]
                for root_id in descendant_to_roots.get(direct_id, []):
                    sale_partner_ids.add(root_id)

            shopee_domain = False
            if 'shopee_order_ref' in SaleOrder._fields:
                shopee_domain = [
                    ('partner_id', 'in', descendants.ids),
                    ('shopee_order_ref', '!=', False),
                ]
            if shopee_domain:
                shopee_groups = SaleOrder.read_group(shopee_domain, ['partner_id'], ['partner_id'])
                for group in shopee_groups:
                    direct_id = group.get('partner_id') and group['partner_id'][0]
                    for root_id in descendant_to_roots.get(direct_id, []):
                        shopee_partner_ids.add(root_id)

            purchase_groups = PurchaseOrder.read_group(
                [('partner_id', 'in', descendants.ids)],
                ['partner_id'],
                ['partner_id'],
            )
            for group in purchase_groups:
                direct_id = group.get('partner_id') and group['partner_id'][0]
                for root_id in descendant_to_roots.get(direct_id, []):
                    purchase_partner_ids.add(root_id)

        for partner in self:
            if not partner.id:
                partner.hlv_has_sale_order = False
                partner.hlv_has_shopee_order = False
                partner.hlv_has_purchase_order = False
                continue

            partner.hlv_has_sale_order = bool(
                partner.customer_rank > 0 or partner.id in sale_partner_ids
            )
            partner.hlv_has_shopee_order = partner.id in shopee_partner_ids
            partner.hlv_has_purchase_order = bool(
                partner.supplier_rank > 0 or partner.id in purchase_partner_ids
            )

    @api.depends('vat', 'ref', 'company_registry')
    def _compute_hlv_misa_code_key(self):
        for partner in self:
            code = (partner.ref or partner.company_registry or '').strip()
            tax_code = (partner.vat or '').strip()
            partner.hlv_misa_code_key = '%s-%s' % (tax_code, code) if tax_code and code else code or False

    @api.depends('hlv_has_sale_order', 'hlv_has_shopee_order', 'hlv_has_purchase_order')
    def _compute_hlv_business_role(self):
        for partner in self:
            if partner.hlv_has_shopee_order:
                partner.hlv_business_role = 'customer_shopee'
            elif partner.hlv_has_sale_order:
                partner.hlv_business_role = 'customer_crm'
            elif partner.hlv_has_purchase_order:
                partner.hlv_business_role = 'vendor'
            else:
                partner.hlv_business_role = 'other'

    @api.depends('parent_id', 'ref', 'company_registry')
    def _compute_hlv_code_flags(self):
        for partner in self:
            ref = (partner.ref or '').strip()
            company_registry = (partner.company_registry or '').strip()
            partner.hlv_dirty_child_code = bool(partner.parent_id and (ref or company_registry))
            partner.hlv_root_code_mismatch = bool(
                not partner.parent_id and ref and company_registry and ref != company_registry
            )

    @api.depends(
        'customer_rank', 'supplier_rank', 'parent_id', 'type', 'is_company',
        'ref', 'company_registry', 'vat', 'hlv_has_sale_order',
        'hlv_has_shopee_order', 'hlv_has_purchase_order',
        'hlv_dirty_child_code', 'hlv_root_code_mismatch', 'hlv_business_role',
    )
    def _compute_hlv_filter_tag_ids(self):
        tags = {
            rec.code: rec
            for rec in self.env['hlv.contact.filter.tag'].sudo().search([])
        }

        for partner in self:
            tag_ids = []

            def add(code):
                tag = tags.get(code)
                if tag:
                    tag_ids.append(tag.id)

            if not partner.parent_id:
                add('root')
                add('company' if partner.is_company else 'person')
            else:
                add('child')

            if partner.type == 'delivery':
                add('delivery')
            elif partner.type == 'invoice':
                add('invoice')

            if partner.hlv_has_shopee_order:
                add('customer_shopee')
            elif partner.hlv_has_sale_order:
                add('customer')

            if partner.hlv_has_purchase_order:
                add('vendor')

            if (partner.ref or partner.company_registry) and not partner.parent_id:
                add('misa_code')

            partner._compute_hlv_code_flags()
            if partner.hlv_dirty_child_code:
                add('dirty_child_code')

            if partner.hlv_root_code_mismatch:
                add('root_code_mismatch')

            partner.hlv_filter_tag_ids = [(6, 0, tag_ids)]

    def action_hlv_refresh_contact_classification(self):
        partners = self
        if not partners:
            partners = self.env['res.partner'].sudo().with_context(active_test=False).search([])
        partners._compute_hlv_partner_type()
        partners._compute_hlv_order_flags()
        partners._compute_hlv_business_role()
        partners._compute_hlv_code_flags()
        partners._compute_hlv_misa_code_key()
        partners._compute_hlv_filter_tag_ids()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã cập nhật phân loại'),
                'message': _('Đã quét lại %s liên hệ.') % len(partners),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_hlv_open_merge_wizard(self):
        destination = self.filtered(lambda p: p.is_company and not p.parent_id)[:1] or self[:1]
        return {
            'name': _('Gộp liên hệ'),
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contact.merge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_partner_ids': [(6, 0, self.ids)],
                'default_destination_partner_id': destination.id,
            },
        }

    def action_hlv_open_split_wizard(self):
        self.ensure_one()
        return {
            'name': _('Tách thành khách hàng mới'),
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contact.split.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_partner_id': self.id,
                'default_new_name': self.name,
                'default_new_vat': self.vat,
            },
        }
