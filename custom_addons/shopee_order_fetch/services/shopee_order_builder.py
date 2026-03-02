# -*- coding: utf-8 -*-
"""
services/shopee_order_builder.py

Tạo Sale Order và các records liên quan (partner, địa chỉ giao hàng, sản phẩm, order line)
từ dữ liệu Shopee API. Tất cả logic tạo dữ liệu được tập trung ở đây.
"""
import logging

from . import shopee_escrow

_logger = logging.getLogger(__name__)

# Mã kho TSN mặc định
DEFAULT_WAREHOUSE_CODE = 'TSN'


def find_or_create_partner(env, order_data):
    """
    Tìm hoặc tạo res.partner từ buyer_username.
    Tạo thêm địa chỉ giao hàng (type=delivery) từ recipient_address.

    :return: (partner, delivery_address) — delivery_address có thể là False
    """
    Partner = env['res.partner'].sudo()

    buyer_username = order_data.get('buyer_username', '') or 'Khách Shopee'
    addr = order_data.get('recipient_address', {}) or {}

    partner = Partner.search([('name', '=', buyer_username)], limit=1)
    if not partner:
        partner = Partner.create({
            'name': buyer_username,
            'customer_rank': 1,
        })
        _logger.info("Shopee: Đã tạo liên hệ '%s' (ID: %s)", partner.name, partner.id)

    delivery_address = find_or_create_delivery_address(env, partner, addr)
    return partner, delivery_address


def find_or_create_delivery_address(env, parent_partner, addr):
    """
    Tạo địa chỉ giao hàng (type=delivery) dưới partner chính.
    Bỏ qua nếu tất cả field đều bị mask (****).

    :return: res.partner record hoặc False
    """
    if not addr:
        return False

    Partner = env['res.partner'].sudo()

    recipient_name = addr.get('name', '')
    phone = addr.get('phone', '')
    full_address = addr.get('full_address', '')

    if all(v in ('', '****') for v in [recipient_name, phone, full_address]):
        return False

    # Tìm delivery address đã có
    domain = [
        ('parent_id', '=', parent_partner.id),
        ('type', '=', 'delivery'),
    ]
    if phone and phone != '****':
        domain.append(('phone', '=', phone))
    existing = Partner.search(domain, limit=1)
    if existing:
        return existing

    delivery_vals = {
        'parent_id': parent_partner.id,
        'type': 'delivery',
        'name': recipient_name if recipient_name and recipient_name != '****' else parent_partner.name,
    }
    if phone and phone != '****':
        delivery_vals['phone'] = phone
    if full_address and full_address != '****':
        delivery_vals['street'] = full_address
    if addr.get('city') and addr['city'] != '****':
        delivery_vals['city'] = addr['city']
    if addr.get('district') and addr['district'] != '****':
        delivery_vals['street2'] = addr['district']
    if addr.get('state') and addr['state'] != '****':
        delivery_vals['city'] = (delivery_vals.get('city', '') + ', ' + addr['state']).strip(', ')

    delivery = Partner.create(delivery_vals)
    _logger.info(
        "Shopee: Đã tạo địa chỉ giao hàng cho '%s' (ID: %s)",
        parent_partner.name, delivery.id,
    )
    return delivery


