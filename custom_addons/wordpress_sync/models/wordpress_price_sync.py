from odoo import models, fields, api, _
from requests.auth import HTTPBasicAuth
import requests
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class WordPressPriceSync(models.TransientModel):
    _name = 'wordpress.price.sync'
    _description = 'WordPress Price Sync Wizard'

    sync_mode = fields.Selection(
        [
            ('single', 'Single Product'),
            ('all', 'All Products'),
        ],
        string='Sync Mode',
        default='single',
        required=True
    )

    product_id = fields.Many2one(
        'product.template',
        string='Product',
        help='Select product to sync'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='WordPress Config',
        required=True,
        help='Select WordPress store configuration'
    )

    def action_sync(self):
        """Main action button - sync prices to WordPress"""
        if not self.wordpress_config_id:
            raise ValueError('⚠️ Please select WordPress configuration')

        if self.sync_mode == 'single':
            if not self.product_id:
                raise ValueError('⚠️ Please select a product to sync')
            result = self._sync_single_product(self.product_id)
        else:  # all
            result = self._sync_all_products()

        return result

    def _sync_single_product(self, product):
        """Sync a single product"""
        config = self.wordpress_config_id

        try:
            # Get product data
            sku = product.default_code or ''
            if not sku:
                _logger.warning(f"⚠️ Product {product.name} has no SKU")
                self._log_sync(product, 'skipped', f'No SKU found', sku=sku)
                return self._show_notification('⏭️ Skipped', f'Product has no SKU', 'warning')

            # Get prices from Odoo
            regular_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
            sale_price = getattr(product, 'x_studio_gi_bn_thng_mi', 0.0) or 0.0

            if regular_price <= 0:
                _logger.warning(f"⚠️ Product {product.name} (SKU: {sku}) has invalid regular price: {regular_price}")
                self._log_sync(
                    product,
                    'skipped',
                    f'Invalid regular price: {regular_price}',
                    sku=sku,
                    new_regular_price=regular_price
                )
                return self._show_notification('⏭️ Skipped', 'Product has invalid regular price', 'warning')

            # Normalize sale price: must be less than regular price and > 0
            has_valid_sale = sale_price > 0 and sale_price < regular_price
            sale_price_final = sale_price if has_valid_sale else 0.0

            _logger.info(f"🔍 Syncing product {product.name} (SKU: {sku}) → regular: {regular_price}, sale: {sale_price_final}")

            # Find product on WordPress by SKU
            wc_product = self._find_wc_product(config, sku)
            if not wc_product:
                msg = f'Product not found on WordPress (SKU: {sku})'
                _logger.warning(f"⚠️ {msg}")
                self._log_sync(product, 'failed', msg, sku=sku)
                return self._show_notification('❌ Not Found', msg, 'danger')

            # Prepare payload
            is_variation = wc_product.get('type') == 'variation'
            wc_id = wc_product.get('id')
            parent_id = wc_product.get('parent_id', 0) if is_variation else wc_id

            payload = {
                'regular_price': str(regular_price),
            }

            # Add sale price if valid
            if has_valid_sale:
                payload['sale_price'] = str(sale_price)
            else:
                # Clear sale price on WordPress if not valid
                payload['sale_price'] = ''

            # Sync to WordPress
            put_path = f"/products/{parent_id}/variations/{wc_id}" if is_variation else f"/products/{wc_id}"

            response = self._wc_put(config, put_path, payload)

            if response:
                _logger.info(f"✅ Successfully synced {product.name} (SKU: {sku})")

                # Purge cache
                self._purge_cache(config, sku)

                # Get old prices for log
                old_regular = getattr(product, '_old_regular_price', regular_price)
                old_sale = getattr(product, '_old_sale_price', sale_price)

                # Log successful sync
                self._log_sync(
                    product,
                    'success',
                    f'Regular: {regular_price}, Sale: {sale_price_final if has_valid_sale else "None"}',
                    sku=sku,
                    wc_id=wc_id,
                    old_regular_price=old_regular,
                    new_regular_price=regular_price,
                    old_sale_price=old_sale,
                    new_sale_price=sale_price if has_valid_sale else 0.0
                )

                msg = f'Product {product.name} synced successfully'
                return self._show_notification('✅ Success', msg, 'success')
            else:
                msg = f'Failed to sync to WordPress'
                _logger.error(f"❌ {msg} for {product.name} (SKU: {sku})")
                self._log_sync(product, 'failed', msg, sku=sku)
                return self._show_notification('❌ Failed', msg, 'danger')

        except Exception as e:
            _logger.exception(f"❌ Error syncing {product.name}: {str(e)}")
            self._log_sync(product, 'failed', f'Exception: {str(e)}')
            return self._show_notification('❌ Error', str(e), 'danger')

    def _sync_all_products(self):
        """Sync all products"""
        products = self.env['product.template'].search([
            ('active', '=', True),
            ('default_code', '!=', False),
            ('default_code', '!=', '')
        ])

        if not products:
            return self._show_notification('⏭️ No Products', 'No active products with SKU found', 'warning')

        synced = 0
        failed = 0
        skipped = 0

        for product in products:
            try:
                # Get prices
                regular_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
                sale_price = getattr(product, 'x_studio_gi_bn_thng_mi', 0.0) or 0.0
                sku = product.default_code or ''

                if regular_price <= 0:
                    skipped += 1
                    self._log_sync(product, 'skipped', f'Invalid price: {regular_price}', sku=sku)
                    continue

                # Find product
                wc_product = self._find_wc_product(self.wordpress_config_id, sku)
                if not wc_product:
                    failed += 1
                    self._log_sync(product, 'failed', f'Not found on WordPress', sku=sku)
                    continue

                # Prepare payload
                is_variation = wc_product.get('type') == 'variation'
                wc_id = wc_product.get('id')
                parent_id = wc_product.get('parent_id', 0) if is_variation else wc_id

                payload = {'regular_price': str(regular_price)}

                has_valid_sale = sale_price > 0 and sale_price < regular_price
                if has_valid_sale:
                    payload['sale_price'] = str(sale_price)
                else:
                    payload['sale_price'] = ''

                # Sync
                put_path = f"/products/{parent_id}/variations/{wc_id}" if is_variation else f"/products/{wc_id}"
                response = self._wc_put(self.wordpress_config_id, put_path, payload)

                if response:
                    synced += 1
                    self._purge_cache(self.wordpress_config_id, sku)
                    self._log_sync(
                        product,
                        'success',
                        f'Regular: {regular_price}, Sale: {sale_price if has_valid_sale else "None"}',
                        sku=sku,
                        wc_id=wc_id,
                        new_regular_price=regular_price,
                        new_sale_price=sale_price if has_valid_sale else 0.0
                    )
                else:
                    failed += 1
                    self._log_sync(product, 'failed', 'Failed to sync', sku=sku)

            except Exception as e:
                failed += 1
                _logger.exception(f"Error syncing {product.name}: {str(e)}")
                self._log_sync(product, 'failed', f'Exception: {str(e)}')

        msg = f'Synced: {synced} ✅, Failed: {failed} ❌, Skipped: {skipped} ⏭️'
        _logger.info(f"📊 Sync complete: {msg}")

        return self._show_notification('📊 Sync Complete', msg, 'success')

    def _find_wc_product(self, config, sku):
        """Find product on WordPress by SKU"""
        try:
            url = f"{config.wc_domain}/wp-json/wc/v3/products?sku={sku}&per_page=100"
            response = self._wc_get(config, url)

            if response and len(response) > 0:
                return response[0]

            # SKU not found
            return None
        except Exception as e:
            _logger.error(f"Error finding WC product with SKU {sku}: {str(e)}")
            return None

    def _wc_get(self, config, url):
        """GET request to WordPress API"""
        try:
            auth = HTTPBasicAuth(config.wc_key, config.wc_secret)
            response = requests.get(url, auth=auth, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                _logger.error(f"WC API error {response.status_code}: {response.text[:200]}")
                return None
        except Exception as e:
            _logger.error(f"Error calling WC API: {str(e)}")
            return None

    def _wc_put(self, config, path, payload, retries=3):
        """PUT request to WordPress API with retries"""
        url = f"{config.wc_domain}/wp-json/wc/v3{path}"

        for attempt in range(retries):
            try:
                auth = HTTPBasicAuth(config.wc_key, config.wc_secret)
                response = requests.put(
                    url,
                    json=payload,
                    auth=auth,
                    timeout=10
                )

                if response.status_code in (200, 201):
                    return response.json()
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    _logger.warning(f"⚠️ Attempt {attempt + 1}: {error_msg}")

                    if attempt < retries - 1:
                        import time
                        time.sleep(1 * (attempt + 1))
                    else:
                        _logger.error(f"❌ Failed after {retries} attempts: {error_msg}")
                        return None

            except Exception as e:
                _logger.warning(f"⚠️ Attempt {attempt + 1} error: {str(e)}")

                if attempt < retries - 1:
                    import time
                    time.sleep(1 * (attempt + 1))
                else:
                    _logger.error(f"❌ Failed after {retries} attempts: {str(e)}")
                    return None

        return None

    def _purge_cache(self, config, sku):
        """Purge LiteSpeed cache for product"""
        try:
            if not config.cache_purge_url:
                return

            url = f"{config.wc_domain}{config.cache_purge_url}{sku}"
            requests.get(url, timeout=5)
            _logger.info(f"🧹 Cache purged for SKU: {sku}")
        except Exception as e:
            _logger.warning(f"⚠️ Cache purge failed for {sku}: {str(e)}")

    def _log_sync(self, product, status, message, sku='', wc_id='', wc_var_id='',
                  old_regular_price=0, new_regular_price=0, old_sale_price=0, new_sale_price=0):
        """Log sync operation"""
        try:
            self.env['product.sync.log'].create({
                'product_id': product.id,
                'sku': sku,
                'sync_type': 'manual',
                'status': status,
                'message': message,
                'wc_product_id': wc_id,
                'wc_variation_id': wc_var_id,
                'old_regular_price': old_regular_price,
                'new_regular_price': new_regular_price,
                'old_sale_price': old_sale_price,
                'new_sale_price': new_sale_price,
                'changed_by_id': self.env.user.id,
            })

            # Clean old logs
            self.env['product.sync.log']._clean_old_logs()
        except Exception as e:
            _logger.warning(f"⚠️ Error creating sync log: {str(e)}")

    def _show_notification(self, title, message, notif_type='success'):
        """Show notification to user"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }


# ===================== EXTEND ProductTemplate with auto-sync =====================
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def write(self, vals):
        """Override write to auto-sync when prices change"""
        # Check if price fields are being updated
        price_fields = ['x_studio_ga_web', 'x_studio_gi_bn_thng_mi']
        has_price_change = any(field in vals for field in price_fields)

        result = super().write(vals)

        if has_price_change and not self.env.context.get('skip_wordpress_sync'):
            # Auto-sync to WordPress
            self._auto_sync_to_wordpress()

        return result

    def _auto_sync_to_wordpress(self):
        """Automatically sync prices to WordPress when changed"""
        config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)
        if not config:
            _logger.warning("⚠️ No active WordPress configuration found")
            return

        for product in self:
            try:
                sku = product.default_code or ''
                if not sku:
                    continue

                regular_price = getattr(product, 'x_studio_ga_web', 0.0) or 0.0
                sale_price = getattr(product, 'x_studio_gi_bn_thng_mi', 0.0) or 0.0

                if regular_price <= 0:
                    _logger.warning(f"⚠️ Invalid price for {product.name}")
                    continue

                # Find product on WordPress
                from requests.auth import HTTPBasicAuth
                import requests

                url = f"{config.wc_domain}/wp-json/wc/v3/products?sku={sku}&per_page=100"
                auth = HTTPBasicAuth(config.wc_key, config.wc_secret)
                response = requests.get(url, auth=auth, timeout=10)

                if response.status_code != 200 or not response.json():
                    _logger.warning(f"Product {product.name} (SKU: {sku}) not found on WordPress")
                    continue

                wc_product = response.json()[0]
                is_variation = wc_product.get('type') == 'variation'
                wc_id = wc_product.get('id')
                parent_id = wc_product.get('parent_id', 0) if is_variation else wc_id

                # Prepare payload
                payload = {'regular_price': str(regular_price)}
                has_valid_sale = sale_price > 0 and sale_price < regular_price
                if has_valid_sale:
                    payload['sale_price'] = str(sale_price)
                else:
                    payload['sale_price'] = ''

                # Sync
                put_path = f"/products/{parent_id}/variations/{wc_id}" if is_variation else f"/products/{wc_id}"
                put_url = f"{config.wc_domain}/wp-json/wc/v3{put_path}"

                put_response = requests.put(
                    put_url,
                    json=payload,
                    auth=auth,
                    timeout=10
                )

                if put_response.status_code in (200, 201):
                    _logger.info(f"✅ Auto-synced {product.name} (SKU: {sku}) to WordPress")

                    # Create internal note
                    product.message_post(
                        body=f'<p><strong>🔄 WordPress Sync:</strong><br/>'
                        f'Regular Price: {regular_price}<br/>'
                        f'Sale Price: {sale_price if has_valid_sale else "None"}<br/>'
                        f'Synced by: {self.env.user.name}<br/>'
                        f'Date: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}'
                        f'</p>',
                        message_type='comment',
                        subtype='mail.mt_note'
                    )

                    # Log
                    self.env['product.sync.log'].create({
                        'product_id': product.id,
                        'sku': sku,
                        'sync_type': 'auto',
                        'status': 'success',
                        'message': f'Auto-synced: Regular={regular_price}, Sale={sale_price if has_valid_sale else "None"}',
                        'wc_product_id': str(wc_id),
                        'new_regular_price': regular_price,
                        'new_sale_price': sale_price if has_valid_sale else 0.0,
                        'changed_by_id': self.env.user.id,
                    })

                    # Purge cache
                    if config.cache_purge_url:
                        cache_url = f"{config.wc_domain}{config.cache_purge_url}{sku}"
                        requests.get(cache_url, timeout=5)

                else:
                    _logger.error(f"❌ Failed to auto-sync {product.name}: {put_response.text[:200]}")

            except Exception as e:
                _logger.warning(f"⚠️ Auto-sync error for {product.name}: {str(e)}")

    def action_sync_to_wordpress(self):
        """Button action to manually sync single product"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wordpress.price.sync',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sync_mode': 'single', 'default_product_id': self.id}
        }
