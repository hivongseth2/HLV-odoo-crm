# -*- coding: utf-8 -*-
"""
models/shopee_product.py

Model lưu trữ cache sản phẩm đã đồng bộ từ Shopee.

Mỗi record = 1 item trên 1 shop Shopee.
Dùng để theo dõi, quản lý và đẩy sản phẩm từ Odoo lên Shopee.
"""
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)

ITEM_STATUS_SELECTION = [
    ('NORMAL', 'Đang bán'),
    ('BANNED', 'Bị cấm'),
    ('UNLIST', 'Ẩn'),
    ('REVIEWING', 'Đang duyệt'),
    ('SELLER_DELETE', 'Xóa bởi Seller'),
    ('SHOPEE_DELETE', 'Xóa bởi Shopee'),
]


class ShopeeProduct(models.Model):
    """Cache sản phẩm Shopee — đồng bộ qua get_item_list + get_item_base_info."""

    _name = 'shopee.product'
    _description = 'Sản phẩm Shopee'
    _order = 'shopee_update_time desc, id desc'
    _rec_name = 'item_name'

    # ── Shopee identifiers ──────────────────────────────
    shop_id = fields.Many2one(
        'shopee.shop',
        string='Cửa hàng Shopee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    shopee_item_id = fields.Integer(
        string='Item ID Shopee',
        required=True,
        index=True,
        help='Mã định danh duy nhất của sản phẩm trên Shopee (item_id).',
    )

    # ── Thông tin cơ bản ────────────────────────────────
    item_name = fields.Char(string='Tên sản phẩm', index=True)
    item_sku = fields.Char(string='SKU', index=True)
    category_id = fields.Integer(string='Category ID Shopee')
    item_status = fields.Selection(
        ITEM_STATUS_SELECTION,
        string='Trạng thái',
        index=True,
    )

    # ── Giá ─────────────────────────────────────────────
    original_price = fields.Float(string='Giá gốc', digits=(16, 0))
    current_price = fields.Float(string='Giá hiện tại', digits=(16, 0))

    # ── Tồn kho ─────────────────────────────────────────
    total_available_stock = fields.Integer(string='Tồn kho khả dụng')
    has_model = fields.Boolean(
        string='Có biến thể',
        help='True nếu sản phẩm có nhiều phân loại (model/variation).',
    )

    # ── Thời gian ───────────────────────────────────────
    shopee_update_time = fields.Datetime(
        string='Cập nhật trên Shopee',
        help='update_time trả về từ Shopee API.',
    )
    last_synced = fields.Datetime(
        string='Đồng bộ lần cuối',
        readonly=True,
    )

    # ── Liên kết Odoo ───────────────────────────────────
    odoo_product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm Odoo thủ công',
        ondelete='set null',
        index=True,
        help='Liên kết thủ công cũ. Ưu tiên mapping từ shopee.item nếu có.',
    )
    shopee_item_mapping_ids = fields.Many2many(
        'shopee.item',
        string='Mapping shopee.item',
        compute='_compute_shopee_item_mapping',
        store=False,
        help='Mapping có sẵn từ sale_shopee/shopee_order_fetch theo shop + Shopee item_id.',
    )
    shopee_item_mapping_count = fields.Integer(
        string='Số mapping',
        compute='_compute_shopee_item_mapping',
        store=False,
    )
    mapped_product_ids = fields.Many2many(
        'product.product',
        string='Sản phẩm Odoo từ shopee.item',
        compute='_compute_shopee_item_mapping',
        store=False,
        help='Các product.product đang được shopee.item trỏ tới.',
    )
    mapped_product_count = fields.Integer(
        string='Số sản phẩm Odoo',
        compute='_compute_shopee_item_mapping',
        store=False,
    )

    # ── Dữ liệu thô ─────────────────────────────────────
    raw_data = fields.Json(
        string='Dữ liệu thô từ Shopee',
        readonly=True,
        help='Toàn bộ JSON trả về từ get_item_base_info để tra cứu chi tiết.',
    )

    # ── Biến thể (models) ────────────────────────────────
    model_ids = fields.One2many(
        'shopee.product.model',
        'shopee_product_id',
        string='Biến thể',
    )
    model_count = fields.Integer(
        string='Số biến thể',
        compute='_compute_model_count',
        store=True,
    )

    @api.depends('model_ids')
    def _compute_model_count(self):
        for rec in self:
            rec.model_count = len(rec.model_ids)

    _sql_constraints = [
        (
            'unique_shop_item',
            'UNIQUE(shop_id, shopee_item_id)',
            'Mỗi sản phẩm Shopee chỉ được lưu một lần trên mỗi cửa hàng.',
        )
    ]

    # ── Computed ────────────────────────────────────────
    shopee_item_url = fields.Char(
        string='Link Shopee',
        compute='_compute_shopee_item_url',
        store=False,
    )

    @api.depends('shopee_item_id')
    def _compute_shopee_item_url(self):
        for rec in self:
            if rec.shopee_item_id:
                rec.shopee_item_url = (
                    f"https://shopee.vn/product/{rec.shopee_item_id}"
                )
            else:
                rec.shopee_item_url = False

    @api.depends('shop_id', 'shopee_item_id')
    def _compute_shopee_item_mapping(self):
        ShopeeItem = self.env['shopee.item'].sudo()
        Product = self.env['product.product'].sudo()
        for rec in self:
            mappings = ShopeeItem.browse()
            if rec.shop_id and rec.shopee_item_id:
                mappings = rec._find_shopee_item_mappings()
            products = mappings.mapped('product_id') if mappings else Product.browse()
            rec.shopee_item_mapping_ids = mappings
            rec.shopee_item_mapping_count = len(mappings)
            rec.mapped_product_ids = products
            rec.mapped_product_count = len(products)

    def _find_shopee_item_mappings(self, model_id=None):
        """Find sale_shopee mapping rows for this Shopee item/model."""
        self.ensure_one()
        if not self.shop_id or not self.shopee_item_id:
            return self.env['shopee.item'].browse()

        domain = [
            ('shop_id', '=', self.shop_id.id),
            ('shopee_item_identifier', '=', str(self.shopee_item_id)),
        ]
        if model_id is not None:
            model_value = str(model_id or '')
            domain.append(('shopee_model_identifier', '=', model_value))
        return self.env['shopee.item'].sudo().search(domain)

    # ── Actions ─────────────────────────────────────────

    def action_open_shopee_item(self):
        """Open the Shopee product page in a new browser tab."""
        self.ensure_one()
        if not self.shopee_item_url:
            raise UserError(_('Không có link Shopee cho sản phẩm này.'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.shopee_item_url,
            'target': 'new',
        }

    def action_open_shopee_item_mappings(self):
        """Open shopee.item mappings already maintained by sale_shopee."""
        self.ensure_one()
        if not self.shopee_item_mapping_ids:
            raise UserError(_('Chưa có mapping shopee.item cho sản phẩm này.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mapping shopee.item'),
            'res_model': 'shopee.item',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.shopee_item_mapping_ids.ids)],
            'target': 'current',
        }

    def action_open_mapped_products(self):
        """Open product.product records linked through shopee.item."""
        self.ensure_one()
        if not self.mapped_product_ids:
            raise UserError(_('Chưa có sản phẩm Odoo nào được mapping qua shopee.item.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sản phẩm Odoo đã mapping'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.mapped_product_ids.ids)],
            'target': 'current',
        }

    def action_refresh_from_shopee(self):
        """Cập nhật lại thông tin sản phẩm này từ Shopee API."""
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)
        items = shopee_product_api.call_get_item_base_info(creds, [self.shopee_item_id])
        if not items:
            raise UserError(_("Không tìm thấy thông tin sản phẩm ID %d trên Shopee.") % self.shopee_item_id)
        _update_record_from_api(self, items[0])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Đã cập nhật"),
                'message': _("Đã đồng bộ lại sản phẩm '%s' từ Shopee.") % self.item_name,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_sync_wizard(self):
        """Mở wizard đồng bộ hàng loạt."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đồng bộ sản phẩm Shopee'),
            'res_model': 'shopee.product.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_load_models(self):
        """Tải danh sách biến thể (model) từ Shopee và lưu vào model_ids."""
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)
        model_list, tier_variation_list = shopee_product_api.call_get_model_list(
            creds, self.shopee_item_id
        )

        ShopeeModel = self.env['shopee.product.model']
        now = fields.Datetime.now()

        existing = {r.shopee_model_id: r for r in self.model_ids}
        for m in model_list:
            mid = m.get('model_id', 0)
            tier_index_raw = m.get('tier_index', [])
            tier_label = ShopeeModel._tier_label_from_variation(
                tier_index_raw, tier_variation_list
            )
            price_info = (m.get('price_info') or [{}])[0]
            stock_v2 = m.get('stock_info_v2', {})
            avail = stock_v2.get('summary_info', {}).get('total_available_stock', 0)

            vals = {
                'shopee_model_id': mid,
                'model_sku': m.get('model_sku', ''),
                'model_status': m.get('model_status', 'MODEL_NORMAL'),
                'tier_index': str(tier_index_raw) if tier_index_raw else '',
                'tier_label': tier_label,
                'original_price': price_info.get('original_price', 0.0),
                'current_price': price_info.get('current_price', 0.0),
                'new_price': price_info.get('original_price', 0.0),
                'available_stock': avail,
                'new_stock': avail,
                'last_synced': now,
            }
            if mid in existing:
                existing[mid].write(vals)
            else:
                ShopeeModel.create({'shopee_product_id': self.id, **vals})

        # Xóa các model không còn trên Shopee
        shopee_model_ids = {m.get('model_id', 0) for m in model_list}
        orphans = self.model_ids.filtered(
            lambda r: r.shopee_model_id not in shopee_model_ids
        )
        if orphans:
            orphans.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã tải biến thể'),
                'message': _('Tải %d biến thể thành công.') % len(model_list),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_push_price(self):
        """
        Đẩy giá mới (field new_price trên model lines) lên Shopee.
        Với sản phẩm không có biến thể: dùng original_price của record này.
        """
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)

        if self.has_model and self.model_ids:
            price_list = [
                {'model_id': m.shopee_model_id, 'original_price': m.new_price}
                for m in self.model_ids
                if m.new_price > 0
            ]
        else:
            price_list = [{'model_id': 0, 'original_price': self.original_price}]

        if not price_list:
            raise UserError(_('Không có giá hợp lệ để cập nhật.'))

        success, failure = shopee_product_api.call_update_price(
            creds, self.shopee_item_id, price_list
        )

        if failure:
            msgs = ', '.join(
                f"Model {f.get('model_id')}: {f.get('failed_reason')}" for f in failure
            )
            raise UserError(_('Một số giá cập nhật thất bại: %s') % msgs)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cập nhật giá thành công'),
                'message': _('Đã cập nhật giá %d model.') % len(success),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_push_stock(self):
        """
        Đẩy tồn kho mới (field new_stock trên model lines) lên Shopee.
        Với sản phẩm không có biến thể: không có model_ids, dùng wizard.
        """
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)

        if self.has_model and self.model_ids:
            stock_list = [
                {
                    'model_id': m.shopee_model_id,
                    'seller_stock': [{'stock': m.new_stock}],
                }
                for m in self.model_ids
            ]
        else:
            return self._action_open_no_model_stock_wizard()

        success, failure = shopee_product_api.call_update_stock(
            creds, self.shopee_item_id, stock_list
        )

        if failure:
            msgs = ', '.join(
                f"Model {f.get('model_id')}: {f.get('failed_reason')}" for f in failure
            )
            raise UserError(_('Một số tồn kho cập nhật thất bại: %s') % msgs)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cập nhật tồn kho thành công'),
                'message': _('Đã cập nhật tồn kho %d model.') % len(success),
                'type': 'success',
                'sticky': False,
            },
        }

    def _action_open_no_model_stock_wizard(self):
        """Mở wizard nhập tồn kho cho sản phẩm không có biến thể."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cập nhật tồn kho Shopee'),
            'res_model': 'shopee.push.stock.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_shopee_product_id': self.id},
        }

    def action_delete_from_shopee(self):
        """Xóa sản phẩm này khỏi Shopee (soft delete — trạng thái SELLER_DELETE)."""
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)
        shopee_product_api.call_delete_item(creds, [self.shopee_item_id])
        self.write({'item_status': 'SELLER_DELETE'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã xóa khỏi Shopee'),
                'message': _('Sản phẩm \'%s\' đã bị xóa khỏi Shopee.') % self.item_name,
                'type': 'warning',
                'sticky': False,
            },
        }

    # ── Classmethod helpers ─────────────────────────────

    @api.model
    def sync_from_shop(self, shop, item_status=None, update_time_from=None,
                       update_time_to=None):
        """
        Kéo toàn bộ sản phẩm của `shop` từ Shopee và upsert vào DB.

        :param shop: shopee.shop record
        :param item_status: list str, mặc định ['NORMAL']
        :param update_time_from: timestamp int (filter theo thời gian)
        :param update_time_to: timestamp int
        :return: (created_count, updated_count)
        """
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(shop)

        if not item_status:
            item_status = ['NORMAL']

        # 1. Lấy danh sách item_id
        _logger.info("ShopeeProduct.sync_from_shop: shop=%s statuses=%s", shop.display_name, item_status)
        all_items = shopee_product_api.call_get_item_list_all(
            creds,
            item_status=item_status,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )
        if not all_items:
            _logger.info("ShopeeProduct.sync_from_shop: không có sản phẩm nào.")
            return 0, 0

        item_ids = [i['item_id'] for i in all_items]
        _logger.info("ShopeeProduct.sync_from_shop: %d items cần sync", len(item_ids))

        # 2. Lấy base info theo batch 50
        base_info_list = shopee_product_api.call_get_item_base_info_batch(creds, item_ids)

        # 3. Upsert vào DB
        created = updated = 0
        existing = {
            r.shopee_item_id: r
            for r in self.sudo().search([('shop_id', '=', shop.id)])
        }

        for item_data in base_info_list:
            sid = item_data.get('item_id')
            if not sid:
                continue
            rec = existing.get(sid)
            if rec:
                _update_record_from_api(rec, item_data)
                updated += 1
            else:
                vals = _build_vals_from_api(item_data, shop.id)
                self.sudo().create(vals)
                created += 1

        _logger.info(
            "ShopeeProduct.sync_from_shop: tạo mới=%d cập nhật=%d", created, updated
        )
        return created, updated


