# -*- coding: utf-8 -*-
"""
wizard/shopee_product_create_wizard.py

Wizard tạo sản phẩm mới trên Shopee từ sản phẩm Odoo (product.template).

Luồng:
1. Mở wizard (từ Actions trên product.template)
2. Chọn cửa hàng Shopee — các thông tin cơ bản được tự động điền
3. Wizard tự gọi Shopee API lấy danh sách kênh vận chuyển → người dùng tick chọn
4. Nhấn "Tạo sản phẩm Shopee" → upload ảnh + add_item → tạo shopee.product
"""
import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeeProductCreateWizard(models.TransientModel):
    _name = 'shopee.product.create.wizard'
    _description = 'Tạo sản phẩm Shopee từ Odoo'

    # ── Nguồn & đích ──────────────────────────────────────────────────────
    product_template_id = fields.Many2one(
        'product.template',
        string='Sản phẩm Odoo',
        required=True,
        ondelete='cascade',
    )
    shop_id = fields.Many2one(
        'shopee.shop',
        string='Cửa hàng Shopee',
        required=True,
    )

    # ── Thông tin cơ bản ──────────────────────────────────────────────────
    item_name = fields.Char(string='Tên sản phẩm Shopee', required=True, size=300)
    item_sku = fields.Char(string='SKU', size=100)
    description = fields.Text(string='Mô tả sản phẩm')

    # ── Giá & tồn kho ─────────────────────────────────────────────────────
    original_price = fields.Float(
        string='Giá gốc (VNĐ)', digits=(16, 0), required=True,
    )
    initial_stock = fields.Integer(string='Tồn kho ban đầu', default=0)
    weight = fields.Float(
        string='Cân nặng (kg)',
        digits=(10, 3),
        default=0.1,
        help='Cân nặng tính bằng kg. Shopee yêu cầu tối thiểu 0.001 kg.',
    )

    # ── Shopee-specific ────────────────────────────────────────────────────
    shopee_category_id = fields.Many2one(
        'shopee.category', string='Danh mục Shopee',
        domain="[('shop_id','=',shop_id),('has_children','=',False)]",
        help='Chọn danh mục từ cây danh mục Shopee đã đồng bộ. '
             'Dùng nút "↻ Tải danh mục" nếu danh sách trống.',
    )
    category_id = fields.Integer(
        string='Category ID Shopee',
        compute='_compute_category_id', store=True, readonly=False,
        help='ID danh mục Shopee. Tự động điền khi chọn từ danh sách phía trên.',
    )
    category_suggestion = fields.Text(
        string='Gợi ý danh mục', readonly=True,
        help='Bấm "Gợi ý danh mục" để Shopee đề xuất dựa trên tên sản phẩm.',
    )
    shopee_brand_id = fields.Many2one(
        'shopee.brand', string='Thương hiệu Shopee',
        domain="[('shop_id','=',shop_id),('category_id','=',category_id)]",
        help='Danh sách thương hiệu được lấy từ Shopee theo danh mục.',
    )
    brand_id = fields.Integer(
        string='Brand ID Shopee', compute='_compute_brand_fields', store=True, readonly=False,
    )
    brand_name = fields.Char(
        string='Tên brand', compute='_compute_brand_fields', store=True, readonly=False,
    )
    attribute_line_ids = fields.One2many(
        'shopee.product.create.wizard.attribute',
        'wizard_id',
        string='Thuộc tính Shopee',
    )

    logistic_line_ids = fields.One2many(
        'shopee.product.create.wizard.logistic',
        'wizard_id',
        string='Kênh vận chuyển',
    )

    # ── Ảnh ───────────────────────────────────────────────────────────────
    upload_product_image = fields.Boolean(
        string='Upload ảnh từ sản phẩm Odoo',
        default=True,
        help='Tự động upload ảnh đại diện sản phẩm Odoo lên Shopee Media Space.',
    )

    # ── Kết quả (sau khi tạo) ─────────────────────────────────────────────
    result_item_id = fields.Char(string='Shopee Item ID', readonly=True)
    result_shopee_product_id = fields.Many2one(
        'shopee.product',
        string='Sản phẩm Shopee đã tạo',
        readonly=True,
    )

    # ──────────────────────────────────────────────────────────────────────

    @api.onchange('product_template_id')
    def _onchange_product_template(self):
        if not self.product_template_id:
            return
        tmpl = self.product_template_id
        self.item_name = tmpl.name or ''
        self.item_sku = tmpl.default_code or ''
        self.description = (
            (tmpl.description_sale or tmpl.description or '').strip()
        )
        self.original_price = tmpl.list_price or 0
        self.weight = max(tmpl.weight or 0.0, 0.001)
        product = tmpl.product_variant_ids[:1]
        if product:
            self.initial_stock = int(product.qty_available or 0)

    @api.onchange('shop_id')
    def _onchange_shop_load_logistics(self):
        """Khi chọn shop, tự động gọi Shopee API lấy danh sách kênh vận chuyển."""
        self.logistic_line_ids = [(5, 0, 0)]
        if not self.shop_id:
            return
        try:
            from odoo.addons.shopee_order_fetch.services.shopee_api import (
                get_credentials_from_shop,
            )
            creds = get_credentials_from_shop(self.shop_id)
            channels = shopee_product_api.call_get_logistics_channels(creds)
        except Exception as e:
            _logger.warning("Shopee wizard: không lấy được logistics: %s", e)
            return {
                'warning': {
                    'title': _('Không tải được kênh vận chuyển'),
                    'message': str(e),
                }
            }

        lines = []
        for ch in channels:
            if not ch.get('enabled', True):
                continue
            channel_id = (
                ch.get('logistics_channel_id')
                or ch.get('logistic_id')
                or ch.get('channel_id')
                or ch.get('id')
            )
            channel_name = (
                ch.get('logistics_channel_name')
                or ch.get('logistic_name')
                or ch.get('channel_name')
                or ch.get('name')
                or ''
            )
            if not channel_id:
                _logger.warning('Shopee logistics channel không có ID: %s', ch)
                continue
            lines.append((0, 0, {
                'channel_id': int(channel_id),
                'channel_name': channel_name,
                'cod_enabled': ch.get('cod_enabled', False),
                'selected': False,
            }))
        self.logistic_line_ids = lines

    def action_reload_logistics(self):
        """Nút thủ công để reload danh sách kênh vận chuyển."""
        self.ensure_one()
        self._onchange_shop_load_logistics()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('shopee_category_id')
    def _compute_category_id(self):
        for rec in self:
            if rec.shopee_category_id:
                rec.category_id = rec.shopee_category_id.category_id
            elif not rec.category_id:
                rec.category_id = 0

    @api.depends('shopee_brand_id')
    def _compute_brand_fields(self):
        for rec in self:
            if rec.shopee_brand_id:
                rec.brand_id = rec.shopee_brand_id.brand_id
                rec.brand_name = rec.shopee_brand_id.brand_name
            else:
                rec.brand_id = 0
                rec.brand_name = 'No Brand'

    @api.onchange('shopee_category_id')
    def _onchange_category_load_brand_attributes(self):
        self.shopee_brand_id = False
        self.attribute_line_ids = [(5, 0, 0)]
        if not self.shop_id or not self.category_id:
            return
        self._load_brand_attribute_lines()

    def _load_brand_attribute_lines(self):
        self.ensure_one()
        Brand = self.env['shopee.brand']
        Attribute = self.env['shopee.attribute']
        try:
            if not Brand.search_count([('shop_id', '=', self.shop_id.id), ('category_id', '=', self.category_id)]):
                Brand._sync_from_shopee(self.shop_id, self.category_id)
            if not Attribute.search_count([('shop_id', '=', self.shop_id.id), ('category_id', '=', self.category_id)]):
                Attribute._sync_from_shopee(self.shop_id, self.category_id)
        except Exception as e:
            _logger.warning('Shopee wizard: không tải được brand/attribute: %s', e)
            return {
                'warning': {
                    'title': _('Không tải được thương hiệu/thuộc tính'),
                    'message': str(e),
                }
            }

        no_brand = Brand.search([
            ('shop_id', '=', self.shop_id.id),
            ('category_id', '=', self.category_id),
            ('brand_id', '=', 0),
        ], limit=1)
        self.shopee_brand_id = no_brand or Brand.search([
            ('shop_id', '=', self.shop_id.id),
            ('category_id', '=', self.category_id),
        ], limit=1)
        attrs = Attribute.search([
            ('shop_id', '=', self.shop_id.id),
            ('category_id', '=', self.category_id),
        ])
        self.attribute_line_ids = [(0, 0, {
            'shopee_attribute_id': attr.id,
            'is_mandatory': attr.is_mandatory,
            'input_type': attr.input_type,
        }) for attr in attrs]

    def action_sync_categories(self):
        """Đồng bộ cây danh mục Shopee cho shop hiện tại."""
        self.ensure_one()
        if not self.shop_id:
            raise UserError(_('Vui lòng chọn cửa hàng trước.'))
        count = self.env['shopee.category']._sync_from_shopee(self.shop_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ danh mục Shopee'),
                'message': _('Đã đồng bộ %d danh mục.') % count,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reload_brand_attributes(self):
        self.ensure_one()
        if not self.shop_id or not self.category_id:
            raise UserError(_('Vui lòng chọn shop và danh mục trước.'))
        self.env['shopee.brand']._sync_from_shopee(self.shop_id, self.category_id)
        self.env['shopee.attribute']._sync_from_shopee(self.shop_id, self.category_id)
        self._load_brand_attribute_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_suggest_category(self):
        """Gọi Shopee category_recommend dựa trên tên sản phẩm."""
        self.ensure_one()
        if not self.item_name:
            raise UserError(_('Cần nhập tên sản phẩm trước khi gợi ý danh mục.'))
        if not self.shop_id:
            raise UserError(_('Vui lòng chọn cửa hàng trước.'))
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)
        result = shopee_product_api.call_category_recommend(creds, self.item_name)
        cat_ids = result if isinstance(result, list) else (
            result.get('category_id') or []
        )
        if not cat_ids:
            self.category_suggestion = _('Không có gợi ý danh mục cho tên này.')
            return
        Cat = self.env['shopee.category']
        if not Cat.search_count([('shop_id', '=', self.shop_id.id)]):
            try:
                Cat._sync_from_shopee(self.shop_id)
            except Exception as e:
                _logger.warning('Sync danh mục thất bại khi gợi ý: %s', e)
        lines = [_('Danh mục Shopee gợi ý:')]
        first_match = False
        for cid in cat_ids[:8]:
            cat_rec = Cat.search([
                ('shop_id', '=', self.shop_id.id),
                ('category_id', '=', cid),
                ('has_children', '=', False),
            ], limit=1)
            name = cat_rec.full_path if cat_rec else '?'
            lines.append('  • [%s] %s' % (cid, name))
            if cat_rec and not first_match:
                first_match = cat_rec
        if first_match:
            self.shopee_category_id = first_match
            self._load_brand_attribute_lines()
        self.category_suggestion = '\n'.join(lines)

    def action_create_shopee_product(self):
        self.ensure_one()

        if not self.category_id:
            raise UserError(_(
                'Vui lòng chọn Danh mục Shopee.\n'
                'Nếu danh sách rỗng, bấm "↻ Tải danh mục" hoặc "Gợi ý danh mục".'
            ))
        if self.shopee_category_id and self.shopee_category_id.has_children:
            raise UserError(_(
                'Danh mục "%s" vẫn còn danh mục con.\n'
                'Shopee yêu cầu chọn danh mục lá (leaf category).'
            ) % self.shopee_category_id.full_path)

        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)

        # 1. Validate logistics ─────────────────────────────────────────
        selected_lines = self.logistic_line_ids.filtered(lambda l: l.selected)
        if not selected_lines:
            raise UserError(_(
                'Vui lòng tick chọn ít nhất một kênh vận chuyển.'
            ))
        logistic_info = []
        for l in selected_lines:
            entry = {'logistic_id': int(l.channel_id), 'enabled': True}
            if l.shipping_fee:
                entry['shipping_fee'] = float(l.shipping_fee)
            logistic_info.append(entry)

        attribute_list = []
        missing_required = []
        for line in self.attribute_line_ids:
            values = line._to_shopee_values()
            if line.is_mandatory and not values:
                missing_required.append(line.attribute_name)
            if values:
                attribute_list.append({
                    'attribute_id': int(line.attribute_id),
                    'attribute_value_list': values,
                })
        if missing_required:
            raise UserError(_('Vui lòng chọn/nhập thuộc tính bắt buộc:\n%s') % '\n'.join(missing_required))

        # 2. Upload ảnh ──────────────────────────────────────────────────
        image_id_list = []
        if self.upload_product_image and self.product_template_id.image_1920:
            try:
                image_binary = base64.b64decode(self.product_template_id.image_1920)
                image_id = shopee_product_api.call_upload_image(creds, image_binary)
                if image_id:
                    image_id_list.append(image_id)
            except UserError:
                raise
            except Exception as e:
                raise UserError(_('Lỗi upload ảnh lên Shopee: %s') % str(e))

        if not image_id_list:
            raise UserError(_(
                'Không có ảnh để upload hoặc upload ảnh thất bại.\n'
                'Vui lòng thêm ảnh đại diện cho sản phẩm Odoo trước khi tạo trên Shopee.'
            ))

        # 3. Build payload ───────────────────────────────────────────────
        seller_stock = [{'stock': int(self.initial_stock or 0)}]
        item_data = {
            'item_name': self.item_name,
            'description': self.description or self.item_name,
            'item_sku': self.item_sku or '',
            'category_id': self.category_id,
            'brand': {
                'brand_id': int(self.brand_id or 0),
                'original_brand_name': self.brand_name or 'No Brand',
            },
            'original_price': self.original_price,
            'weight': self.weight,
            'image': {'image_id_list': image_id_list},
            # Shopee add_item dùng key 'logistic_info', không phải 'logistics'.
            'logistic_info': logistic_info,
            'attribute_list': attribute_list,
            # Shopee add_item ở một số region/sandbox vẫn validate seller_stock
            # trực tiếp, dù docs mới dùng stock_info_v2.
            'seller_stock': seller_stock,
            'stock_info_v2': {
                'seller_stock': seller_stock,
            },
        }

        # 4. Gọi add_item ────────────────────────────────────────────────
        _logger.info(
            'Shopee add_item payload: logistic_info=%s, attribute_count=%s, '
            'image_count=%s, brand=%s',
            logistic_info, len(attribute_list), len(image_id_list),
            item_data.get('brand'),
        )
        try:
            result = shopee_product_api.call_add_item(creds, item_data)
        except UserError:
            raise
        except Exception as e:
            raise UserError(_('Lỗi tạo sản phẩm Shopee: %s') % str(e))

        shopee_item_id = str(result.get('item_id', ''))
        if not shopee_item_id:
            raise UserError(_('Shopee không trả về item_id. Phản hồi: %s') % result)

        # 5. Tạo shopee.product record ───────────────────────────────────
        shopee_product = self.env['shopee.product'].create({
            'shop_id': self.shop_id.id,
            'shopee_item_id': shopee_item_id,
            'item_name': self.item_name,
            'item_sku': self.item_sku or '',
            'category_id': self.category_id,
            'original_price': self.original_price,
            'current_price': self.original_price,
            'total_available_stock': int(self.initial_stock or 0),
            'item_status': 'REVIEWING',
            'last_synced': fields.Datetime.now(),
        })

        self.write({
            'result_item_id': shopee_item_id,
            'result_shopee_product_id': shopee_product.id,
        })

        # 6. Mở sản phẩm vừa tạo ────────────────────────────────────────
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sản phẩm Shopee mới'),
            'res_model': 'shopee.product',
            'res_id': shopee_product.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ShopeeProductCreateWizardLogistic(models.TransientModel):
    _name = 'shopee.product.create.wizard.logistic'
    _description = 'Kênh vận chuyển trong wizard tạo sản phẩm Shopee'
    _order = 'channel_name'

    wizard_id = fields.Many2one(
        'shopee.product.create.wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Chọn', default=False)
    channel_id = fields.Integer(string='Channel ID', readonly=True)
    channel_name = fields.Char(string='Tên kênh', readonly=True)
    cod_enabled = fields.Boolean(string='Hỗ trợ COD', readonly=True)
    shipping_fee = fields.Float(string='Phí vận chuyển', digits=(16, 0), default=0)


