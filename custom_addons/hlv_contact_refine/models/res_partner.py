# -*- coding: utf-8 -*-
import json
import base64
import time
import unicodedata
import uuid

import requests

from odoo import api, fields, models, _


MISA_CRM_ACCOUNT_GRID_URL = "https://amisapp.misa.vn/crm/g2/api/business/Account/Grid"
MISA_CRM_FETCH_ATTEMPTS = 3
MISA_CRM_COLUMNS = (
    "SUQsVGFnSUQsVGFnSURUZXh0LEFjY291bnROdW1iZXIsQWNjb3VudFR5cGVJRCxBY2NvdW50"
    "VHlwZUlEVGV4dCxBY2NvdW50TmFtZSxUYXhDb2RlLE9mZmljZVRlbCxPZmZpY2VFbWFpbCxTZWN0"
    "b3JJRCxTZWN0b3JJRFRleHQsQmlsbGluZ0FkZHJlc3MsQmlsbGluZ1Byb3ZpbmNlSUQsQmls"
    "bGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElE"
    "VGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlc2NyaXB0aW9uLE93bmVy"
    "SUQsT3duZXJJRFRleHQsTGVhZFNvdXJjZUlELExlYWRTb3VyY2VJRFRleHQsRm9ybUxheW91"
    "dElELEZvcm1MYXlvdXRJRFRleHQsQXZhdGFyLEluYWN0aXZlLElzQ29ycA=="
)


