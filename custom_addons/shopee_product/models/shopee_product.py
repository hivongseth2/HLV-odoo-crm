# -*- coding: utf-8 -*-
"""
models/shopee_product.py

Model lưu trữ cache sản phẩm đã đồng bộ từ Shopee.

Mỗi record = 1 item trên 1 shop Shopee.
Dùng để theo dõi, quản lý và đẩy sản phẩm từ Odoo lên Shopee.
"""
import base64
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
    category_display = fields.Char(
        string='Danh mục Shopee',
        compute='_compute_category_display',
    )
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
    last_api_section = fields.Char(string='Nhóm API gần nhất', readonly=True)
    last_api_synced_at = fields.Datetime(string='API cập nhật lần cuối', readonly=True)

    # ── Editor nội dung ─────────────────────────────────
    edit_description = fields.Text(string='Mô tả Shopee')
    image_line_ids = fields.One2many(
        'shopee.product.image', 'shopee_product_id', string='Ảnh Shopee',
    )
    video_line_ids = fields.One2many(
        'shopee.product.video', 'shopee_product_id', string='Video Shopee',
    )
    quality_summary = fields.Text(string='Chất lượng nội dung', readonly=True)
    violation_summary = fields.Text(string='Vi phạm', readonly=True)
    extra_summary = fields.Text(string='Thông tin thêm', readonly=True)
    quality_last_checked = fields.Datetime(string='Kiểm tra nội dung lúc', readonly=True)

    # ── Hàng đợi đồng bộ tồn kho ─────────────────────────
    pending_stock_sync = fields.Boolean(
        string='Chờ đồng bộ tồn kho',
        default=False,
        help='True khi tồn kho thay đổi qua phiếu kho và đang chờ đồng bộ lên Shopee.',
    )
    pending_sync_since = fields.Datetime(string='Đánh dấu lúc', readonly=True)

    # ── Cấu hình tồn kho ─────────────────────────────────
    stock_update_mode = fields.Selection([
        ('manual', 'Thủ công'),
        ('total_warehouses', 'Tổng tất cả kho'),
        ('warehouse', 'Theo kho'),
        ('fixed_location', 'Vị trí cố định'),
    ], string='Phương thức cập nhật tồn kho', default='manual')
    stock_warehouse_id = fields.Many2one('stock.warehouse', string='Kho hàng')
    stock_location_id = fields.Many2one(
        'stock.location', string='Vị trí kho',
        domain="[('usage', '=', 'internal')]",
    )
    manual_stock = fields.Integer(string='Tồn kho thủ công', default=0)

    # ── Cấu hình giá ─────────────────────────────────────
    price_update_mode = fields.Selection([
        ('manual', 'Thủ công'),
        ('price_field', 'Cột giá từ sản phẩm'),
    ], string='Phương thức cập nhật giá', default='manual')
    price_field_id = fields.Many2one(
        'ir.model.fields',
        string='Cột giá (product.template)',
        domain="[('model', '=', 'product.template'), ('ttype', 'in', ['float', 'monetary', 'integer'])]",
        help='Chọn bất kỳ cột số trên product.template: list_price, standard_price, x_studio_gia_san_tmdt, x_studio_gi_bn_thng_mi, x_studio_ga_web, ...',
    )
    manual_price = fields.Float(string='Giá thủ công', digits=(16, 0), default=0)

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

    @api.depends('category_id', 'raw_data')
    def _compute_category_display(self):
        for rec in self:
            cid = rec.category_id or 0
            name = ''
            raw = rec.raw_data if isinstance(rec.raw_data, dict) else {}
            cat_info = raw.get('category_info') or raw.get('category') or {}
            if isinstance(cat_info, dict):
                name = cat_info.get('display_name') or cat_info.get('name') or ''
            if name:
                rec.category_display = f"{cid} — {name}"
            else:
                rec.category_display = str(cid) if cid else ''



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
        item_id = int(self.shopee_item_id)
        items = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_base_info(creds, [item_id])
        )
        if not items:
            raise UserError(_("Không tìm thấy thông tin sản phẩm ID %s trên Shopee.") % self.shopee_item_id)
        _update_record_from_api(self, items[0])
        self.with_context(skip_shopee_auto_quality=True).action_fetch_full_content()
        self._auto_refresh_quality_panels()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
        item_id = int(self.shopee_item_id)
        model_list, tier_variation_list = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_model_list(creds, item_id)
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
        """Đẩy giá lên Shopee theo price_update_mode và reload form."""
        self.ensure_one()
        mode = self.price_update_mode or 'manual'
        fname = self.price_field_id.name if self.price_field_id else None

        def _price_from_product(product):
            if not product or not fname:
                return 0.0
            val = getattr(product, fname, None)
            if not val and hasattr(product, 'product_tmpl_id'):
                val = getattr(product.product_tmpl_id, fname, None)
            return float(val or 0)

        if mode == 'price_field' and not fname:
            raise UserError(_('Vui lòng chọn cột giá từ product.template.'))

        if self.has_model and self.model_ids:
            price_list = []
            for m in self.model_ids:
                if not m.shopee_model_id:
                    continue
                if mode == 'price_field':
                    product = m.mapped_product_id
                    if not product:
                        raise UserError(_(
                            'Biến thể "%s" chưa có mapping shopee.item → product.product, không đọc được giá.'
                        ) % (m.tier_label or m.model_sku or m.shopee_model_id))
                    price = _price_from_product(product)
                else:
                    price = m.new_price
                if price > 0:
                    price_list.append({'model_id': int(m.shopee_model_id), 'original_price': price})
        else:
            if mode == 'price_field':
                product = self.mapped_product_ids[:1] or self.odoo_product_id
                if not product:
                    raise UserError(_('Sản phẩm chưa có mapping Odoo để đọc giá.'))
                price = _price_from_product(product)
            else:
                price = self.manual_price or self.original_price
            price_list = [{'model_id': 0, 'original_price': price}] if price > 0 else []

        if not price_list:
            raise UserError(_('Không có giá hợp lệ để cập nhật.'))

        item_id = int(self.shopee_item_id)
        success, failure = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_update_price(creds, item_id, price_list)
        )

        if failure:
            msgs = ', '.join(
                f"Model {f.get('model_id')}: {f.get('failed_reason')}" for f in failure
            )
            raise UserError(_('Một số giá cập nhật thất bại: %s') % msgs)

        # Tự refresh sau khi push
        self.action_refresh_from_shopee()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _do_push_stock(self):
        """Đẩy tồn kho lên Shopee (không reload). Dùng cho cron và action_push_stock."""
        self.ensure_one()
        mode = self.stock_update_mode or 'manual'

        if mode == 'warehouse' and not self.stock_warehouse_id:
            raise UserError(_('Vui lòng chọn kho hàng.'))
        if mode == 'fixed_location' and not self.stock_location_id:
            raise UserError(_('Vui lòng chọn vị trí kho.'))

        def _qty_from_product(product):
            if not product:
                return 0
            if mode == 'total_warehouses':
                qty = product.qty_available
            elif mode == 'warehouse':
                qty = product.with_context(warehouse=self.stock_warehouse_id.id).qty_available
            elif mode == 'fixed_location':
                loc_ids = self.stock_location_id.search([
                    ('id', 'child_of', self.stock_location_id.id),
                    ('usage', '=', 'internal'),
                ]).ids
                qty = product.with_context(location=loc_ids).qty_available
                _logger.info(
                    "Shopee push_stock fixed_location: product=%s location=%s child_ids=%s qty=%s",
                    product.display_name, self.stock_location_id.complete_name, loc_ids, qty,
                )
            else:
                qty = 0
            return int(qty or 0)

        if self.has_model and self.model_ids:
            stock_list = []
            for m in self.model_ids:
                if not m.shopee_model_id:
                    continue
                if mode == 'manual':
                    qty = m.new_stock
                else:
                    product = m.mapped_product_id
                    if not product:
                        raise UserError(_(
                            'Biến thể "%s" chưa có mapping shopee.item → product.product, không đọc được tồn kho.'
                        ) % (m.tier_label or m.model_sku or m.shopee_model_id))
                    qty = _qty_from_product(product)
                stock_list.append({
                    'model_id': int(m.shopee_model_id),
                    'seller_stock': [{'stock': qty}],
                })
        else:
            if mode == 'manual':
                qty = self.manual_stock
            else:
                product = self.mapped_product_ids[:1] or self.odoo_product_id
                if not product:
                    raise UserError(_('Sản phẩm chưa có mapping Odoo để đọc tồn kho.'))
                qty = _qty_from_product(product)
            stock_list = [{'model_id': 0, 'seller_stock': [{'stock': qty}]}]

        if not stock_list:
            raise UserError(_('Không có tồn kho hợp lệ để cập nhật.'))

        item_id = int(self.shopee_item_id)
        success, failure = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_update_stock(creds, item_id, stock_list)
        )

        if failure:
            msgs = ', '.join(
                f"Model {f.get('model_id')}: {f.get('failed_reason')}" for f in failure
            )
            raise UserError(_('Một số tồn kho cập nhật thất bại: %s') % msgs)

    def action_push_stock(self):
        """Đẩy tồn kho lên Shopee theo stock_update_mode và reload form."""
        self.ensure_one()
        self._do_push_stock()
        # Tự refresh sau khi push
        self.action_refresh_from_shopee()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def cron_push_stock_to_shopee(self):
        """Scheduled action: đồng bộ tồn kho → Shopee cho tất cả sản phẩm auto-mode."""
        products = self.search([
            ('stock_update_mode', 'not in', ['manual', False]),
            ('item_status', 'not in', ['SELLER_DELETE', 'SHOPEE_DELETE']),
        ])
        success_count = 0
        error_count = 0
        for product in products:
            try:
                product._do_push_stock()
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(
                    "Shopee cron_push_stock: thất bại id=%s item=%s: %s",
                    product.id, product.shopee_item_id, str(e),
                )
        _logger.info(
            "Shopee cron_push_stock: hoàn tất — %d thành công, %d lỗi",
            success_count, error_count,
        )

    def action_bulk_sync_stock(self):
        """Đồng bộ tồn kho hàng loạt cho các sản phẩm được chọn (chế độ auto)."""
        auto_products = self.filtered(
            lambda p: p.stock_update_mode and p.stock_update_mode != 'manual'
        )
        if not auto_products:
            raise UserError(_('Không có sản phẩm nào có chế độ tồn kho tự động trong danh sách đã chọn.'))
        success_count = 0
        error_msgs = []
        for product in auto_products:
            try:
                product._do_push_stock()
                success_count += 1
            except Exception as e:
                error_msgs.append('%s: %s' % (product.item_name or product.shopee_item_id, str(e)))
        if error_msgs:
            raise UserError(
                _('Đồng bộ thành công %d sản phẩm.\nLỗi:\n%s') % (
                    success_count, '\n'.join(error_msgs[:10])
                )
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ tồn kho hoàn tất'),
                'message': _('Đã đồng bộ thành công %d sản phẩm lên Shopee.') % success_count,
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _mark_for_stock_sync(self, product_ids):
        """Đánh dấu shopee.products cần đồng bộ tồn kho khi Odoo product.product thay đổi.

        Được gọi từ stock.picking._action_done() sau khi phiếu kho hoàn thành.
        Tìm kiếm qua cả odoo_product_id (link thủ công) và shopee.item mapping.
        Đánh dấu TẤT CẢ sản phẩm có liên kết — kể cả mode thủ công.
        Cron sẽ tự xử lý: push nếu auto-mode, skip nếu manual.
        """
        if not product_ids:
            return

        # 1. Tìm qua odoo_product_id (liên kết thủ công trực tiếp)
        direct = self.search([('odoo_product_id', 'in', product_ids)])

        # 2. Tìm qua shopee.item mapping (sale_shopee / shopee_order_fetch)
        via_items = self.browse()
        try:
            shopee_items = self.env['shopee.item'].sudo().search(
                [('product_id', 'in', product_ids)]
            )
            if shopee_items:
                item_identifiers = list({
                    str(si.shopee_item_identifier)
                    for si in shopee_items
                    if si.shopee_item_identifier
                })
                via_items = self.search([
                    ('shopee_item_id', 'in', item_identifiers),
                    ('id', 'not in', direct.ids),
                ])
        except Exception as e:
            _logger.info(
                "Shopee _mark_for_stock_sync: shopee.item lookup failed (model missing?): %s", e
            )

        to_mark = direct | via_items
        _logger.info(
            "Shopee _mark_for_stock_sync: %d sản phẩm Odoo thay đổi → "
            "%d direct (odoo_product_id) + %d via shopee.item = %d tổng cộng",
            len(product_ids), len(direct), len(via_items), len(to_mark),
        )
        if not to_mark:
            _logger.info(
                "Shopee _mark_for_stock_sync: không tìm thấy shopee.product nào liên kết "
                "với product_ids=%s. Kiểm tra odoo_product_id hoặc shopee.item mapping.",
                product_ids[:10],
            )
            return

        now = fields.Datetime.now()
        to_mark.write({'pending_stock_sync': True, 'pending_sync_since': now})
        # Tạo / cập nhật log entry cho mỗi sản phẩm
        SyncLog = self.env['shopee.stock.sync.log'].sudo()
        for product in to_mark:
            existing = SyncLog.search([
                ('shopee_product_id', '=', product.id),
                ('state', '=', 'pending'),
            ], limit=1)
            if existing:
                existing.write({'triggered_at': now})
            else:
                SyncLog.create({
                    'shopee_product_id': product.id,
                    'state': 'pending',
                    'stock_update_mode': product.stock_update_mode or 'manual',
                    'triggered_at': now,
                })
        _logger.info(
            "Shopee: đánh dấu %d sản phẩm chờ đồng bộ tồn kho (triggered by %d products)",
                len(to_mark), len(product_ids),
            )

    @api.model
    def cron_process_stock_sync_queue(self):
        """Scheduled action: xử lý hàng đợi đồng bộ tồn kho Shopee.

        Chạy thường xuyên (VD: mỗi 15 phút) để đẩy tồn kho sau khi
        phiếu kho được xác nhận qua app barcode hoặc thủ công.
        """
        # Lấy TẤT CẢ pending (kể cả manual) để clear flag và log
        pending = self.search([
            ('pending_stock_sync', '=', True),
            ('item_status', 'not in', ['SELLER_DELETE', 'SHOPEE_DELETE']),
        ])
        if not pending:
            return
        success_count = 0
        error_count = 0
        skip_count = 0
        SyncLog = self.env['shopee.stock.sync.log'].sudo()
        now = fields.Datetime.now()
        for product in pending:
            log = SyncLog.search([
                ('shopee_product_id', '=', product.id),
                ('state', '=', 'pending'),
            ], limit=1)

            # Sản phẩm mode thủ công → bỏ qua (không đẩy), clear flag
            if not product.stock_update_mode or product.stock_update_mode == 'manual':
                skip_count += 1
                product.write({'pending_stock_sync': False, 'pending_sync_since': False})
                if log:
                    log.write({
                        'state': 'skipped',
                        'synced_at': now,
                        'error_message': 'Chế độ thủ công — không tự đồng bộ. Cấu hình stock_update_mode để bật auto-sync.',
                    })
                continue

            try:
                product._do_push_stock()
                stock_qty = product.total_available_stock
                product.write({'pending_stock_sync': False, 'pending_sync_since': False})
                success_count += 1
                if log:
                    log.write({
                        'state': 'done',
                        'synced_at': now,
                        'stock_qty': stock_qty,
                    })
            except Exception as e:
                error_count += 1
                err_msg = str(e)
                _logger.error(
                    "Shopee stock sync queue: thất bại id=%s item=%s: %s",
                    product.id, product.shopee_item_id, err_msg,
                )
                if log:
                    log.write({
                        'state': 'error',
                        'synced_at': now,
                        'error_message': err_msg,
                    })
        _logger.info(
            "Shopee stock sync queue: hoàn tất — %d thành công, %d lỗi, %d bỏ qua (manual)",
            success_count, error_count, skip_count,
        )

    def action_delete_from_shopee(self):
        """Xóa sản phẩm này khỏi Shopee (soft delete — trạng thái SELLER_DELETE)."""
        self.ensure_one()
        item_id = int(self.shopee_item_id)
        self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_delete_item(creds, [item_id])
        )
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

    def _call_with_token_refresh(self, fn):
        """
        Gọi fn(creds) và tự động làm mới token nếu Shopee trả invalid_access_token,
        sau đó retry một lần.

        :param fn: callable nhận creds dict, thực hiện Shopee API call
        :return: kết quả của fn
        """
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
            SHOPEE_INVALID_TOKEN_ERRORS,
        )
        creds = get_credentials_from_shop(self.shop_id)
        try:
            return fn(creds)
        except UserError as exc:
            msg = str(exc.args[0]) if exc.args else ''
            if any(code in msg for code in SHOPEE_INVALID_TOKEN_ERRORS):
                _logger.warning(
                    "Shopee invalid_access_token cho shop %s — đang tự refresh...",
                    self.shop_id.display_name,
                )
                self.shop_id._refresh_shopee_token()
                creds = get_credentials_from_shop(self.shop_id)
                return fn(creds)
            raise

    def _store_raw_section(self, section, value, title, message=None):
        """Lưu kết quả API vào raw_data và hiển thị thông báo dễ đọc."""
        self.ensure_one()
        raw_data = self.raw_data if isinstance(self.raw_data, dict) else {}
        raw_data = dict(raw_data)
        now = fields.Datetime.now()
        raw_data[section] = value
        self.write({
            'raw_data': raw_data,
            'last_synced': now,
            'last_api_section': section,
            'last_api_synced_at': now,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': str(title),
                'message': str(message) if message else '',
                'type': 'success',
                'sticky': True,
            },
        }

    def action_fetch_full_content(self):
        """Lấy đầy đủ nội dung sản phẩm từ Shopee (mô tả, ảnh, video).

        Dùng GET /api/v2/product/get_item_base_info — trả về dict với
        description, image (image_id_list, image_url_list), video_info...
        Lưu vào raw_data['full_content'] để form view hiển thị.
        """
        self.ensure_one()
        if not self.shopee_item_id:
            raise UserError(_('Sản phẩm chưa có shopee_item_id.'))
        item_id = int(self.shopee_item_id)
        items = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_base_info(creds, [item_id])
        )
        item = (items or [{}])[0] if isinstance(items, list) else items
        if not isinstance(item, dict):
            raise UserError(_('Shopee trả về dữ liệu không hợp lệ: %s') % item)

        # Trích xuất các phần thường dùng
        desc = item.get('description') or ''
        if isinstance(item.get('description_info'), dict):
            # description_info dạng extended (rich text + images)
            ext = item['description_info'].get('extended_description', {})
            field_list = ext.get('field_list') or []
            extended_text = []
            for f in field_list:
                if f.get('field_type') == 'text':
                    # Shopee có thể trả 'text' là str (mới) hoặc dict {'text': str}
                    raw = f.get('text', '')
                    if isinstance(raw, dict):
                        extended_text.append(raw.get('text', '') or '')
                    elif isinstance(raw, str):
                        extended_text.append(raw)
                elif f.get('field_type') == 'image':
                    img = f.get('image_info', {}) or {}
                    if isinstance(img, dict):
                        extended_text.append('[ẢNH] %s' % (img.get('image_url') or img.get('image_id') or ''))
            if extended_text:
                desc = (desc + '\n\n--- Extended ---\n' + '\n'.join(extended_text)) if desc else '\n'.join(extended_text)

        images = item.get('image', {}) or {}
        image_id_list = images.get('image_id_list') or []
        image_url_list = images.get('image_url_list') or []
        video_info_list = item.get('video_info') or []

        image_commands = [(5, 0, 0)]
        for seq, image_id in enumerate(image_id_list, 1):
            image_commands.append((0, 0, {
                'sequence': seq,
                'image_id': image_id,
                'image_url': image_url_list[seq - 1] if len(image_url_list) >= seq else '',
                'active': True,
            }))
        video_commands = [(5, 0, 0)]
        for seq, video in enumerate(video_info_list, 1):
            v_url = video.get('video_url_list', [{}])[0].get('video_url') if video.get('video_url_list') else ''
            video_commands.append((0, 0, {
                'sequence': seq,
                'video_id': video.get('video_id') or video.get('video_upload_id') or '',
                'video_url': v_url,
                'duration': video.get('duration') or 0,
                'active': True,
            }))
        self.write({
            'edit_description': desc,
            'image_line_ids': image_commands,
            'video_line_ids': video_commands,
        })

        summary_lines = [
            _('Tên: %s') % (item.get('item_name') or ''),
            _('Mô tả: %d ký tự') % len(desc),
            _('Ảnh: %d') % len(image_id_list),
            _('Video: %d') % len(video_info_list),
            _('Trạng thái: %s') % (item.get('item_status') or ''),
            _('Danh mục: %s') % (item.get('category_id') or ''),
        ]
        # Liệt kê URL ảnh (tối đa 5 đầu)
        for i, url in enumerate(image_url_list[:5], 1):
            summary_lines.append('  ảnh %d: %s' % (i, url))
        # Video
        for i, v in enumerate(video_info_list[:3], 1):
            v_url = v.get('video_url_list', [{}])[0].get('video_url') if v.get('video_url_list') else ''
            summary_lines.append('  video %d: %s (%ss)' % (
                i, v_url or v.get('video_id', ''), v.get('duration', '?')
            ))

        return self._store_raw_section(
            'full_content',
            {
                'description': desc,
                'image_id_list': image_id_list,
                'image_url_list': image_url_list,
                'video_info_list': video_info_list,
                'item_name': item.get('item_name'),
                'category_id': item.get('category_id'),
            },
            _('Nội dung sản phẩm Shopee'),
            '\n'.join(summary_lines),
        )

    def action_push_content_update(self):
        """Đẩy mô tả, ảnh, video đã chỉnh trên form về Shopee qua update_item."""
        self.ensure_one()
        if not self.shopee_item_id:
            raise UserError(_('Sản phẩm chưa có shopee_item_id.'))
        active_images = self.image_line_ids.filtered(lambda l: l.active).sorted('sequence')
        image_id_list = []
        for line in active_images:
            if line.upload_image:
                image_binary = base64.b64decode(line.upload_image)
                line.image_id = self._call_with_token_refresh(
                    lambda creds: shopee_product_api.call_upload_image(creds, image_binary)
                )
            if line.image_id:
                image_id_list.append(line.image_id)
        if not image_id_list:
            raise UserError(_('Shopee yêu cầu ít nhất một ảnh sản phẩm.'))

        video_upload_ids = []
        for line in self.video_line_ids.filtered(lambda l: l.active).sorted('sequence'):
            if line.upload_video:
                video_binary = base64.b64decode(line.upload_video)
                line.video_upload_id = self._call_with_token_refresh(
                    lambda creds: shopee_product_api.call_upload_video(
                        creds, video_binary, filename=line.upload_filename or 'product.mp4',
                    )
                )
            if line.video_upload_id:
                video_upload_ids.append(line.video_upload_id)

        payload = {
            'description': self.edit_description or self.item_name or '',
            'image': {'image_id_list': image_id_list},
        }
        if video_upload_ids:
            payload['video_upload_id'] = video_upload_ids
        item_id = int(self.shopee_item_id)
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_update_item(creds, item_id, payload)
        )
        self.action_fetch_full_content()
        return self._store_raw_section(
            'content_update', result, _('Cập nhật nội dung'),
            _('Đã đẩy mô tả/ảnh/video lên Shopee.'),
        )

    def _get_credentials(self):
        from odoo.addons.shopee_order_fetch.services.shopee_api import get_credentials_from_shop
        self.ensure_one()
        return get_credentials_from_shop(self.shop_id)

    def action_fetch_item_extra_info(self):
        self.ensure_one()
        item_id = int(self.shopee_item_id)
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_extra_info(creds, [item_id])
        )
        items = result if isinstance(result, list) else [result]
        item = items[0] if items else {}
        parts = []
        if 'view_count' in item:
            parts.append(_("Lượt xem: %s") % f"{item['view_count']:,}")
        if 'liked_count' in item:
            parts.append(_("Lượt thích: %s") % f"{item['liked_count']:,}")
        if 'comment_count' in item:
            parts.append(_("Bình luận: %s") % f"{item['comment_count']:,}")
        if 'sold' in item:
            parts.append(_("Số bán: %s") % f"{item['sold']:,}")
        msg = "\n".join(parts) if parts else _('Đã lấy thông tin bổ sung')
        self.write({'extra_summary': msg, 'quality_last_checked': fields.Datetime.now()})
        return self._store_raw_section('extra_info', result, _('Thông tin bổ sung'), msg)

    def action_fetch_content_diagnosis(self):
        self.ensure_one()
        item_id = int(self.shopee_item_id)
        success, failure = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_content_diagnosis_result(creds, [item_id])
        )
        data = {'success_item_list': success, 'failure_item_list': failure}
        if failure:
            msg = _('❌ Không lấy được kết quả (%d lỗi)') % len(failure)
        elif success:
            item = success[0]
            level = item.get('quality_level', '?')
            tasks = item.get('unfinished_task', [])
            if tasks:
                lines = [_('Chất lượng nội dung: Cấp %s/3') % level, _('Cần cải thiện:')]
                for t in tasks[:8]:
                    lines.append('  • %s' % t.get('suggestion', ''))
                msg = '\n'.join(lines)
            else:
                msg = _('Chất lượng nội dung: Cấp %s/3\n✓ Không còn vấn đề cần cải thiện') % level
        else:
            msg = _('Không có dữ liệu chẩn đoán')
        self.write({'quality_summary': msg, 'quality_last_checked': fields.Datetime.now()})
        return self._store_raw_section('content_diagnosis', data, _('Chẩn đoán nội dung'), msg)

    def action_fetch_category_recommendation(self):
        self.ensure_one()
        if not self.item_name:
            raise UserError(_('Cần có tên sản phẩm để gợi ý danh mục.'))
        item_name = self.item_name
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_category_recommend(creds, item_name)
        )
        # Shopee trả về list of int category_id (hoặc list of dict tuỳ phiên bản).
        if isinstance(result, dict):
            cats_raw = result.get('category_id') or result.get('category') or result.get('categories') or []
        else:
            cats_raw = result or []

        # Build name map từ get_category (cache trong raw_data nếu có).
        name_map = {}
        if cats_raw and not (cats_raw and isinstance(cats_raw[0], dict)):
            try:
                cat_list = self._call_with_token_refresh(
                    lambda creds: shopee_product_api.call_get_category(creds)
                )
                for c in (cat_list or []):
                    name_map[c.get('category_id')] = (
                        c.get('display_category_name')
                        or c.get('original_category_name')
                        or ''
                    )
            except Exception as e:
                _logger.warning('Không lấy được tên category để enrich: %s', e)

        if cats_raw:
            lines = [_('Danh mục gợi ý:')]
            for i, c in enumerate(cats_raw[:8], 1):
                if isinstance(c, dict):
                    name = c.get('display_category_name') or c.get('category_name') or '?'
                    cid = c.get('category_id', '')
                else:
                    cid = c
                    name = name_map.get(cid, '?')
                lines.append('  %d. %s (ID: %s)' % (i, name, cid))
            msg = '\n'.join(lines)
        else:
            msg = _('Không có gợi ý danh mục')
        return self._store_raw_section('category_recommendation', result, _('Gợi ý danh mục'), msg)

    def action_fetch_recommend_attributes(self):
        self.ensure_one()
        if not self.item_name or not self.category_id:
            raise UserError(_('Cần có tên sản phẩm và category_id để gợi ý thuộc tính.'))
        item_name = self.item_name
        cat_id = self.category_id
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_recommend_attribute(creds, item_name, cat_id)
        )
        # Service trả về list attribute_list trực tiếp.
        if isinstance(result, list):
            attrs = result
        elif isinstance(result, dict):
            attrs = result.get('attribute_list') or result.get('attribute') or result.get('attributes') or []
        else:
            attrs = []
        if attrs:
            names = []
            for a in attrs[:12]:
                if isinstance(a, dict):
                    names.append(a.get('attribute_name') or a.get('original_attribute_name') or '?')
                else:
                    names.append(str(a))
            msg = _('Thuộc tính gợi ý:\n') + '\n'.join('  • %s' % n for n in names)
        else:
            msg = _('Không có gợi ý thuộc tính')
        return self._store_raw_section('recommend_attribute', result, _('Gợi ý thuộc tính'), msg)

    def action_fetch_variation_tree(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_('Cần có category_id để lấy cây phân loại Shopee.'))
        cat_id = self.category_id
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_variations(creds, cat_id)
        )
        if isinstance(result, list):
            variations = result
        elif isinstance(result, dict):
            variations = result.get('standardise_variation_list') or result.get('variation') or result.get('variations') or []
        else:
            variations = []
        count = len(variations) if isinstance(variations, list) else 0
        msg = _('Tìm thấy %d cấp phân loại cho danh mục %s') % (count, cat_id)
        return self._store_raw_section('variation_tree', result, _('Cây phân loại'), msg)

    def action_fetch_kit_item_limit(self):
        self.ensure_one()
        cat_id = self.category_id or None
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_kit_item_limit(creds, cat_id)
        )
        max_count = result.get('max_model_count', result.get('max_count', '?'))
        msg = _('Giới hạn sản phẩm trong bộ: %s') % max_count
        return self._store_raw_section('kit_item_limit', result, _('Giới hạn Kit Item'), msg)

    def action_fetch_kit_item_info(self):
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            SHOPEE_INVALID_TOKEN_ERRORS,
        )
        item_id = int(self.shopee_item_id)
        try:
            result = self._call_with_token_refresh(
                lambda creds: shopee_product_api.call_get_kit_item_info(creds, item_id)
            )
        except UserError as exc:
            if any(code in str(exc) for code in SHOPEE_INVALID_TOKEN_ERRORS):
                raise
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
        models_in_kit = result.get('model_list', result.get('item_list', []))
        kit_count = len(models_in_kit) if isinstance(models_in_kit, list) else 0
        msg = _('Bộ sản phẩm gồm %d thành phần') % kit_count
        return self._store_raw_section(
            'kit_item_info', result, _('Thông tin bộ sản phẩm'), msg
        )

    def action_check_deboost_search(self):
        self.ensure_one()
        _item_sku = self.item_sku or None
        _item_name = False if self.item_sku else self.item_name
        _item_status = self.item_status or None
        item_ids, total_count, next_offset = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_search_item(
                creds,
                item_sku=_item_sku,
                item_name=_item_name,
                item_status=_item_status,
                deboost_only=True,
                page_size=10,
            )
        )
        current_matched = str(self.shopee_item_id) in {str(i) for i in item_ids}
        data = {
            'item_id_list': item_ids,
            'total_count': total_count,
            'next_offset': next_offset,
            'current_item_matched': current_matched,
        }
        if current_matched:
            msg = _('⚠ Sản phẩm này đang bị hạ hạng (deboost)\nTổng trong danh sách deboost: %d') % total_count
        else:
            msg = _('✓ Sản phẩm này không bị hạ hạng\nTổng trong danh sách deboost: %d') % total_count
        return self._store_raw_section('deboost_search', data, _('Kiểm tra Deboost'), msg)

    def action_fetch_item_limit(self):
        self.ensure_one()
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_limit(creds)
        )
        parts = []
        for k in ['item_total_count', 'max_item_count', 'sold_count', 'item_left']:
            if k in result:
                label = k.replace('_', ' ').title()
                parts.append('%s: %s' % (label, result[k]))
        if not parts:
            parts = ['%s: %s' % (str(k).replace('_', ' ').title(), v)
                     for k, v in result.items() if isinstance(v, (int, float))][:6]
        msg = '\n'.join(parts) if parts else _('Đã lấy giới hạn sản phẩm')
        return self._store_raw_section('item_limit', result, _('Giới hạn sản phẩm'), msg)

    def action_fetch_comments(self):
        self.ensure_one()
        item_id = int(self.shopee_item_id)
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_comment(creds, item_id=item_id, page_size=20)
        )
        comments = result.get('comment', result.get('comments', []))
        total = result.get('item_total', result.get('total', len(comments)))
        if comments:
            lines = [_('Tổng %d bình luận. Mới nhất:') % total]
            for c in comments[:3]:
                author = c.get('buyer_username') or c.get('username') or '?'
                rating = c.get('rating_star', c.get('rating', 0))
                content = c.get('comment', '')[:60]
                stars = '★' * int(rating) if rating else ''
                lines.append('  • %s %s: %s' % (author, stars, content))
            msg = '\n'.join(lines)
        else:
            msg = _('Không có bình luận (tổng: %d)') % total
        return self._store_raw_section('comments', result, _('Bình luận'), msg)

    def action_fetch_boosted_list(self):
        self.ensure_one()
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_boosted_list(creds)
        )
        current_item = str(self.shopee_item_id)
        current_boost = [item for item in result if str(item.get('item_id')) == current_item]
        total_boost = len(result)
        if current_boost:
            msg = _('✓ Sản phẩm này đang được đẩy hiển thị\nTổng đang đẩy trong shop: %d') % total_boost
        else:
            msg = _('Sản phẩm này chưa được đẩy hiển thị\nTổng đang đẩy trong shop: %d') % total_boost
        return self._store_raw_section(
            'boosted_list',
            {'item_list': result, 'current_item': current_boost},
            _('Trạng thái đẩy hiển thị'),
            msg,
        )

    def action_fetch_violation_info(self):
        self.ensure_one()
        item_id = int(self.shopee_item_id)
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_item_violation_info(creds, [item_id])
        )
        items = result if isinstance(result, list) else (result.get('item_list') or [])
        if not items:
            msg = _('✓ Không tìm thấy thông tin vi phạm')
        else:
            item = items[0]
            deboost_flag = item.get('deboost', False)
            status = item.get('item_status', '?')
            violations = item.get('violation_list') or item.get('violations') or []
            deboost_txt = _('Có ⚠') if deboost_flag else _('Không ✓')
            lines = [
                _('Deboost: %s') % deboost_txt,
                _('Trạng thái: %s') % status,
            ]
            if violations:
                lines.append(_('Vi phạm (%d mục):') % len(violations))
                for v in violations[:5]:
                    vtype = v.get('violation_type', '')
                    action_txt = v.get('suggest_action', '')
                    lines.append('  • %s: %s' % (vtype, action_txt))
            else:
                lines.append(_('✓ Không có vi phạm cụ thể'))
            msg = '\n'.join(lines)
        self.write({'violation_summary': msg, 'quality_last_checked': fields.Datetime.now()})
        return self._store_raw_section('violation_info', result, _('Thông tin vi phạm'), msg)

    def _auto_refresh_quality_panels(self):
        """Best-effort refresh for form UX; never blocks opening the product."""
        for rec in self:
            if self.env.context.get('skip_shopee_auto_quality'):
                continue
            # Auto-tải nội dung (mô tả + ảnh + video) — chạy độc lập với throttle
            # 15 phút để người dùng luôn thấy nội dung mới nhất khi mở form lần đầu.
            if not rec.shopee_item_id:
                pass
            elif not rec.edit_description and not rec.image_line_ids and not rec.video_line_ids:
                try:
                    rec.with_context(skip_shopee_auto_quality=True).action_fetch_full_content()
                except Exception as e:
                    _logger.warning('Auto-fetch content failed for %s: %s', rec.id, e)
            # Tránh gọi API chẩn đoán/vi phạm liên tục khi web client read nhiều lần.
            if rec.quality_last_checked:
                age = fields.Datetime.now() - rec.quality_last_checked
                if age.total_seconds() < 15 * 60:
                    continue
            try:
                rec.with_context(skip_shopee_auto_quality=True).action_fetch_content_diagnosis()
            except Exception as e:
                rec.with_context(skip_shopee_auto_quality=True).write({
                    'quality_summary': _('Không tải được chẩn đoán: %s') % str(e),
                    'quality_last_checked': fields.Datetime.now(),
                })
            try:
                rec.with_context(skip_shopee_auto_quality=True).action_fetch_violation_info()
            except Exception as e:
                rec.with_context(skip_shopee_auto_quality=True).write({
                    'violation_summary': _('Không tải được vi phạm: %s') % str(e),
                })
            try:
                rec.with_context(skip_shopee_auto_quality=True).action_fetch_item_extra_info()
            except Exception as e:
                rec.with_context(skip_shopee_auto_quality=True).write({
                    'extra_summary': _('Không tải được thông tin thêm: %s') % str(e),
                })

    def web_read(self, specification):
        if not self.env.context.get('skip_shopee_auto_quality') and len(self) <= 3:
            self._auto_refresh_quality_panels()
        return super().web_read(specification)

    def action_fetch_size_chart_list(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_('Cần có category_id để lấy danh sách bảng kích thước.'))
        cat_id = self.category_id
        result = self._call_with_token_refresh(
            lambda creds: shopee_product_api.call_get_size_chart_list(creds, cat_id, page_size=20)
        )
        charts = result.get('size_chart', result.get('size_chart_list', []))
        count = len(charts) if isinstance(charts, list) else 0
        if count:
            names = ', '.join(c.get('title', '?') for c in charts[:5])
            msg = _('Tìm thấy %d bảng kích thước: %s') % (count, names)
        else:
            msg = _('Không có bảng kích thước cho danh mục này')
        return self._store_raw_section('size_chart_list', result, _('Bảng kích thước'), msg)

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


class ShopeeProductImage(models.Model):
    _name = 'shopee.product.image'
    _description = 'Ảnh sản phẩm Shopee'
    _order = 'shopee_product_id, sequence, id'

    shopee_product_id = fields.Many2one(
        'shopee.product', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(string='Dùng', default=True)
    image_id = fields.Char(string='Image ID Shopee', readonly=False)
    image_url = fields.Char(string='URL ảnh', readonly=True)
    upload_image = fields.Binary(string='Ảnh mới')
    upload_filename = fields.Char(string='Tên file')


class ShopeeProductVideo(models.Model):
    _name = 'shopee.product.video'
    _description = 'Video sản phẩm Shopee'
    _order = 'shopee_product_id, sequence, id'

    shopee_product_id = fields.Many2one(
        'shopee.product', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(string='Dùng', default=True)
    video_id = fields.Char(string='Video ID', readonly=True)
    video_upload_id = fields.Char(string='Video Upload ID')
    video_url = fields.Char(string='URL video', readonly=True)
    duration = fields.Integer(string='Thời lượng (giây)', readonly=True)
    upload_video = fields.Binary(string='Video mới')
    upload_filename = fields.Char(string='Tên file')


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
