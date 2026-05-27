import json
import logging

from odoo import api, fields, models

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
    shopee_model_id = fields.Integer('Model ID Shopee', index=True, readonly=True)
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
