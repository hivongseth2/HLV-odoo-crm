# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from .wordpress_api import PriceSyncService
import logging
import time
import math

_logger = logging.getLogger(__name__)


class WordPressPriceSyncWizard(models.TransientModel):
    """
    Wizard để đồng bộ giá thủ công lên WordPress
    """
    _name = 'wordpress.price.sync'
    _description = 'WordPress Price Sync Wizard'

    # ===========================================
    # FIELDS
    # ===========================================
    sync_mode = fields.Selection([
        ('single', 'Một sản phẩm'),
        ('all', 'Tất cả sản phẩm'),
        ('retry', 'Thử lại các lỗi thất bại'),
    ], string='Chế độ', default='single', required=True)

    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='Cấu hình WordPress',
        required=True,
        domain=[('active', '=', True)],
        default=lambda self: self._default_wordpress_config()
    )

    # Computed field để kiểm tra có nhiều config không
    has_multiple_configs = fields.Boolean(
        compute='_compute_has_multiple_configs'
    )

    # ===========================================
    # DEFAULT / COMPUTE METHODS
    # ===========================================
    @api.model
    def _default_wordpress_config(self):
        """Lấy config mặc định từ Settings hoặc config active đầu tiên"""
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = ICP.get_param('wordpress_sync.default_config_id', False)

        if config_id:
            try:
                config = self.env['wordpress.config'].browse(int(config_id))
                if config.exists() and config.active:
                    return config
            except (ValueError, TypeError):
                pass

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)

    @api.depends('wordpress_config_id')
    def _compute_has_multiple_configs(self):
        """Kiểm tra có nhiều hơn 1 config active không"""
        config_count = self.env['wordpress.config'].search_count([('active', '=', True)])
        for record in self:
            record.has_multiple_configs = config_count > 1

    # ===========================================
    # ACTIONS
    # ===========================================
    def action_sync(self):
        """Thực hiện đồng bộ"""
        self.ensure_one()

        if not self.wordpress_config_id:
            raise UserError('Vui lòng chọn cấu hình WordPress')

        # Kiểm tra credentials
        wc_key, wc_secret = self.wordpress_config_id.get_credentials()
        if not wc_key or not wc_secret:
            raise UserError('Chưa cấu hình API credentials cho WordPress')

        if self.sync_mode == 'single':
            return self._sync_single()
        elif self.sync_mode == 'retry':
            return self._sync_retry()
        else:
            # All
            return self._sync_all()

    def _sync_single(self):
        """Đồng bộ một sản phẩm"""
        if not self.product_id:
            raise UserError('Vui lòng chọn sản phẩm cần đồng bộ')

        service = PriceSyncService(self.env, self.wordpress_config_id)
        result = service.sync_product(self.product_id)

        # Log kết quả
        self._create_log(self.product_id, result, 'manual')

        # Tạo internal note trên product
        self._post_sync_note(self.product_id, result)

        # Hiển thị notification
        if result['success']:
            return self._notify('Thành công', f"{self.product_id.name}: {result['message']}", 'success')
        else:
            return self._notify('Thất bại', result['message'], 'danger')

    def _sync_retry(self):
        """Thử lại các sản phẩm bị lỗi trong 24h qua"""
        from datetime import datetime, timedelta
        
        # Tìm các log lỗi gần đây
        cutoff = datetime.now() - timedelta(hours=24)
        failed_logs = self.env['product.sync.log'].search([
            ('status', '=', 'failed'),
            ('sync_date', '>=', cutoff)
        ])
        
        if not failed_logs:
            return self._notify('Không có lỗi', 'Không tìm thấy sản phẩm lỗi nào trong 24h qua', 'success')
            
        # Lấy danh sách sản phẩm
        products = failed_logs.mapped('product_id')
        
        if not products:
             return self._notify('Không có sản phẩm', 'Các log lỗi không liên kết với sản phẩm nào', 'warning')
             
        _logger.info(f"Retrying sync for {len(products)} failed products")
        return self._sync_all(products=products)

    def _sync_all(self, products=None):
        """
        Đồng bộ tất cả hoặc một danh sách sản phẩm theo batch
        """
        if not products:
            products = self.env['product.template'].search([
                ('active', '=', True),
                ('default_code', '!=', False),
                ('default_code', '!=', '')
            ])
        
        if not products:
            return self._notify('Không có sản phẩm', 'Không tìm thấy sản phẩm nào có SKU', 'warning')

        config = self.wordpress_config_id
        service = PriceSyncService(self.env, config)
        
        # 1. Fetch map first (optimized)
        _logger.info("Fetching SKU map for batch sync...")
        product_map = service.api.get_all_products_map()
        
        total_products = len(products)
        batch_size = config.batch_size or 50
        if batch_size > 100: batch_size = 100 # API limit
        
        delay = config.sync_delay or 1.0
        
        batches = math.ceil(total_products / batch_size)
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        _logger.info(f"Starting batch sync: {total_products} products, {batches} batches, size {batch_size}")
        
        for i in range(batches):
            start = i * batch_size
            end = start + batch_size
            product_batch = products[start:end]
            
            _logger.info(f"Processing batch {i+1}/{batches}")
            
            # Process batch
            batch_results = service.sync_products_batch(product_batch, product_map)
            
            # Analyze results
            for result in batch_results.values():
                p_id_temp = next((pid for pid, res in batch_results.items() if res == result), None)
                product_obj = self.env['product.template'].browse(p_id_temp) if p_id_temp else None

                if result['success']:
                    success_count += 1
                    status = 'success'
                elif 'không có sku' in result['message'].lower():
                    skipped_count += 1
                    status = 'skipped'
                else:
                    failed_count += 1
                    status = 'failed'
                
                # Log & Note
                if product_obj:
                    self._create_log(product_obj, result, 'auto', status=status)
                    # Note: Only create note if failed, or maybe every time? 
                    # To avoid spamming chatter during bulk sync, maybe only log failures or just create log table entry
                    # Current logic: logs everything. Let's keep it but maybe optimize?
                    # For now, keep existing behavior:
                    if status != 'skipped':
                         self._post_sync_note(product_obj, result)

            # Delay
            if i < batches - 1:
                time.sleep(delay)

        # Update last sync date
        config.last_sync_date = fields.Datetime.now()
        
        message = f'Tổng: {total_products}. Thành công: {success_count}, Thất bại: {failed_count}, Bỏ qua: {skipped_count}'
        
        if failed_count > 0:
            msg_type = 'warning'
        else:
            msg_type = 'success'
            
        _logger.info(f"Batch sync completed: {message}")
        return self._notify('Hoàn tất đồng bộ', message, msg_type)

    # ===========================================
    # HELPER METHODS
    # ===========================================
    def _create_log(self, product, result, sync_type, status=None):
        """Tạo log đồng bộ"""
        if not status:
            status = 'success' if result['success'] else 'failed'
            
        self.env['product.sync.log'].create_log(
            product=product,
            status=status,
            message=result['message'],
            sync_type=sync_type,
            sku=result.get('sku', ''),
            wc_product_id=result.get('wc_product_id', ''),
            new_regular_price=result.get('regular_price', 0),
            new_sale_price=result.get('sale_price', 0)
        )

    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification"""
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

    def _post_sync_note(self, product, result):
        """Tạo internal note trên product sau khi sync"""
        from datetime import datetime
        sync_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if result['success']:
            regular_price = result.get('regular_price', 0)
            sale_price = result.get('sale_price', 0)
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