def find_or_create_shopee_item(env, item_data, shop):
    """
    Tìm hoặc tạo shopee.item từ item_data; trả về product.product.

    Thứ tự tìm kiếm:
    1. shopee.item theo item_id + model_id
    2. product.product theo model_sku (default_code)
    3. product.product theo tên sản phẩm
    4. Tạo product mới nếu không tìm thấy
    """
    ShopeeItem = env['shopee.item'].sudo()

    item_id = item_data.get('item_id', 0)
    model_id = item_data.get('model_id', 0)
    item_name = item_data.get('item_name', '')
    model_sku = item_data.get('model_sku', '')

    # 1. Tìm theo shopee.item identifier
    domain = [('shopee_item_identifier', '=', item_id)]
    if model_id:
        domain.append(('shopee_model_identifier', '=', model_id))
    existing_item = ShopeeItem.search(domain, limit=1)
    if existing_item and existing_item.product_id:
        return existing_item.product_id

    # 2. Tìm theo SKU (default_code)
    product = False
    if model_sku:
        product = env['product.product'].sudo().search(
            [('default_code', '=', model_sku)], limit=1
        )

    # 3. Tìm theo tên
    if not product and item_name:
        product = env['product.product'].sudo().search(
            [('name', '=', item_name)], limit=1
        )

    # 4. Tạo mới
    if not product:
        product = env['product.product'].sudo().create({
            'name': item_name or f"Shopee Item {item_id}",
            'default_code': model_sku or '',
            'type': 'consu',
            'sale_ok': True,
        })
        _logger.info("Shopee: Đã tạo sản phẩm '%s' (SKU: %s)", product.name, model_sku)

    # 5. Tạo shopee.item record nếu chưa tồn tại
    if not existing_item and shop:
        shopee_item_vals = {
            'shopee_item_identifier': item_id,
            'product_id': product.id,
            'shop_id': shop.id,
        }
        if model_id:
            shopee_item_vals['shopee_model_identifier'] = model_id
        ShopeeItem.create(shopee_item_vals)
        _logger.info(
            "Shopee: Đã tạo shopee.item (item_id=%s, model_id=%s) → product=%s",
            item_id, model_id, product.name,
        )

    return product


def create_order_line(env, so, item_data, shop):
    """
    Tạo sale.order.line từ 1 item trong Shopee response.
    Giá và chiết khấu lấy từ model_original_price / model_discounted_price.
    """
    product = find_or_create_shopee_item(env, item_data, shop)

    qty = item_data.get('model_quantity_purchased', 1)
    original_price = item_data.get('model_original_price', 0)
    discounted_price = item_data.get('model_discounted_price', 0)

    discount = 0.0
    if original_price > 0 and discounted_price is not None:
        discount = (original_price - discounted_price) / original_price * 100

    line_vals = {
        'order_id': so.id,
        'product_id': product.id,
        'name': product.name,
        'product_uom_qty': qty,
        'price_unit': original_price,
        'discount': discount,
    }

    tax_included = shopee_escrow.get_tax_included(env, so.company_id)
    if tax_included:
        line_vals['tax_id'] = [(6, 0, tax_included.ids)]

    return env['sale.order.line'].sudo().create(line_vals)


def create_order_from_data(env, order_data, shop, escrow_data=None):
    """
    Tạo đầy đủ sale.order từ 1 order trong Shopee API response.

    Steps:
    1. Tạo / tìm partner + địa chỉ giao hàng
    2. Tìm kho TSN mặc định
    3. Tạo sale.order
    4. Tạo sale.order.line từ item_list
    5. Áp dụng shopee voucher từ escrow (nếu có)
    6. Xác nhận đơn hàng

    :param env: Odoo env
    :param order_data: dict một order từ Shopee get_order_detail response
    :param shop: shopee.shop record (hoặc False)
    :param escrow_data: dict response từ Shopee get_escrow_detail (hoặc None)
    :return: sale.order record vừa tạo
    """
    partner, delivery_address = find_or_create_partner(env, order_data)

    warehouse = env['stock.warehouse'].sudo().search(
        [('code', '=', DEFAULT_WAREHOUSE_CODE)], limit=1
    )

    so_vals = {
        'partner_id': partner.id,
        'shopee_order_ref': order_data.get('order_sn', ''),
        'shopee_order_status': order_data.get('order_status', ''),
    }
    if delivery_address:
        so_vals['partner_shipping_id'] = delivery_address.id
    if shop:
        so_vals['shopee_shop_id'] = shop.id
    if warehouse:
        so_vals['warehouse_id'] = warehouse.id

    so = env['sale.order'].sudo().create(so_vals)

    for item_data in order_data.get('item_list', []):
        create_order_line(env, so, item_data, shop)

    if escrow_data:
        shopee_escrow.apply_escrow_voucher(so, escrow_data)

    try:
        so.sudo().action_confirm()
        _logger.info("Shopee: Đã xác nhận đơn hàng %s → picking đã tạo", so.name)
    except Exception as e:
        _logger.warning("Shopee: Không thể xác nhận đơn %s: %s", so.name, str(e))

    _logger.info("Shopee: Đã tạo đơn hàng %s từ order_sn=%s", so.name, order_data.get('order_sn'))
    return so
