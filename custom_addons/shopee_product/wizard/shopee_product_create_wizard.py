# -*- coding: utf-8 -*-
"""
wizard/shopee_product_create_wizard.py

Wizard tạo sản phẩm mới trên Shopee từ sản phẩm Odoo (product.template).

Luồng:
1. Mở wizard (từ Actions trên product.template)
2. Chọn cửa hàng Shopee — các thông tin cơ bản được tự động điền
3. Nhập category_id Shopee và logistic IDs (bắt buộc)
4. Nhấn "Tạo sản phẩm Shopee" → API call_add_item → tạo shopee.product
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
    category_id = fields.Integer(
        string='Category ID Shopee',
        required=True,
        help='ID danh mục Shopee. Tìm bằng nút "Gợi ý danh mục" trên shopee.product.',
    )
    logistic_ids_text = fields.Text(
        string='Logistic IDs',
        placeholder='40013\n40014',
        help=(
            'Mỗi dòng một Logistic ID (số nguyên).\n'
            'Tìm trong Shopee Seller Center → Cài đặt → Vận chuyển.\n'
            'Hoặc dùng nút "Xem logistics" ở dưới.'
        ),
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

    def action_create_shopee_product(self):
        self.ensure_one()

        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(self.shop_id)

        # 1. Upload ảnh ──────────────────────────────────────────────────
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

        # 2. Parse logistics ─────────────────────────────────────────────
        logistics = []
        if self.logistic_ids_text:
            for line in self.logistic_ids_text.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    logistics.append({'logistic_id': int(line), 'enabled': True})

        if not logistics:
            raise UserError(_(
                'Vui lòng nhập ít nhất một Logistic ID.\n'
                'Tìm trong Shopee Seller Center → Cài đặt → Vận chuyển.'
            ))

        # 3. Build payload ───────────────────────────────────────────────
        item_data = {
            'item_name': self.item_name,
            'description': self.description or self.item_name,
            'item_sku': self.item_sku or '',
            'category_id': self.category_id,
            'original_price': self.original_price,
            'weight': self.weight,
            'image': {'image_id_list': image_id_list},
            'logistics': logistics,
            'stock_info_v2': {
                'seller_stock': [{'stock': self.initial_stock}],
            },
        }

        # 4. Gọi add_item ────────────────────────────────────────────────
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
            'total_available_stock': self.initial_stock,
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
