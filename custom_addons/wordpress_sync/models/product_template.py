# -*- coding: utf-8 -*-
from odoo import models, fields, api
from .wordpress_api import PriceSyncService, StockSyncService
from datetime import datetime
import logging


_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """
    Extension cho product.template để hỗ trợ auto-sync giá và stock lên WordPress
    """
    _inherit = 'product.template'

    # ===========================================
    # ===========================================
    # NEW FIELDS
    # ===========================================
    # Define Studio fields explicitly to avoid view errors if Studio not loaded yet/module isolation
    x_studio_ga_web = fields.Monetary(string="Giá Web")
    x_studio_ga_hng_nim_yt = fields.Monetary(string="Giá Niêm Yết")
    x_studio_gia_san_tmdt = fields.Monetary(string="Giá Sàn TMĐT")
    x_studio_gi_bn_thng_mi = fields.Monetary(string="Giá Thương Mại")

    x_wp_stock_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh')
    ], string='Tình trạng WP', 
       help='Tình trạng kho trên WordPress (ghi đè tự động)')

    x_wp_combo_price = fields.Float(
        string='Giá bán trong combo',
        default=0.0,
        help='Giá sử dụng khi tính giá combo (nếu = 0, sử dụng giá bán thường)'
    )

    computed_combo_selling_price = fields.Float(
        string='Giá combo tính toán',
        compute='_compute_combo_selling_price',
        store=True,
        help='Giá bán combo được tính tự động từ BOM'
    )

    # ===========================================
    # COMPUTED METHODS
    # ===========================================
    @api.depends(
        'bom_ids',
        'bom_ids.type',
        'bom_ids.active',
        'bom_ids.bom_line_ids',
        'bom_ids.bom_line_ids.product_qty',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.list_price',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.x_studio_ga_web',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.x_studio_ga_hng_nim_yt',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.x_studio_gia_san_tmdt',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.x_studio_gi_bn_thng_mi',
        'bom_ids.bom_line_ids.product_id.product_tmpl_id.x_wp_combo_price',
    )
    def _compute_combo_selling_price(self):
        """Tính giá combo dựa trên BOM và phương pháp được cấu hình"""
        # Get settings from wordpress.config
        config = self._get_wordpress_config()
        if config:
            pricing_method = config.combo_pricing_method or 'sum_combo_price'
            discount_pct = config.combo_discount_percentage or 0.0
        else:
            pricing_method = 'sum_combo_price'
            discount_pct = 0.0

        for product in self:
            combo_price, listed_price, tmdt_price, thuongmai_price, retail_price, zalo_price = product._calculate_combo_price_values(
                pricing_method, discount_pct
            )
            product.computed_combo_selling_price = combo_price

            # Auto-update Odoo price fields if calculated
            # Update x_studio_ga_web, x_studio_ga_hng_nim_yt, x_studio_gia_san_tmdt,
            # x_studio_gi_bn_thng_mi, list_price và x_zalo_price từ BOM (cùng một cơ chế)
            vals = {}
            if combo_price > 0 and 'x_studio_ga_web' in product._fields:
                 vals['x_studio_ga_web'] = combo_price

            if listed_price > 0 and 'x_studio_ga_hng_nim_yt' in product._fields:
                 vals['x_studio_ga_hng_nim_yt'] = listed_price

            if tmdt_price > 0 and 'x_studio_gia_san_tmdt' in product._fields:
                 vals['x_studio_gia_san_tmdt'] = tmdt_price

            if thuongmai_price > 0 and 'x_studio_gi_bn_thng_mi' in product._fields:
                 vals['x_studio_gi_bn_thng_mi'] = thuongmai_price

            if retail_price > 0:
                 vals['list_price'] = retail_price

            if zalo_price > 0 and 'x_zalo_price' in product._fields:
                 vals['x_zalo_price'] = zalo_price

            if vals:
                # Use write to update fields safely
                product.write(vals)

    def _calculate_combo_price(self, pricing_method='sum_combo_price', discount_pct=0.0):
        """Deprecated: Use _calculate_combo_price_values instead"""
        price = self._calculate_combo_price_values(pricing_method, discount_pct)[0]
        return price

    def _calculate_combo_price_values(self, pricing_method='sum_combo_price', discount_pct=0.0):
        """
        Tính giá combo (bán, niêm yết, sàn TMĐT, thương mại, bán lẻ, Zalo) dựa trên BOM

        Returns:
            tuple: (selling_price, listed_price, tmdt_price, thuongmai_price, retail_price, zalo_price)
        """
        self.ensure_one()

        # Find active BOM for this product (phantom/kit type)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', self.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)

        if not bom:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        total_selling_price = 0.0
        total_listed_price = 0.0
        total_tmdt_price = 0.0
        total_thuongmai_price = 0.0
        total_retail_price = 0.0
        total_zalo_price = 0.0

        for line in bom.bom_line_ids:
            child_product = line.product_id.product_tmpl_id
            qty = line.product_qty or 1.0

            # Tính giá listed (luôn là tổng listed con)
            child_listed = getattr(child_product, 'x_studio_ga_hng_nim_yt', 0) or child_product.list_price or 0.0
            total_listed_price += child_listed * qty

            # Giá sàn TMĐT (tổng của các con, cùng cơ chế với giá niêm yết)
            child_tmdt = getattr(child_product, 'x_studio_gia_san_tmdt', 0) or 0.0
            total_tmdt_price += child_tmdt * qty

            # Giá thương mại (tổng của các con, cùng cơ chế với giá niêm yết)
            child_thuongmai = getattr(child_product, 'x_studio_gi_bn_thng_mi', 0) or 0.0
            total_thuongmai_price += child_thuongmai * qty

            # Giá bán lẻ (list_price) - tổng list_price con, cùng cơ chế với giá niêm yết
            total_retail_price += (child_product.list_price or 0.0) * qty

            # Giá Zalo Mini App - tổng x_zalo_price con, cùng cơ chế với giá niêm yết
            child_zalo = getattr(child_product, 'x_zalo_price', 0) or 0.0
            total_zalo_price += child_zalo * qty

            if pricing_method == 'sum_combo_price':
                # Lấy x_wp_combo_price, nếu = 0 thì lấy giá bán thường
                combo_price = child_product.x_wp_combo_price or 0.0
                if combo_price <= 0:
                    # Fallback to regular price (x_studio_ga_web or list_price)
                    combo_price = getattr(child_product, 'x_studio_ga_web', 0) or child_product.list_price or 0.0
                total_selling_price += combo_price * qty
            else:
                # discount_percentage method
                regular_price = getattr(child_product, 'x_studio_ga_web', 0) or child_product.list_price or 0.0
                total_selling_price += regular_price * qty

        # Apply discount if using discount_percentage method
        if pricing_method == 'discount_percentage' and discount_pct > 0:
            total_selling_price = total_selling_price * (1 - discount_pct / 100)
            total_tmdt_price = total_tmdt_price * (1 - discount_pct / 100)
            total_thuongmai_price = total_thuongmai_price * (1 - discount_pct / 100)
            total_retail_price = total_retail_price * (1 - discount_pct / 100)
            total_zalo_price = total_zalo_price * (1 - discount_pct / 100)

        return total_selling_price, total_listed_price, total_tmdt_price, total_thuongmai_price, total_retail_price, total_zalo_price

    # ===========================================
    # OVERRIDE METHODS
    # ===========================================
    def write(self, vals):
        """Override write để auto-sync khi giá thay đổi và cập nhật combo cha"""
        # Các field giá cần theo dõi
        price_fields = [
            'x_studio_ga_web',
            'x_studio_gi_bn_thng_mi',
            'x_studio_gia_san_tmdt',
            'x_wp_combo_price',
            'list_price',
            'x_studio_ga_hng_nim_yt',
            'x_zalo_price',
        ]
        has_price_change = any(field in vals for field in price_fields)
        changed_price_fields = [field for field in price_fields if field in vals]
        old_price_values = {}
        if has_price_change:
            for product in self:
                old_price_values[product.id] = {
                    field: product[field]
                    for field in changed_price_fields
                    if field in product._fields
                }
        old_stock_values = {}
        if 'x_wp_stock_status' in vals:
            old_stock_values = {
                product.id: product.x_wp_stock_status
                for product in self
            }

        result = super().write(vals)
        price_queue_values = (
            self._get_price_queue_values(changed_price_fields, old_price_values)
            if has_price_change
            else {}
        )
        stock_queue_values = (
            self._get_stock_queue_values(old_stock_values)
            if 'x_wp_stock_status' in vals
            else {}
        )

        # 1. Update Parent Combos if I am a child and my price changed
        if has_price_change:
            _logger.info(f"Price change detected for {self.name} (IDs: {self.ids}). Updating parent combos...")
            self._update_parent_combo_prices()

        # 2. Auto-sync to WordPress if enabled
        if has_price_change and not self.env.context.get('skip_wordpress_sync'):
            if self._is_auto_sync_enabled():
                _logger.info(f"Auto-sync enabled. Queuing sync for {self.name}...")
                self._auto_sync_to_wordpress(price_queue_values=price_queue_values)
            else:
                 _logger.info(f"Auto-sync disabled or config missing.")
                
        # 3. Check for manual stock status change
        if 'x_wp_stock_status' in vals and not self.env.context.get('skip_wordpress_sync'):
             _logger.info(f"Manual Stock Status change detected for {self.name}. Queuing sync...")
             self._auto_sync_stock_to_wordpress(stock_queue_values=stock_queue_values) # Reuse queue mechanism
             self._update_parent_combos_stock()

        return result

    def _get_computed_stock_status(self):
        """Tính toán trạng thái kho dựa trên các thành phần (BOM)"""
        self.ensure_one()
        # Find active BOM for this product (phantom/kit type)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', self.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)

        if not bom:
            # Not a combo, return own status
            return self.x_wp_stock_status or 'instock'

        has_discontinued = False
        has_outofstock = False

        for line in bom.bom_line_ids:
            # Check component status
            # Note: bom line points to product.product, but x_wp_stock_status is on template
            # For simplicity, we check the template of the component
            comp_status = line.product_id.product_tmpl_id.x_wp_stock_status or 'instock'
            
            if comp_status == 'discontinued':
                has_discontinued = True
                break # Highest severity
            elif comp_status == 'outofstock':
                has_outofstock = True
        
        if has_discontinued:
            return 'discontinued'
        if has_outofstock:
            return 'outofstock'
        return 'instock'

    def _update_parent_combos_stock(self):
        """Find parent combos and update their status based on components"""
        # Check context to skip queueing if needed (e.g. from wizard)
        if self.env.context.get('skip_parent_combo_queue'):
            _logger.info("Skipping parent combo queue update due to context flag.")
            return

        # 1. Find variants
        variants = self.product_variant_ids
        
        # 2. Find BOM lines using these variants
        bom_lines = self.env['mrp.bom.line'].search([
            ('product_id', 'in', variants.ids)
        ])
        
        # 3. Find parent phantom/kit BOMs
        parent_boms = bom_lines.mapped('bom_id').filtered(lambda b: b.type == 'phantom' and b.active)
        parent_combos = parent_boms.mapped('product_tmpl_id')
        
        _logger.info(f"Found {len(parent_combos)} parent combos for {self.name}: {parent_combos.mapped('name')}")
        
        if not parent_combos:
             return

        # 4. Update Status & Queue Sync
        # Instead of blind queueing, we update the status field.
        # The write() method on parent will trigger its own auto-sync if status changes.
        for combo in parent_combos:
            new_status = combo._get_computed_stock_status()
            if new_status != combo.x_wp_stock_status:
                _logger.info(f"Auto-updating combo {combo.name} status to {new_status}")
                combo.write({'x_wp_stock_status': new_status})
            else:
                # If status didn't change, we might still want to sync if the child stock count changed?
                # But here we are dealing with 'status' (instock/outofstock). 
                # If the overall status is same, usually no need to push status update.
                pass

    def _get_stock_queue_values(self, old_stock_values):
        """Build old/new stock status summaries for wordpress.sync.queue display."""
        stock_queue_values = {}

        for product in self:
            old_value = old_stock_values.get(product.id)
            new_value = product.x_wp_stock_status
            if old_value == new_value:
                continue

            stock_queue_values[product.id] = {
                'old_value': old_value or '',
                'new_value': new_value or '',
            }

        return stock_queue_values

    def _auto_sync_stock_to_wordpress(self, old_value=None, new_value=None, stock_queue_values=None):
        """Queue stock sync job"""
        Queue = self.env['wordpress.sync.queue']
        for product in self:
            if not product.default_code: continue
            _logger.error(f"[Sync-DEBUG] Auto-Syncing Stock for {product.name} (ID: {product.id})")
            queue_values = (stock_queue_values or {}).get(product.id, {})
            
            Queue.create_job(
                product, 
                sync_type='stock', 
                priority=50,
                old_value=queue_values.get('old_value', old_value),
                new_value=queue_values.get('new_value', new_value)
            ) # Manual change = High priority

    def _update_parent_combo_prices(self):
        """Tìm và cập nhật giá của các combo cha chứa sản phẩm này"""
        # Tìm tất cả BOM line chứa sản phẩm này (hoặc variant của nó)
        # Note: product.template -> product.product
        variants = self.product_variant_ids
        bom_lines = self.env['mrp.bom.line'].search([
            ('product_id', 'in', variants.ids)
        ])
        
        # Lấy các BOM cha (chỉ phantom)
        parent_boms = bom_lines.mapped('bom_id').filtered(lambda b: b.type == 'phantom' and b.active)
        parent_products = parent_boms.mapped('product_tmpl_id')
        
        # Recompute price for parents
        # Gọi _compute_combo_selling_price để update lại giá và các field x_studio
        # Vì store=True nên cần invalidate cache hoặc ghi đè? 
        # computed method store=True sẽ tự chạy khi depends đổi, 
        # nhưng manual trigger thì ta gọi hàm tính toán và write
        for parent in parent_products:
             # Force re-calculate
             parent._compute_combo_selling_price()

    # ===========================================
    # ACTIONS
    # ===========================================
    def action_sync_to_wordpress(self):
        """Button action để mở wizard sync thủ công"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wordpress.price.sync',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sync_mode': 'single',
                'default_product_id': self.id
            }
        }

    def action_sync_stock_to_wordpress(self):
        """Button action để sync stock status thủ công"""
        self.ensure_one()

        config = self._get_wordpress_config()
        if not config:
            return self._notify('Thiếu cấu hình', 'Không tìm thấy cấu hình WordPress', 'warning')

        wc_key, wc_secret = config.get_credentials()
        if not wc_key or not wc_secret:
            return self._notify('Thiếu Credentials', 'Vui lòng nhập Consumer Key và Secret', 'warning')

        service = StockSyncService(self.env, config)
        result = service.sync_stock_status(self)

        if result['success']:
            # Create log
            self.env['product.sync.log'].create_log(
                product=self,
                status='success',
                message=f"Stock: {result['message']}",
                sync_type='manual',
                sku=result.get('sku', ''),
                wc_product_id=result.get('wc_product_id', '')
            )
            self._post_sync_note(self, result)
            return self._notify('Thành công', result['message'], 'success')
        else:
            self.env['product.sync.log'].create_log(
                product=self,
                status='failed',
                message=f"Stock: {result['message']}",
                sync_type='manual',
                sku=result.get('sku', self.default_code or ''),
                wc_product_id=result.get('wc_product_id', '')
            )
            return self._notify('Thất bại', result['message'], 'danger')

    # ===========================================
    # PRIVATE METHODS
    # ===========================================
    def _is_auto_sync_enabled(self):
        """Kiểm tra auto-sync có được bật không"""
        config = self._get_wordpress_config()
        if config:
            return config.auto_sync_price
        return False

    def _get_wordpress_config(self):
        """Lấy config WordPress để đồng bộ"""
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = int(ICP.get_param('wordpress_sync.default_config_id', '0') or 0)

        if config_id:
            config = self.env['wordpress.config'].browse(config_id)
            if config.exists() and config.active:
                return config

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)

    def _get_price_queue_values(self, changed_price_fields, old_price_values):
        """Build old/new price summaries for wordpress.sync.queue display."""
        price_queue_values = {}

        for product in self:
            old_parts = []
            new_parts = []
            for field in changed_price_fields:
                if field not in product._fields:
                    continue

                old_value = old_price_values.get(product.id, {}).get(field)
                new_value = product[field]
                if old_value == new_value:
                    continue

                label = product._fields[field].string or field
                old_parts.append(f"{label}: {self._format_price_queue_value(old_value)}")
                new_parts.append(f"{label}: {self._format_price_queue_value(new_value)}")

            if old_parts or new_parts:
                price_queue_values[product.id] = {
                    'old_value': '; '.join(old_parts),
                    'new_value': '; '.join(new_parts),
                }

        return price_queue_values

    def _format_price_queue_value(self, value):
        if value in (False, None, ''):
            value = 0.0
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    def _auto_sync_to_wordpress(self, price_queue_values=None):
        """Tự động đồng bộ giá lên WordPress: Create Queue Jobs"""
        config = self._get_wordpress_config()
        if not config:
            _logger.warning("Auto-sync: No active WordPress configuration found")
            return

        # Create Queue Jobs for each product
        QueueModel = self.env['wordpress.sync.queue']
        
        for product in self:
            # Check SKU
            if not product.default_code:
                continue

            queue_values = (price_queue_values or {}).get(product.id, {})
            QueueModel.create_job(
                product,
                sync_type='price',
                priority=10,
                old_value=queue_values.get('old_value'),
                new_value=queue_values.get('new_value'),
            )
            _logger.info(f"Queued sync for product {product.name} (SKU: {product.default_code})")
            
            # Post internal note about queued status? 
            # Maybe too spammy. Let's just create job.

    def _post_sync_note(self, product, result, success=True):
        """Tạo internal note trên product sau khi sync"""
        sync_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if success:
            regular_price = result.get('regular_price', 0)
            sale_price = result.get('sale_price', 0)
            stock_status = result.get('stock_status', '')

            if stock_status:
                body = (
                    f"✓ WordPress Stock Sync thành công\n"
                    f"Stock Status: {stock_status}\n"
                    f"Người thực hiện: {self.env.user.name}\n"
                    f"Thời gian: {sync_time}"
                )
            else:
                sale_price_str = f"{sale_price:,.0f} đ" if sale_price > 0 else "Không có"
                body = (
                    f"✓ WordPress Sync thành công\n"
                    f"Regular Price: {regular_price:,.0f} đ\n"
                    f"Sale Price: {sale_price_str}\n"
                    f"Người thực hiện: {self.env.user.name}\n"
                    f"Thời gian: {sync_time}"
                )
        else:
            error_message = result.get('message', 'Lỗi không xác định')

            body = (
                f"✗ WordPress Sync thất bại\n"
                f"Chi tiết lỗi: {error_message}\n"
                f"SKU: {product.default_code or 'Không có'}\n"
                f"Người thực hiện: {self.env.user.name}\n"
                f"Thời gian: {sync_time}"
            )

        product.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note'
        )

    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification cho user"""
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