class ShopeeProductCreateWizardAttribute(models.TransientModel):
    _name = 'shopee.product.create.wizard.attribute'
    _description = 'Thuộc tính trong wizard tạo sản phẩm Shopee'
    _order = 'is_mandatory desc, attribute_name'

    wizard_id = fields.Many2one(
        'shopee.product.create.wizard', required=True, ondelete='cascade',
    )
    shopee_attribute_id = fields.Many2one(
        'shopee.attribute', string='Thuộc tính', required=True, readonly=True,
    )
    attribute_id = fields.Integer(
        string='Attribute ID', related='shopee_attribute_id.attribute_id', readonly=True,
    )
    attribute_name = fields.Char(
        string='Tên thuộc tính', related='shopee_attribute_id.attribute_name', readonly=True,
    )
    is_mandatory = fields.Boolean(string='Bắt buộc', readonly=True)
    input_type = fields.Char(string='Kiểu nhập', readonly=True)
    value_id = fields.Many2one(
        'shopee.attribute.value', string='Giá trị',
        domain="[('attribute_id_ref','=',shopee_attribute_id)]",
    )
    value_text = fields.Char(string='Giá trị nhập tay')

    def _to_shopee_values(self):
        self.ensure_one()
        if self.value_id:
            value = {
                'value_id': int(self.value_id.value_id or 0),
                'original_value_name': self.value_id.value_name,
            }
            if self.value_id.value_unit:
                value['value_unit'] = self.value_id.value_unit
            return [value]
        if self.value_text:
            return [{'original_value_name': self.value_text.strip()}]
        return []