# ── Private helpers ──────────────────────────────────────

def _extract_price(item_data):
    """Lấy original_price và current_price từ price_info list."""
    price_info = item_data.get('price_info', [])
    if price_info:
        first = price_info[0]
        return first.get('original_price', 0.0), first.get('current_price', 0.0)
    return 0.0, 0.0


def _extract_stock(item_data):
    """Lấy total_available_stock từ stock_info_v2."""
    stock_v2 = item_data.get('stock_info_v2', {})
    summary = stock_v2.get('summary_info', {})
    return summary.get('total_available_stock', 0)


def _build_vals_from_api(item_data, shop_id):
    """Tạo dict vals để create() một shopee.product record."""
    orig_price, curr_price = _extract_price(item_data)
    update_ts = item_data.get('update_time')
    shopee_update_time = (
        datetime.fromtimestamp(update_ts) if update_ts else False
    )
    return {
        'shop_id': shop_id,
        'shopee_item_id': item_data['item_id'],
        'item_name': item_data.get('item_name', ''),
        'item_sku': item_data.get('item_sku', ''),
        'category_id': item_data.get('category_id', 0),
        'item_status': item_data.get('item_status'),
        'original_price': orig_price,
        'current_price': curr_price,
        'total_available_stock': _extract_stock(item_data),
        'has_model': item_data.get('has_model', False),
        'shopee_update_time': shopee_update_time,
        'last_synced': fields.Datetime.now(),
        'raw_data': item_data,
    }


def _update_record_from_api(rec, item_data):
    """Cập nhật record hiện có từ API response."""
    orig_price, curr_price = _extract_price(item_data)
    update_ts = item_data.get('update_time')
    shopee_update_time = (
        datetime.fromtimestamp(update_ts) if update_ts else False
    )
    rec.write({
        'item_name': item_data.get('item_name', rec.item_name),
        'item_sku': item_data.get('item_sku', rec.item_sku),
        'category_id': item_data.get('category_id', rec.category_id),
        'item_status': item_data.get('item_status', rec.item_status),
        'original_price': orig_price,
        'current_price': curr_price,
        'total_available_stock': _extract_stock(item_data),
        'has_model': item_data.get('has_model', rec.has_model),
        'shopee_update_time': shopee_update_time,
        'last_synced': fields.Datetime.now(),
        'raw_data': item_data,
    })