def _norm_text(value):
    value = unicodedata.normalize("NFC", (value or "").strip().upper())
    return " ".join(value.split())


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def init(self):
        cr = self.env.cr

        def column_exists(table, column):
            cr.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                     WHERE table_name = %s
                       AND column_name = %s
                )
            """, (table, column))
            return cr.fetchone()[0]

        if column_exists('res_partner', 'hlv_partner_type'):
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

        if column_exists('res_partner', 'hlv_misa_code_key'):
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

        if column_exists('res_partner', 'hlv_has_sale_order'):
            cr.execute("UPDATE res_partner SET hlv_has_sale_order = customer_rank > 0")
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

        if column_exists('res_partner', 'hlv_has_purchase_order'):
            cr.execute("UPDATE res_partner SET hlv_has_purchase_order = supplier_rank > 0")
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

        if column_exists('res_partner', 'hlv_has_shopee_order'):
            cr.execute("UPDATE res_partner SET hlv_has_shopee_order = FALSE")
            if column_exists('sale_order', 'shopee_order_ref'):
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

        if column_exists('res_partner', 'hlv_business_role'):
            cr.execute("""
                UPDATE res_partner
                   SET hlv_business_role = CASE
                       WHEN type = 'delivery' THEN 'delivery_address'
                       WHEN type = 'invoice' THEN 'invoice_address'
                       WHEN parent_id IS NOT NULL THEN 'child_contact'
                       WHEN hlv_has_shopee_order IS TRUE THEN 'customer_shopee'
                       WHEN hlv_has_sale_order IS TRUE THEN 'customer_crm'
                       WHEN hlv_has_purchase_order IS TRUE THEN 'supplier'
                       ELSE 'other'
                   END
            """)

        if column_exists('res_partner', 'hlv_relationship_label'):
            cr.execute("""
                UPDATE res_partner
                   SET hlv_relationship_label = CASE
                       WHEN type = 'delivery' THEN 'Giao hàng'
                       WHEN type = 'invoice' THEN 'Hóa đơn'
                       WHEN parent_id IS NOT NULL THEN 'Liên hệ con'
                       ELSE 'Hồ sơ gốc'
                   END
            """)
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
        ('vendor', 'Nhà cung cấp (cũ)'),
        ('customer_crm', 'Khách CRM'),
        ('customer_shopee', 'Khách Shopee'),
        ('supplier', 'Nhà cung cấp'),
        ('delivery_address', 'Địa chỉ giao hàng'),
        ('invoice_address', 'Địa chỉ hóa đơn'),
        ('child_contact', 'Liên hệ con'),
        ('other', 'Khác'),
    ], compute='_compute_hlv_business_role', string="Nghiệp vụ", store=True)
    hlv_relationship_label = fields.Char(
        compute='_compute_hlv_relationship_label',
        string="Quan hệ",
        store=True,
    )
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

    @api.depends('parent_id', 'type', 'hlv_has_sale_order', 'hlv_has_shopee_order', 'hlv_has_purchase_order')
    def _compute_hlv_business_role(self):
        for partner in self:
            if partner.type == 'delivery':
                partner.hlv_business_role = 'delivery_address'
            elif partner.type == 'invoice':
                partner.hlv_business_role = 'invoice_address'
            elif partner.parent_id:
                partner.hlv_business_role = 'child_contact'
            elif partner.hlv_has_shopee_order:
                partner.hlv_business_role = 'customer_shopee'
            elif partner.hlv_has_sale_order:
                partner.hlv_business_role = 'customer_crm'
            elif partner.hlv_has_purchase_order:
                partner.hlv_business_role = 'supplier'
            else:
                partner.hlv_business_role = 'other'

    @api.depends('parent_id', 'type')
    def _compute_hlv_relationship_label(self):
        for partner in self:
            if partner.type == 'delivery':
                partner.hlv_relationship_label = 'Giao hàng'
            elif partner.type == 'invoice':
                partner.hlv_relationship_label = 'Hóa đơn'
            elif partner.parent_id:
                partner.hlv_relationship_label = 'Liên hệ con'
            else:
                partner.hlv_relationship_label = 'Hồ sơ gốc'

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

            if not partner.parent_id and partner.hlv_has_shopee_order:
                add('customer_shopee')
            elif not partner.parent_id and partner.hlv_has_sale_order:
                add('customer')

            if not partner.parent_id and partner.hlv_has_purchase_order:
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
        partners._compute_hlv_relationship_label()
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
        view = self.env.ref('hlv_contact_refine.view_hlv_contact_merge_wizard_form', raise_if_not_found=False)
        return {
            'name': _('Gộp liên hệ'),
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contact.merge.wizard',
            'view_mode': 'form',
            'views': [(view.id if view else False, 'form')],
            'target': 'new',
            'context': {
                'default_source_partner_ids': [(6, 0, self.ids)],
                'default_destination_partner_id': destination.id,
            },
        }

    def action_hlv_open_split_wizard(self):
        self.ensure_one()
        view = self.env.ref('hlv_contact_refine.view_hlv_contact_split_wizard_form', raise_if_not_found=False)
        return {
            'name': _('Tách thành khách hàng mới'),
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contact.split.wizard',
            'view_mode': 'form',
            'views': [(view.id if view else False, 'form')],
            'target': 'new',
            'context': {
                'default_source_partner_id': self.id,
                'default_new_name': self.name,
                'default_new_vat': self.vat,
            },
        }

    @api.model
    def hlv_contact_explorer_data(self, search_text=False, role='customer_crm', limit=80, offset=0):
        domain = [('parent_id', '=', False), ('active', '=', True)]
        if role == 'dirty':
            domain.append(('id', 'in', self._hlv_explorer_dirty_root_ids()))
        elif role and role != 'all':
            domain.append(('hlv_business_role', '=', role))
        if search_text:
            domain += ['|', '|', '|',
                       ('name', 'ilike', search_text),
                       ('ref', 'ilike', search_text),
                       ('vat', 'ilike', search_text),
                       ('phone', 'ilike', search_text)]

        total = self.sudo().search_count(domain)
        partners = self.sudo().search(domain, order='name asc, id asc', limit=limit, offset=offset)
        rows = [partner._hlv_explorer_row() for partner in partners]
        selected = rows[0] if rows else False
        related = self.browse(selected['id'])._hlv_explorer_related_rows() if selected else []
        return {
            'rows': rows,
            'selected': selected,
            'related': related,
            'roles': self._hlv_explorer_role_counts(),
            'total': total,
            'offset': offset,
            'limit': limit,
        }

    @api.model
    def hlv_contact_explorer_select(self, partner_id):
        partner = self.sudo().browse(partner_id).exists()
        if not partner:
            return {'selected': False, 'related': []}
        root = partner.commercial_partner_id or partner
        return {
            'selected': root._hlv_explorer_row(),
            'related': root._hlv_explorer_related_rows(),
        }

    @api.model
    def hlv_contact_explorer_compare_crm(self, partner_id):
        partner = self.sudo().browse(partner_id).exists()
        if not partner:
            return {'ok': False, 'message': _('Khong tim thay lien he.'), 'accounts': []}

        root = partner.commercial_partner_id or partner
        try:
            keywords = []
            for value in (root.name, root.ref, root.company_registry, root.vat):
                value = (value or '').strip()
                if value and value not in keywords:
                    keywords.append(value)
            accounts = []
            seen_account_ids = set()
            for keyword in keywords:
                for account in self._hlv_fetch_misa_crm_accounts(keyword):
                    account_key = account.get('ID') or '%s-%s' % (
                        account.get('AccountNumber'), account.get('TaxCode')
                    )
                    if account_key in seen_account_ids:
                        continue
                    seen_account_ids.add(account_key)
                    accounts.append(account)
        except Exception as exc:
            return {'ok': False, 'message': str(exc), 'accounts': []}

        root_ref = (root.ref or '').strip()
        root_registry = (root.company_registry or '').strip()
        root_codes = set(code for code in (root_ref, root_registry) if code)
        root_vat = (root.vat or '').strip()
        exact = []
        account_rows = []
        same_name_count = 0

        for account in accounts:
            if _norm_text(account.get('AccountName')) == _norm_text(root.name):
                same_name_count += 1
            code = (account.get('AccountNumber') or '').strip()
            tax_code = (account.get('TaxCode') or '').strip()
            matched_code = bool(code and code in root_codes)
            matched_tax = bool(tax_code and root_vat and tax_code == root_vat)
            is_exact = bool(matched_code and (matched_tax or not root_vat or not tax_code))
            if is_exact:
                exact.append(account)
            account_rows.append({
                'id': account.get('ID'),
                'code': code,
                'name': account.get('AccountName') or '',
                'tax': tax_code,
                'phone': account.get('OfficeTel') or '',
                'email': account.get('OfficeEmail') or '',
                'address': account.get('BillingAddress') or '',
                'matched_code': matched_code,
                'matched_tax': matched_tax,
                'exact': is_exact,
            })

        if exact:
            message = _('CRM khop %s account theo ma KH/MST.') % len(exact)
            ok = True
        elif account_rows and same_name_count:
            message = _('CRM co account cung ten nhung chua khop key MST + ma KH.')
            ok = False
        elif account_rows:
            message = _('CRM co tra du lieu nhung khong co AccountName khop chinh xac.')
            ok = False
        else:
            message = _('CRM khong tra ve account nao cung ten.')
            ok = False

        return {
            'ok': ok,
            'message': message,
            'partner': root._hlv_explorer_row(),
            'accounts': account_rows,
        }

    @api.model
    def _hlv_misa_crm_headers(self):
        misa_config = self.env['misa.config'].sudo()
        crm_token = self._hlv_get_cached_misa_crm_token()
        if not crm_token:
            raise Exception(_('Khong lay duoc token MISA CRM.'))

        headers = dict(misa_config.get_crm_header(crm_token))
        # Let requests calculate this; the fixed value in get_crm_header is
        # only safe for the original captured payload.
        headers.pop('content-length', None)
        headers.pop('Content-Length', None)
        headers.update({
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'layoutcode': 'account',
            'x-misa-language': 'vi-VN',
        })
        return headers

    @api.model
    def _hlv_get_cached_misa_crm_token(self, force_refresh=False):
        ICP = self.env['ir.config_parameter'].sudo()
        now = int(time.time())
        if not force_refresh:
            token = (ICP.get_param('hlv_contact_refine.misa_crm_token') or '').strip()
            exp = int(ICP.get_param('hlv_contact_refine.misa_crm_token_exp') or 0)
            if token and exp > now + 300:
                return token

        token = self.env['misa.api.utils'].sudo()._fetch_login_crm_token()
        exp = self._hlv_decode_jwt_exp(token) or (now + 3600)
        ICP.set_param('hlv_contact_refine.misa_crm_token', token)
        ICP.set_param('hlv_contact_refine.misa_crm_token_exp', str(exp))
        return token

    @api.model
    def _hlv_decode_jwt_exp(self, token):
        try:
            payload_b64 = (token or '').split('.')[1]
            payload_b64 += '=' * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode('ascii')))
            return int(payload.get('exp') or 0)
        except Exception:
            return 0

    @api.model
    def _hlv_misa_crm_payload(self, keyword, page=1, page_size=20):
        return {
            'Columns': MISA_CRM_COLUMNS,
            'Sorts': [{'SortBy': 'ModifiedDate', 'Type': 0, 'SortDirection': 1}],
            'Start': (page - 1) * page_size,
            'Page': page,
            'PageSize': page_size,
            'Filters': [],
            'Formula': '',
            'LayoutCode': 'Account',
            'DefaultTotal': True,
            'IsMappingData': False,
            'MappingValueObject': {},
            'IsApproved': False,
            'CustomPagingData': {},
            'IsUsedELTS': True,
            'ListGmailPage': [],
            'ListFacebookPage': {},
            'IsListPaging': True,
            'IsGetCache': False,
            'IsCheckInactive': False,
            'IsConverted': False,
            'SessionID': str(uuid.uuid4()),
            'LayoutCodeCheckPermission': 'Account',
            'AISearchKeyword': keyword or '',
            'SkipNormalSearch': False,
        }

    @api.model
    def _hlv_fetch_misa_crm_accounts(self, keyword):
        expected_name = _norm_text(keyword)
        last_raw = []
        for attempt in range(MISA_CRM_FETCH_ATTEMPTS):
            response = requests.post(
                MISA_CRM_ACCOUNT_GRID_URL,
                headers=self._hlv_misa_crm_headers(),
                data=json.dumps(
                    self._hlv_misa_crm_payload(keyword),
                    ensure_ascii=False,
                ).encode('utf-8'),
                timeout=30,
            )
            if response.status_code in (401, 403) and attempt == 0:
                self._hlv_get_cached_misa_crm_token(force_refresh=True)
                continue
            response.raise_for_status()
            data = response.json()
            if data.get('Code') != 200 or data.get('Success') is not True:
                raise Exception(_('MISA CRM loi: %s') % data.get('SubCode'))

            raw_accounts = data.get('Data') or []
            last_raw = raw_accounts
            matched = [
                account for account in raw_accounts
                if _norm_text(account.get('AccountName')) == expected_name
            ]
            if matched:
                return matched
            time.sleep(0.6)
        return last_raw

    @api.model
    def hlv_contact_explorer_apply_crm_account(self, partner_id, account):
        partner = self.sudo().browse(partner_id).exists()
        if not partner:
            return {'ok': False, 'message': _('Khong tim thay lien he.')}
        if not isinstance(account, dict):
            return {'ok': False, 'message': _('Du lieu CRM khong hop le.')}

        root = partner.commercial_partner_id or partner
        code = (account.get('code') or account.get('AccountNumber') or '').strip()
        tax_code = (account.get('tax') or account.get('TaxCode') or '').strip()
        vals = {}

        if code:
            vals['ref'] = code
            vals['company_registry'] = code
        if tax_code:
            vals['vat'] = tax_code

        field_map = [
            ('phone', 'phone'),
            ('OfficeTel', 'phone'),
            ('email', 'email'),
            ('OfficeEmail', 'email'),
            ('address', 'street'),
            ('BillingAddress', 'street'),
            ('BillingProvinceIDText', 'city'),
        ]
        for source_field, target_field in field_map:
            value = (account.get(source_field) or '').strip()
            if value and (root[target_field] or '') != value:
                vals[target_field] = value

        if not vals:
            return {
                'ok': True,
                'message': _('Khong co field can cap nhat.'),
                'selected': root._hlv_explorer_row(),
                'related': root._hlv_explorer_related_rows(),
            }

        root.write(vals)
        root.message_post(body=_(
            'Da gan thong tin tu MISA CRM account %s. Fields: %s'
        ) % (code or account.get('id') or account.get('ID'), ', '.join(sorted(vals))))
        (root | root.child_ids)._compute_hlv_code_flags()
        (root | root.child_ids)._compute_hlv_misa_code_key()
        (root | root.child_ids)._compute_hlv_filter_tag_ids()
        return {
            'ok': True,
            'message': _('Da gan ma/MST tu CRM vao lien he dang chon.'),
            'selected': root._hlv_explorer_row(),
            'related': root._hlv_explorer_related_rows(),
        }

    @api.model
    def _hlv_explorer_role_counts(self):
        labels = {
            'all': _('Tất cả'),
            'customer_crm': _('Khách CRM'),
            'customer_shopee': _('Khách Shopee'),
            'supplier': _('Nhà cung cấp'),
            'other': _('Khác'),
        }
        result = [{'key': 'all', 'label': labels['all'], 'count': self.sudo().search_count([
            ('parent_id', '=', False),
            ('active', '=', True),
        ])}]
        for key in ('customer_crm', 'customer_shopee', 'supplier'):
            result.append({
                'key': key,
                'label': labels[key],
                'count': self.sudo().search_count([
                    ('parent_id', '=', False),
                    ('active', '=', True),
                    ('hlv_business_role', '=', key),
                ]),
            })
        result.append({
            'key': 'dirty',
            'label': _('Cần kiểm tra'),
            'count': len(self._hlv_explorer_dirty_root_ids()),
        })
        result.append({
            'key': 'other',
            'label': _('Khác'),
            'count': self.sudo().search_count([
                ('parent_id', '=', False),
                ('active', '=', True),
                ('hlv_business_role', '=', 'other'),
            ]),
        })
        return result

    @api.model
    def _hlv_explorer_dirty_root_ids(self):
        self.env.cr.execute("""
            SELECT DISTINCT root.id
              FROM res_partner root
         LEFT JOIN res_partner child ON child.parent_id = root.id
             WHERE root.parent_id IS NULL
               AND root.active IS TRUE
               AND (
                   (
                       COALESCE(NULLIF(TRIM(root.ref), ''), '') != ''
                       AND COALESCE(NULLIF(TRIM(root.company_registry), ''), '') != ''
                       AND TRIM(root.ref) != TRIM(root.company_registry)
                   )
                   OR (
                       child.id IS NOT NULL
                       AND child.active IS TRUE
                       AND (
                           COALESCE(NULLIF(TRIM(child.ref), ''), '') != ''
                           OR COALESCE(NULLIF(TRIM(child.company_registry), ''), '') != ''
                       )
                   )
               )
        """)
        return [row[0] for row in self.env.cr.fetchall()]

    def _hlv_explorer_row(self):
        self.ensure_one()
        dirty = self._hlv_explorer_is_dirty()
        return {
            'id': self.id,
            'name': self.display_name or self.name or '',
            'role': dict(self._fields['hlv_business_role'].selection).get(self.hlv_business_role, self.hlv_business_role or ''),
            'role_key': self.hlv_business_role or '',
            'relationship': self.hlv_relationship_label or '',
            'relationship_key': self._hlv_explorer_relationship_key(),
            'ref': self.ref or '',
            'company_registry': self.company_registry or '',
            'code_hint': self._hlv_explorer_code_hint(),
            'vat': self.vat or '',
            'phone': self.phone or self.mobile or '',
            'email': self.email or '',
            'city': self.city or '',
            'child_count': self.child_contact_count,
            'has_shopee': bool(self.hlv_has_shopee_order),
            'dirty': dirty,
            'dirty_reason': self._hlv_explorer_dirty_reason() if dirty else '',
        }

    def _hlv_explorer_relationship_key(self):
        self.ensure_one()
        if self.type == 'delivery':
            return 'delivery'
        if self.type == 'invoice':
            return 'invoice'
        if self.parent_id:
            return 'child'
        return 'root'

    def _hlv_explorer_dirty_reason(self):
        self.ensure_one()
        reasons = []
        ref = (self.ref or '').strip()
        company_registry = (self.company_registry or '').strip()
        if self.parent_id and (ref or company_registry):
            reasons.append(_('mã MISA đang nằm trên liên hệ con/địa chỉ'))
        if not self.parent_id and ref and company_registry and ref != company_registry:
            reasons.append(_('ref và company_registry đang lệch nhau'))
        return ', '.join(reasons)

    def _hlv_explorer_is_dirty(self):
        self.ensure_one()
        ref = (self.ref or '').strip()
        company_registry = (self.company_registry or '').strip()
        return bool(
            (self.parent_id and (ref or company_registry))
            or (not self.parent_id and ref and company_registry and ref != company_registry)
        )

    def _hlv_explorer_code_hint(self):
        self.ensure_one()
        parts = []
        if self.ref:
            parts.append('ref=%s' % self.ref)
        if self.company_registry:
            parts.append('registry=%s' % self.company_registry)
        return ', '.join(parts)

    def _hlv_explorer_related_rows(self):
        self.ensure_one()
        related = self | self.child_ids
        related = related.sorted(lambda p: (0 if p.id == self.id else 1, p.type or '', p.name or ''))
        return [partner._hlv_explorer_row() for partner in related]

    def action_hlv_open_contact_explorer(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'hlv_contact_explorer_action',
            'name': _('Liên hệ tinh gọn'),
        }

    @api.model
    def hlv_contact_explorer_fix_data(self, partner_id):
        partner = self.sudo().browse(partner_id).exists()
        if not partner:
            return {'selected': False, 'related': []}

        root = partner.commercial_partner_id or partner
        fixed = []

        if partner.parent_id and (partner.ref or partner.company_registry):
            partner.write({'ref': False, 'company_registry': False})
            fixed.append(partner.id)
        elif not partner.parent_id:
            dirty_children = partner.child_ids.filtered(lambda p: p.ref or p.company_registry)
            if dirty_children:
                dirty_children.write({'ref': False, 'company_registry': False})
                fixed.extend(dirty_children.ids)

            ref = (partner.ref or '').strip()
            company_registry = (partner.company_registry or '').strip()
            if ref and company_registry and ref != company_registry:
                partner.write({'company_registry': ref})
                fixed.append(partner.id)

        (root | root.child_ids)._compute_hlv_code_flags()
        (root | root.child_ids)._compute_hlv_filter_tag_ids()
        return {
            'fixed_ids': fixed,
            'selected': root._hlv_explorer_row(),
            'related': root._hlv_explorer_related_rows(),
        }

    @api.model
    def hlv_contact_explorer_fix_many(self, partner_ids):
        partners = self.sudo().browse(partner_ids or []).exists()
        fixed_ids = set()
        for partner in partners:
            root = partner.commercial_partner_id or partner
            if partner.parent_id and (partner.ref or partner.company_registry):
                partner.write({'ref': False, 'company_registry': False})
                fixed_ids.add(partner.id)
                continue

            dirty_children = root.child_ids.filtered(lambda p: p.ref or p.company_registry)
            if dirty_children:
                dirty_children.write({'ref': False, 'company_registry': False})
                fixed_ids.update(dirty_children.ids)

            ref = (root.ref or '').strip()
            company_registry = (root.company_registry or '').strip()
            if ref and company_registry and ref != company_registry:
                root.write({'company_registry': ref})
                fixed_ids.add(root.id)

            (root | root.child_ids)._compute_hlv_code_flags()
            (root | root.child_ids)._compute_hlv_filter_tag_ids()

        return {'fixed_ids': sorted(fixed_ids)}

    @api.model
    def hlv_contact_explorer_merge_action(self, destination_id, source_ids):
        destination = self.sudo().browse(destination_id).exists()
        sources = self.sudo().browse(source_ids or []).exists()
        if not destination or not sources:
            return False
        partner_ids = (destination | sources).ids
        view = self.env.ref('hlv_contact_refine.view_hlv_contact_merge_wizard_form', raise_if_not_found=False)
        return {
            'name': _('Gop lien he'),
            'type': 'ir.actions.act_window',
            'res_model': 'hlv.contact.merge.wizard',
            'view_mode': 'form',
            'views': [(view.id if view else False, 'form')],
            'target': 'new',
            'context': {
                'active_ids': partner_ids,
                'default_source_partner_ids': [(6, 0, partner_ids)],
                'default_destination_partner_id': destination.id,
            },
        }
