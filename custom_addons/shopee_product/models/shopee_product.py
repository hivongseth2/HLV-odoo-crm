# -*- coding: utf-8 -*-
"""
models/shopee_product.py

Model lưu trữ cache sản phẩm đã đồng bộ từ Shopee.

Mỗi record = 1 item trên 1 shop Shopee.
Dùng để theo dõi, quản lý và đẩy sản phẩm từ Odoo lên Shopee.
"""
import json as _json
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
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    shopee_item_id = fields.Char(
        string='Item ID Shopee',
        required=True,
        index=True,
        size=64,
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
        items = shopee_product_api.call_get_item_base_info(creds, [int(self.shopee_item_id)])
        if not items:
            raise UserError(_("Không tìm thấy thông tin sản phẩm ID %s trên Shopee.") % self.shopee_item_id)
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
            creds, int(self.shopee_item_id)
        )

        ShopeeModel = self.env['shopee.product.model']
        now = fields.Datetime.now()

        existing = {r.shopee_model_id: r for r in self.model_ids}
        for m in model_list:
            mid = str(m.get('model_id') or '0')
            tier_index_raw = m.get('tier_index', [])
            tier_label = ShopeeModel._tier_label_from_variation(
                tier_index_raw, tier_variation_list
            )
            price_list = m.get('price_info') if isinstance(m.get('price_info'), list) else []
            price_info = price_list[0] if price_list and isinstance(price_list[0], dict) else {}
            stock_v2 = m.get('stock_info_v2') if isinstance(m.get('stock_info_v2'), dict) else {}
            summary = stock_v2.get('summary_info') if isinstance(stock_v2.get('summary_info'), dict) else {}
            avail = summary.get('total_available_stock', 0)

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
        if not model_list and self.shopee_item_mapping_ids:
            self._sync_models_from_shopee_item_mappings(self.shopee_item_mapping_ids, now)

        shopee_model_ids = {str(m.get('model_id') or '0') for m in model_list}
        orphans = self.model_ids.filtered(
            lambda r: model_list and r.shopee_model_id not in shopee_model_ids
        )
        if orphans:
            orphans.unlink()

        loaded_count = self.env['shopee.product.model'].sudo().search_count([
            ('shopee_product_id', '=', self.id),
        ])

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã tải biến thể'),
                'message': _('Tải %d biến thể thành công.') % loaded_count,
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
                {'model_id': int(m.shopee_model_id), 'original_price': m.new_price}
                for m in self.model_ids
                if m.shopee_model_id and m.new_price > 0
            ]
        else:
            price_list = [{'model_id': 0, 'original_price': self.original_price}]

        if not price_list:
            raise UserError(_('Không có giá hợp lệ để cập nhật.'))

        success, failure = shopee_product_api.call_update_price(
            creds, int(self.shopee_item_id), price_list
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
                    'model_id': int(m.shopee_model_id),
                    'seller_stock': [{'stock': m.new_stock}],
                }
                for m in self.model_ids
                if m.shopee_model_id
            ]
        else:
            return self._action_open_no_model_stock_wizard()

        success, failure = shopee_product_api.call_update_stock(
            creds, int(self.shopee_item_id), stock_list
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
        shopee_product_api.call_delete_item(creds, [int(self.shopee_item_id)])
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

    def _get_shopee_credentials(self):
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        return get_credentials_from_shop(self.shop_id)

    def _store_raw_section(self, section, value, title, message=None):
        self.ensure_one()
        raw_data = self.raw_data if isinstance(self.raw_data, dict) else {}
        raw_data = dict(raw_data)
        now = fields.Datetime.now()
        raw_data[section] = value
        raw_data['last_api_section'] = section
        raw_data['last_api_synced_at'] = fields.Datetime.to_string(now)
        self.write({'raw_data': raw_data, 'last_synced': now})
        viewer = self.env['shopee.result.viewer'].create({
            'title': title,
            'result_json': _json.dumps(value, ensure_ascii=False, indent=2),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'shopee.result.viewer',
            'res_id': viewer.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_fetch_item_extra_info(self):
        self.ensure_one()
        result = shopee_product_api.call_get_item_extra_info(
            self._get_shopee_credentials(), [int(self.shopee_item_id)]
        )
        return self._store_raw_section(
            'extra_info', result, _('Đã lấy Extra Info'), _('Đã lưu thông tin bổ sung của sản phẩm.')
        )

    def action_fetch_content_diagnosis(self):
        self.ensure_one()
        success, failure = shopee_product_api.call_get_item_content_diagnosis_result(
            self._get_shopee_credentials(), [int(self.shopee_item_id)]
        )
        return self._store_raw_section(
            'content_diagnosis',
            {'success_item_list': success, 'failure_item_list': failure},
            _('Đã chẩn đoán nội dung'),
            _('Đã lưu kết quả Content Quality vào Raw JSON.'),
        )

    def action_fetch_category_recommendation(self):
        self.ensure_one()
        if not self.item_name:
            raise UserError(_('Cần có tên sản phẩm để gợi ý danh mục.'))
        result = shopee_product_api.call_category_recommend(
            self._get_shopee_credentials(), self.item_name
        )
        return self._store_raw_section(
            'category_recommendation', result, _('Đã gợi ý danh mục')
        )

    def action_fetch_recommend_attributes(self):
        self.ensure_one()
        if not self.item_name or not self.category_id:
            raise UserError(_('Cần có tên sản phẩm và category_id để gợi ý thuộc tính.'))
        result = shopee_product_api.call_get_recommend_attribute(
            self._get_shopee_credentials(), self.item_name, self.category_id
        )
        return self._store_raw_section(
            'recommend_attribute', result, _('Đã gợi ý thuộc tính')
        )

    def action_fetch_variation_tree(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_('Cần có category_id để lấy cây phân loại Shopee.'))
        result = shopee_product_api.call_get_variations(
            self._get_shopee_credentials(), self.category_id
        )
        return self._store_raw_section(
            'variation_tree', result, _('Đã lấy cây phân loại')
        )

    def action_fetch_kit_item_limit(self):
        self.ensure_one()
        result = shopee_product_api.call_get_kit_item_limit(
            self._get_shopee_credentials(), self.category_id or None
        )
        return self._store_raw_section(
            'kit_item_limit', result, _('Đã lấy giới hạn Kit Item')
        )

    def action_fetch_kit_item_info(self):
        self.ensure_one()
        try:
            result = shopee_product_api.call_get_kit_item_info(
                self._get_shopee_credentials(), int(self.shopee_item_id)
            )
        except UserError as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Không phải bộ sản phẩm (Kit)'),
                    'message': str(exc.args[0]),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        return self._store_raw_section(
            'kit_item_info', result, _('Đã lấy Kit Item Info')
        )

    def action_check_deboost_search(self):
        self.ensure_one()
        item_ids, total_count, next_offset = shopee_product_api.call_search_item(
            self._get_shopee_credentials(),
            item_sku=self.item_sku or None,
            item_name=False if self.item_sku else self.item_name,
            item_status=self.item_status or None,
            deboost_only=True,
            page_size=10,
        )
        return self._store_raw_section(
            'deboost_search',
            {
                'item_id_list': item_ids,
                'total_count': total_count,
                'next_offset': next_offset,
                'current_item_matched': str(self.shopee_item_id) in {str(item_id) for item_id in item_ids},
            },
            _('Đã kiểm tra Deboost'),
        )

    def action_fetch_item_limit(self):
        self.ensure_one()
        result = shopee_product_api.call_get_item_limit(self._get_shopee_credentials())
        return self._store_raw_section(
            'item_limit', result, _('Đã lấy giới hạn sản phẩm')
        )

    def action_fetch_comments(self):
        self.ensure_one()
        result = shopee_product_api.call_get_comment(
            self._get_shopee_credentials(), item_id=int(self.shopee_item_id), page_size=20
        )
        return self._store_raw_section(
            'comments', result, _('Đã lấy bình luận'), _('Đã lưu danh sách bình luận vào Raw JSON.')
        )

    def action_fetch_boosted_list(self):
        self.ensure_one()
        result = shopee_product_api.call_get_boosted_list(self._get_shopee_credentials())
        current_item = str(self.shopee_item_id)
        current_boost = [item for item in result if str(item.get('item_id')) == current_item]
        return self._store_raw_section(
            'boosted_list',
            {'item_list': result, 'current_item': current_boost},
            _('Đã lấy danh sách đang đẩy hiển thị'),
        )

    def action_fetch_violation_info(self):
        self.ensure_one()
        result = shopee_product_api.call_get_item_violation_info(
            self._get_shopee_credentials(), [int(self.shopee_item_id)]
        )
        return self._store_raw_section(
            'violation_info', result, _('Đã lấy thông tin vi phạm')
        )

    def action_fetch_size_chart_list(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_('Cần có category_id để lấy danh sách bảng kích thước.'))
        result = shopee_product_api.call_get_size_chart_list(
            self._get_shopee_credentials(), self.category_id, page_size=20
        )
        return self._store_raw_section(
            'size_chart_list', result, _('Đã lấy danh sách bảng kích thước')
        )

    def _open_operation_wizard(self, operation, title):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'shopee.product.operation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_shopee_product_id': self.id,
                'default_operation': operation,
            },
        }

    def action_open_reply_comment_wizard(self):
        return self._open_operation_wizard('reply_comment', _('Trả lời bình luận Shopee'))

    def action_open_size_chart_detail_wizard(self):
        return self._open_operation_wizard('size_chart_detail', _('Chi tiết bảng kích thước'))

    def action_open_generate_kit_image_wizard(self):
        return self._open_operation_wizard('generate_kit_image', _('Tạo ảnh bộ sản phẩm'))

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
        _logger.info(
            "ShopeeProduct.sync_from_shop: partner_id=%s shop_id=%s",
            creds.get('partner_id'), creds.get('shop_identifier'),
        )

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
            int(r.shopee_item_id): r
            for r in self.sudo().search([('shop_id', '=', shop.id)])
            if r.shopee_item_id
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

    @api.model
    def import_from_shopee_items(self, shop=None):
        """Create/update product cache rows from existing sale_shopee mapping."""
        if 'shopee.item' not in self.env:
            raise UserError(_('Không tìm thấy model shopee.item để khởi tạo dữ liệu.'))

        domain = []
        if shop:
            domain.append(('shop_id', '=', shop.id))

        shopee_items = self.env['shopee.item'].sudo().search(domain)
        grouped = {}
        for item in shopee_items:
            if not item.shop_id or not item.shopee_item_identifier:
                continue
            try:
                shopee_item_id = str(int(item.shopee_item_identifier))  # normalize to str
            except (TypeError, ValueError):
                _logger.warning(
                    "Skip shopee.item %s with invalid item id %r",
                    item.id, item.shopee_item_identifier,
                )
                continue
            grouped.setdefault((item.shop_id.id, shopee_item_id), self.env['shopee.item'].sudo().browse())
            grouped[(item.shop_id.id, shopee_item_id)] |= item

        created = updated = 0
        now = fields.Datetime.now()
        existing = {
            (rec.shop_id.id, rec.shopee_item_id): rec
            for rec in self.sudo().search([])
        }

        for (shop_id, shopee_item_id), mappings in grouped.items():
            products = mappings.mapped('product_id')
            first_product = products[:1]
            first_mapping = mappings[:1]
            model_identifiers = [m.shopee_model_identifier for m in mappings if m.shopee_model_identifier]
            has_model = len(mappings) > 1 or bool(model_identifiers)
            item_name = first_product.display_name or _('Shopee Item %s') % shopee_item_id
            item_sku = first_product.default_code or ''
            vals = {
                'shop_id': shop_id,
                'shopee_item_id': shopee_item_id,
                'item_name': item_name,
                'item_sku': item_sku,
                'item_status': 'NORMAL',
                'original_price': first_product.lst_price or first_product.list_price or 0.0,
                'current_price': first_product.lst_price or first_product.list_price or 0.0,
                'total_available_stock': sum(products.mapped('qty_available')),
                'has_model': has_model,
                'last_synced': now,
                'raw_data': {
                    'source': 'shopee.item',
                    'mapping_ids': mappings.ids,
                    'first_mapping_id': first_mapping.id,
                    'mapped_product_ids': products.ids,
                },
            }
            rec = existing.get((shop_id, shopee_item_id))
            if rec:
                rec.write(vals)
                updated += 1
            else:
                rec = self.sudo().create(vals)
                created += 1
            rec._sync_models_from_shopee_item_mappings(mappings, now)

        _logger.info(
            "ShopeeProduct.import_from_shopee_items: tạo mới=%d cập nhật=%d mappings=%d",
            created, updated, len(shopee_items),
        )
        return created, updated, len(shopee_items)

    # ── write override ──────────────────────────────────────────────────────

    def write(self, vals):
        result = super().write(vals)
        if 'odoo_product_id' in vals:
            self._sync_manual_link_to_shopee_item()
        return result

    def _sync_manual_link_to_shopee_item(self):
        """Khi odoo_product_id được set thủ công, tự tạo/cập nhật bản ghi shopee.item."""
        ShopeeItem = self.env['shopee.item'].sudo()
        for rec in self:
            if not rec.shop_id or not rec.shopee_item_id:
                continue
            if not rec.odoo_product_id:
                continue
            existing = ShopeeItem.search([
                ('shop_id', '=', rec.shop_id.id),
                ('shopee_item_identifier', '=', str(rec.shopee_item_id)),
                ('shopee_model_identifier', 'in', [False, '', '0']),
            ], limit=1)
            if existing:
                if existing.product_id.id != rec.odoo_product_id.id:
                    existing.write({'product_id': rec.odoo_product_id.id})
            else:
                ShopeeItem.create({
                    'shop_id': rec.shop_id.id,
                    'shopee_item_identifier': str(rec.shopee_item_id),
                    'product_id': rec.odoo_product_id.id,
                })

    def _sync_models_from_shopee_item_mappings(self, mappings, now=None):
        """Create lightweight model lines from sale_shopee mapping rows."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        existing = {line.shopee_model_id: line for line in self.model_ids}
        seen_model_ids = set()
        for mapping in mappings:
            model_identifier = str(mapping.shopee_model_identifier or '')
            if not model_identifier or model_identifier in seen_model_ids:
                continue
            seen_model_ids.add(model_identifier)
            product = mapping.product_id
            product_name = product.display_name if product else mapping.display_name
            product_sku = product.default_code if product else ''
            product_price = (product.lst_price or product.list_price or 0.0) if product else 0.0
            product_stock = product.qty_available if product else 0
            vals = {
                'shopee_model_id': model_identifier,
                'model_sku': product_sku or '',
                'model_status': 'MODEL_NORMAL',
                'tier_label': product_name or model_identifier,
                'original_price': product_price,
                'current_price': product_price,
                'new_price': product_price,
                'available_stock': product_stock,
                'new_stock': product_stock,
                'last_synced': now,
            }
            if model_identifier in existing:
                existing[model_identifier].write(vals)
            else:
                self.env['shopee.product.model'].sudo().create({
                    'shopee_product_id': self.id,
                    **vals,
                })


# ── Private helpers ──────────────────────────────────────

def _extract_price(item_data):
    """Lấy original_price và current_price từ price_info list."""
    price_info = item_data.get('price_info', [])
    if isinstance(price_info, list) and price_info:
        first = price_info[0]
        if isinstance(first, dict):
            return first.get('original_price', 0.0), first.get('current_price', 0.0)
    return 0.0, 0.0


def _extract_stock(item_data):
    """Lấy total_available_stock từ stock_info_v2."""
    stock_v2 = item_data.get('stock_info_v2')
    if not isinstance(stock_v2, dict):
        return 0
    summary = stock_v2.get('summary_info')
    if not isinstance(summary, dict):
        return 0
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
        'shopee_item_id': str(item_data['item_id']),
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
