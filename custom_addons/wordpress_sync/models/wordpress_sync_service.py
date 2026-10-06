# -*- coding: utf-8 -*-
"""
Logic đồng bộ giá và tình trạng kho lên một web WooCommerce.

Đích đẩy lấy từ bảng liên kết (wordpress.product.link), không tìm theo SKU mỗi lần.
"""
import logging
from collections import defaultdict

from .wordpress_api import BATCH_SIZE_LIMIT
from .wordpress_sync_utils import chunked

_logger = logging.getLogger(__name__)

# Giữ đúng câu chữ: no_retry_patterns mặc định của wordpress.config khớp theo chuỗi này.
NOT_FOUND_MESSAGE = 'Không tìm thấy product trên WordPress (SKU: {sku})'
NO_SKU_MESSAGE = 'Product không có SKU'


class _WebSyncService:
    """Phần chung: tìm sản phẩm web mà một sản phẩm Odoo trỏ tới, rồi đẩy payload lên."""

    def __init__(self, env, config):
        """
        Args:
            env: Odoo environment
            config: wordpress.config record — web cần đẩy
        """
        self.env = env
        self.config = config
        self.api = config._api_client()

    def _targets(self, product):
        """
        Các dòng liên kết của web này trỏ tới product.

        Web chưa quét lần nào thì chưa có bảng liên kết: tìm theo SKU như cách cũ và ghi
        lại kết quả, để không mất đồng bộ trong lúc chờ lượt quét đầu tiên.
        """
        Link = self.env['wordpress.product.link']
        links = Link.search([('config_id', '=', self.config.id), ('product_id', '=', product.id)])
        if links or self.config.link_scan_date:
            return links

        raw = self.api.find_product_by_sku(product.default_code)
        if not raw:
            return links
        return Link._record_web_products(self.config, [raw]).filtered(
            lambda link: link.product_id == product
        )

    def _push(self, links, payload):
        """
        Đẩy payload lên từng sản phẩm web.

        Returns:
            list: wc_product_id bị lỗi; rỗng nghĩa là tất cả thành công.
        """
        failed = []
        for link in links:
            response = self.api.update_product(
                link.wc_product_id,
                payload,
                is_variation=bool(link.wc_parent_id),
                parent_id=link.wc_parent_id or None,
            )
            if not response:
                failed.append(link.wc_product_id)
        return failed

    def _sync_one(self, product, payload, result, success_message):
        """
        Đẩy payload của một sản phẩm lên mọi sản phẩm web nó trỏ tới, điền result.

        Returns:
            dict: chính result, đã có success, message, wc_product_id.
        """
        if not product.default_code:
            result['message'] = NO_SKU_MESSAGE
            return result

        links = self._targets(product)
        if not links:
            result['message'] = NOT_FOUND_MESSAGE.format(sku=product.default_code)
            return result

        result['wc_product_id'] = ','.join(str(wc_id) for wc_id in links.mapped('wc_product_id'))
        failed = self._push(links, payload)
        if failed:
            result['message'] = f"Không thể cập nhật lên WordPress (ID lỗi: {', '.join(map(str, failed))})"
            return result

        result['success'] = True
        result['message'] = success_message
        self.api.purge_cache(self.config.cache_purge_url, product.default_code)
        return result


