import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeeProductModel(models.Model):
    """
    Lưu trữ danh sách biến thể (model) của sản phẩm Shopee.

    Mỗi bản ghi là một tier-combination (ví dụ: Xanh / Size M).
    Dữ liệu được đồng bộ qua nút "Tải biến thể" trên form sản phẩm.
    """

    _name = 'shopee.product.model'
    _description = 'Biến thể Sản phẩm Shopee'
    _order = 'shopee_product_id, shopee_model_id'
    _rec_name = 'display_name_computed'

    shopee_product_id = fields.Many2one(
        'shopee.product',
        string='Sản phẩm',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Shopee identifiers ──────────────────────────────────────────────────
    shopee_model_id = fields.Char('Model ID Shopee', index=True, readonly=True, size=64)
    model_sku = fields.Char('SKU biến thể')
    model_status = fields.Selection(
        [('MODEL_NORMAL', 'Đang bán'), ('MODEL_UNAVAILABLE', 'Không khả dụng')],
        string='Trạng thái',
        readonly=True,
    )

    # ── Tier variation metadata ─────────────────────────────────────────────
    tier_index = fields.Char(
        'Tier Index',
        help='Mảng JSON, VD: [0, 1] – vị trí option trong từng tier',
        readonly=True,
    )
    tier_label = fields.Char(
        'Phân loại',
        help='Nhãn hiển thị, VD: Xanh / Size M',
        readonly=True,
    )

    # ── Price info ──────────────────────────────────────────────────────────
    original_price = fields.Float('Giá gốc', digits=(16, 0), readonly=True)
    current_price = fields.Float('Giá hiện tại', digits=(16, 0), readonly=True)
    new_price = fields.Float(
        'Giá mới',
        digits=(16, 0),
        help='Nhập giá mới rồi nhấn "Đẩy giá lên Shopee"',
    )

    # ── Stock info ──────────────────────────────────────────────────────────
    available_stock = fields.Integer('Tồn kho hiện tại', readonly=True)
    new_stock = fields.Integer(
        'Tồn kho mới',
        help='Nhập tồn kho mới rồi nhấn "Đẩy tồn kho lên Shopee"',
    )

    last_synced = fields.Datetime('Đồng bộ lần cuối', readonly=True)

    # ── sale_shopee mapping ────────────────────────────────────────────────
    shopee_item_mapping_id = fields.Many2one(
        'shopee.item',
        string='Mapping shopee.item',
        compute='_compute_shopee_item_mapping',
        store=False,
        help='Mapping biến thể có sẵn từ sale_shopee theo item_id + model_id.',
    )
    mapped_product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm Odoo từ shopee.item',
        compute='_compute_shopee_item_mapping',
        store=False,
    )

    # ── Computed ────────────────────────────────────────────────────────────
    display_name_computed = fields.Char(
        compute='_compute_display_name_computed',
        store=False,
    )

    @api.depends('tier_label', 'model_sku', 'shopee_model_id')
    def _compute_display_name_computed(self):
        for rec in self:
            parts = [p for p in [rec.tier_label, rec.model_sku] if p]
            rec.display_name_computed = ' — '.join(parts) if parts else str(rec.shopee_model_id)

    @api.depends('shopee_product_id.shop_id', 'shopee_product_id.shopee_item_id', 'shopee_model_id')
    def _compute_shopee_item_mapping(self):
        ShopeeItem = self.env['shopee.item'].sudo()
        Product = self.env['product.product']
        for rec in self:
            mapping = ShopeeItem.browse()
            product = Product.browse()
            product_rec = rec.shopee_product_id
            if product_rec.shop_id and product_rec.shopee_item_id:
                mapping = ShopeeItem.search([
                    ('shop_id', '=', product_rec.shop_id.id),
                    ('shopee_item_identifier', '=', str(product_rec.shopee_item_id)),
                    ('shopee_model_identifier', '=', str(rec.shopee_model_id or '')),
                ], limit=1)
                product = mapping.product_id if mapping else product
            rec.shopee_item_mapping_id = mapping
            rec.mapped_product_id = product

    # ── Helper ──────────────────────────────────────────────────────────────
    @api.model
    def _tier_label_from_variation(self, tier_index_raw, tier_variation_list):
        """
        Dựng nhãn hiển thị từ tier_index (list int) và tier_variation_list.

        tier_variation_list là list tier trả về từ get_model_list:
          [{'name': 'Màu sắc', 'option_list': [{'name': 'Đỏ'}, {'name': 'Xanh'}]}, ...]
        """
        if not tier_index_raw or not tier_variation_list:
            return ''
        try:
            indices = (
                tier_index_raw
                if isinstance(tier_index_raw, list)
                else json.loads(tier_index_raw)
            )
        except Exception:
            return ''
        labels = []
        for tier_pos, opt_idx in enumerate(indices):
            if tier_pos >= len(tier_variation_list):
                break
            tier = tier_variation_list[tier_pos]
            options = tier.get('option_list', [])
            if opt_idx < len(options):
                opt = options[opt_idx]
                # API trả về 'name' hoặc 'variation_option_name'
                labels.append(opt.get('name') or opt.get('variation_option_name', ''))
        return ' / '.join(labels)

    # ── Shopee model CRUD ──────────────────────────────────────────────────
    def _shopee_creds(self):
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        self.ensure_one()
        if not self.shopee_product_id.shop_id:
            raise UserError(_('Sản phẩm Shopee chưa liên kết cửa hàng.'))
        return get_credentials_from_shop(self.shopee_product_id.shop_id)

    def action_push_model_update(self):
        """Đẩy thay đổi của biến thể này lên Shopee qua update_model.

        Cập nhật model_sku, original_price (nếu nhập new_price), seller_stock
        (nếu nhập new_stock).
        """
        self.ensure_one()
        if not self.shopee_model_id:
            raise UserError(_('Biến thể chưa có model_id trên Shopee.'))
        item_id = self.shopee_product_id.shopee_item_id
        if not item_id:
            raise UserError(_('Sản phẩm chưa có item_id trên Shopee.'))

        model_entry = {'model_id': int(self.shopee_model_id)}
        if self.model_sku:
            model_entry['model_sku'] = self.model_sku
        if self.new_price:
            model_entry['original_price'] = float(self.new_price)
        if self.new_stock:
            model_entry['seller_stock'] = [{'stock': int(self.new_stock)}]

        if len(model_entry) == 1:
            raise UserError(_('Không có thay đổi (SKU/Giá mới/Tồn kho mới) để đẩy.'))

        creds = self._shopee_creds()
        _logger.info('Shopee update_model item_id=%s payload=%s', item_id, model_entry)
        shopee_product_api.call_update_model(creds, int(item_id), [model_entry])

        vals = {'last_synced': fields.Datetime.now()}
        if self.new_price:
            vals.update({'original_price': self.new_price, 'current_price': self.new_price, 'new_price': 0})
        if self.new_stock:
            vals.update({'available_stock': self.new_stock, 'new_stock': 0})
        self.write(vals)
        return True

    def action_delete_model_from_shopee(self):
        """Xóa biến thể này khỏi Shopee qua delete_model rồi xóa bản ghi Odoo."""
        self.ensure_one()
        if not self.shopee_model_id:
            self.unlink()
            return True
        item_id = self.shopee_product_id.shopee_item_id
        if not item_id:
            raise UserError(_('Sản phẩm chưa có item_id trên Shopee.'))

        creds = self._shopee_creds()
        _logger.info('Shopee delete_model item_id=%s model_id=%s', item_id, self.shopee_model_id)
        shopee_product_api.call_delete_model(creds, int(item_id), [int(self.shopee_model_id)])
        self.unlink()
        return True