class PriceSyncService(_WebSyncService):
    """
    Service xử lý logic đồng bộ giá

    Usage:
        service = PriceSyncService(env, config)
        result = service.sync_product(product)
    """

    def _prices(self, product):
        """
        Giá đẩy lên web: (regular_price, sale_price).

        Ưu tiên giá nhập tay; combo (BOM phantom) chưa có giá web thì lấy giá combo tính từ BOM.
        """
        regular_price = getattr(product, 'x_studio_ga_hng_nim_yt', 0.0) or 0.0
        sale_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0

        has_bom = self.env['mrp.bom'].search_count([
            ('product_tmpl_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ]) > 0

        if has_bom and sale_price <= 0:
            combo_price = product.computed_combo_selling_price
            if combo_price > 0:
                sale_price = combo_price
                if regular_price <= 0:
                    regular_price = combo_price
        return regular_price, sale_price

    def _price_payload(self, regular_price, sale_price):
        """Sale price chỉ gửi khi > 0 và < regular; còn lại gửi '' để xoá sale trên web."""
        has_valid_sale = 0 < sale_price < regular_price
        return {
            'regular_price': str(regular_price),
            'sale_price': str(sale_price) if has_valid_sale else '',
        }

    def _price_message(self, regular_price, sale_price):
        if 0 < sale_price < regular_price:
            return f'Regular: {regular_price:,.0f}, Sale: {sale_price:,.0f}'
        return f'Regular: {regular_price:,.0f}'

    def sync_product(self, product):
        """
        Đồng bộ giá một product lên web này.

        Returns:
            dict: success, message, wc_product_id, sku, regular_price, sale_price
        """
        regular_price, sale_price = self._prices(product)
        result = {
            'success': False,
            'message': '',
            'wc_product_id': '',
            'sku': product.default_code or '',
            'regular_price': regular_price,
            'sale_price': sale_price,
        }

        if regular_price < 0:
            result['message'] = f'Giá regular không hợp lệ: {regular_price}'
            return result

        result = self._sync_one(
            product,
            self._price_payload(regular_price, sale_price),
            result,
            self._price_message(regular_price, sale_price),
        )
        if result['success']:
            _logger.info(f"Synced {product.name} (SKU: {product.default_code}) to {self.config.name}")
        return result

    def sync_products_batch(self, products):
        """
        Đồng bộ giá nhiều sản phẩm bằng Batch API, theo liên kết đã quét.

        Sản phẩm thường gửi /products/batch; biến thể gửi /products/<cha>/variations/batch.

        Returns:
            dict: {product_id: result dict như sync_product}
        """
        links_by_product = defaultdict(lambda: self.env['wordpress.product.link'])
        for link in self.env['wordpress.product.link'].search([
            ('config_id', '=', self.config.id),
            ('product_id', 'in', products.ids),
        ]):
            links_by_product[link.product_id.id] |= link

        results = {}
        items_by_parent = defaultdict(list)  # wc_parent_id (0 = sản phẩm thường) -> [(item, product_id)]
        for product in products:
            regular_price, sale_price = self._prices(product)
            links = links_by_product.get(product.id)
            result = {
                'success': False,
                'message': '',
                'sku': product.default_code or '',
                'wc_product_id': '',
                'regular_price': regular_price,
                'sale_price': sale_price,
            }
            results[product.id] = result

            if not product.default_code:
                result['message'] = NO_SKU_MESSAGE
                continue
            if not links:
                result['message'] = NOT_FOUND_MESSAGE.format(sku=product.default_code)
                continue

            result.update(success=True, message=self._price_message(regular_price, sale_price))
            result['wc_product_id'] = ','.join(str(wc_id) for wc_id in links.mapped('wc_product_id'))
            payload = self._price_payload(regular_price, sale_price)
            for link in links:
                items_by_parent[link.wc_parent_id].append((dict(payload, id=link.wc_product_id), product.id))

        for parent_id, entries in items_by_parent.items():
            for chunk in chunked(entries, BATCH_SIZE_LIMIT):
                items = [item for item, _product_id in chunk]
                if parent_id:
                    response = self.api.update_variations_batch(parent_id, items)
                else:
                    response = self.api.update_products_batch(items)
                for product_id, error in self._batch_errors(response, chunk).items():
                    results[product_id].update(success=False, message=error)

        return results

    def _batch_errors(self, response, chunk):
        """
        Đọc response Batch API, trả {product_id: lỗi} cho các item không cập nhật được.

        Batch trả 200 kể cả khi một vài item lỗi; item lỗi có khoá 'error'.
        """
        if not response or 'update' not in response:
            return {product_id: 'Batch request failed' for _item, product_id in chunk}

        updated = {item.get('id'): item for item in response['update']}
        errors = {}
        for item, product_id in chunk:
            item_resp = updated.get(item['id'])
            if item_resp is None:
                errors[product_id] = f"WordPress không trả kết quả cho ID {item['id']}"
            elif 'error' in item_resp:
                errors[product_id] = str(item_resp['error'])
        return errors


class StockSyncService(_WebSyncService):
    """
    Service xử lý logic đồng bộ tình trạng kho

    Usage:
        service = StockSyncService(env, config)
        result = service.sync_stock_status(product)
    """

    # Stock status mapping
    STOCK_STATUS_MAP = {
        'in_stock': 'instock',
        'out_of_stock': 'outofstock'
    }

    def _get_stock_field(self):
        """Get configured stock field name from wordpress.config"""
        return self.config.stock_status_field or 'qty_available'

    def _is_in_stock(self, product):
        """
        Kiểm tra sản phẩm còn hàng không dựa trên field được cấu hình
        Priority: Manual Override (x_wp_stock_status) > Computed Qty
        """
        # 0. Invalidate cache to ensure fresh data from DB (in case of race/cache issues)
        product.invalidate_recordset(['x_wp_stock_status'])

        # 1. Manual Override
        manual_status = getattr(product, 'x_wp_stock_status', False)

        _logger.info(f"[WP-STOCK-DEBUG] {product.name} (ID: {product.id}) | Manual Override: '{manual_status}'")

        if manual_status:
            if manual_status == 'instock':
                _logger.info(f"[WP-STOCK-DEBUG] {product.name} -> RETURNING INSTOCK (Manual)")
                return True
            if manual_status in ('outofstock', 'discontinued'):
                _logger.info(f"[WP-STOCK-DEBUG] {product.name} -> RETURNING OUTOFSTOCK (Manual)")
                return False

        # 2. Check Phantom BOM (Recursive)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)

        if bom:
            # If ANY component is OOS, the Kit is OOS
            for line in bom.bom_line_ids:
                child = line.product_id.product_tmpl_id
                if not self._is_in_stock(child):
                    _logger.info(f"Checking stock for {product.name}: Component {child.name} is OOS. Kit is OOS.")
                    return False
            # All components in stock -> Kit is in stock
            _logger.info(f"Checking stock for {product.name}: All components in stock. Kit is In Stock.")
            return True

        # 3. Check Configuration: Sync based on Qty?
        if not self.config.sync_stock_based_on_quantity:
            # If Config says "Don't sync based on quantity" -> We assume In Stock (unless Manual Override was OOS)
            _logger.info(f"Checking stock for {product.name}: Sync based on Qty is OFF -> Returning In Stock.")
            return True

        # 4. Computed from Quantity (Standard)
        stock_field = self._get_stock_field()

        # For product.template, we need to check all variants
        # Get total qty from all product variants
        total_qty = 0
        for variant in product.product_variant_ids:
            qty = getattr(variant, stock_field, 0) or 0
            total_qty += qty

        return total_qty > 0

    def sync_stock_status(self, product):
        """
        Đồng bộ tình trạng kho một product lên web này.

        Returns:
            dict: success, message, wc_product_id, sku, stock_status
        """
        is_in_stock = self._is_in_stock(product)
        stock_status = self.STOCK_STATUS_MAP['in_stock'] if is_in_stock else self.STOCK_STATUS_MAP['out_of_stock']
        result = {
            'success': False,
            'message': '',
            'wc_product_id': '',
            'sku': product.default_code or '',
            'stock_status': stock_status,
        }

        status_text = 'Còn hàng' if is_in_stock else 'Hết hàng'
        result = self._sync_one(
            product,
            {'stock_status': stock_status},
            result,
            f'Stock status: {status_text} → {stock_status}',
        )
        if result['success']:
            _logger.info(f"Synced stock status for {product.name} (SKU: {product.default_code}) → {stock_status}")
        return result
