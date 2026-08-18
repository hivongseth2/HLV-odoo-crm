# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class WordPressSyncQueue(models.Model):
    _name = 'wordpress.sync.queue'
    _description = 'WordPress Sync Queue'
    _order = 'priority desc, create_date asc'

    product_id = fields.Many2one('product.template', string='Sản phẩm', required=True, ondelete='cascade')
    product_name = fields.Char(related='product_id.name', string='Tên sản phẩm', readonly=True)
    sku = fields.Char(related='product_id.default_code', string='Mã SKU', readonly=True)

    config_id = fields.Many2one(
        'wordpress.config', string='Site', ondelete='cascade', index=True,
        help='Site WordPress cụ thể job này sẽ đồng bộ tới. '
             'Để trống (job cũ trước khi có multi-site) = tự resolve theo site mặc định lúc xử lý.'
    )

    status = fields.Selection([
        ('draft', 'Nháp'),
        ('pending', 'Chờ xử lý'),
        ('processing', 'Đang xử lý'),
        ('done', 'Hoàn thành'),
        ('failed', 'Lỗi')
    ], string='Trạng thái', default='pending', index=True)
    
    sync_type = fields.Selection([
        ('price', 'Cập nhật giá'),
        ('stock', 'Cập nhật kho'),
        ('full', 'Đồng bộ tất cả')
    ], string='Loại', default='price')
    
    priority = fields.Integer(string='Độ ưu tiên', default=10, help='Số càng lớn càng ưu tiên')
    
    log = fields.Text(string='Nhật ký')
    last_error = fields.Char(string='Lỗi gần nhất')
    
    attempt_count = fields.Integer(string='Số lần thử', default=0)
    max_attempts = fields.Integer(string='Số lần thử tối đa', default=3)
    
    next_execution = fields.Datetime(string='Thời gian chạy tiếp theo', default=fields.Datetime.now, index=True)
    
    old_value = fields.Char(string='Giá trị cũ')
    new_value = fields.Char(string='Giá trị mới')

    def process_queue(self, limit=50):
        """
        Cron method to process pending queue items
        """
        # Get retry limit from default config
        config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)
        max_retries = config.max_retry_attempts if config else 3
        retry_delay_seconds = config.retry_delay_seconds if config else 30
        # Lấy danh sách pattern không retry từ config (mỗi dòng 1 pattern)
        raw_patterns = (config.no_retry_patterns or '') if config else ''
        no_retry_patterns = [p.strip() for p in raw_patterns.splitlines() if p.strip()]

        # Process jobs one by one with locking
        for _ in range(limit):
            # Fetch 1 job with SKIP LOCKED to avoid concurrency issues
            query = """
                SELECT id FROM wordpress_sync_queue
                WHERE status IN ('pending', 'failed')
                  AND attempt_count < %s
                  AND next_execution <= %s
                ORDER BY priority DESC, create_date ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """
            self.env.cr.execute(query, (max_retries, fields.Datetime.now()))
            res = self.env.cr.fetchone()
            
            if not res:
                break
                
            job_id = res[0]
            job = self.browse(job_id)
            
            # Update status immediately
            job.write({'status': 'processing', 'attempt_count': job.attempt_count + 1})
            # We do NOT commit here to keep the lock until we finish (or we commit to save 'processing' state?)
            # Actually, if we crash during process, we want 'processing' state? 
            # If we commit here, we lose the lock.
            # But process can take time.
            # Standard Odoo queue often commits 'started' state.
            # However, if we commit here, another worker CANNOT pick it up because status is 'processing' (not in SELECT query anymore).
            # So it is safe to commit here.
            self.env.cr.commit() 
            
            try:
                # Identify config and service
                # job.config_id = site cụ thể job này nhắm tới (multi-site).
                # Job cũ (tạo trước khi có multi-site) không có config_id -> fallback site mặc định.
                product = job.product_id
                config = job.config_id or product._get_wordpress_config()

                if not config:
                    raise Exception("No WordPress Config found")

                # Import services inside method to avoid circular deps at module level if any
                from .wordpress_api import PriceSyncService, StockSyncService

                result = {'success': False, 'message': 'Unknown error'}
                
                if job.sync_type in ('price', 'full'):
                    price_service = PriceSyncService(self.env, config)
                    result = price_service.sync_product(product)
                elif job.sync_type == 'stock':
                    stock_service = StockSyncService(self.env, config)
                    result = stock_service.sync_stock_status(product)

                if result['success']:
                    job.write({
                        'status': 'done',
                        'log': result['message'],
                        'last_error': False
                    })
                else:
                    raise Exception(result['message'])

            except Exception as e:
                import traceback
                error_msg = str(e)
                _logger.error(f"Queue Job Failed {job.id}: {error_msg}")

                # Lỗi khớp pattern no-retry → không cần retry, đánh dấu failed vĩnh viễn
                import re
                is_no_retry = any(
                    re.search(pattern, error_msg)
                    for pattern in no_retry_patterns
                )
                if is_no_retry:
                    job.write({
                        'status': 'failed',
                        'last_error': error_msg,
                        'log': f"{job.log or ''}\nFailed (no retry - SKU not on WP): {error_msg}",
                        'attempt_count': max_retries,  # Đặt = max để cron không pick lại
                    })
                else:
                    # Retry sau: delay tăng dần (retry_delay_seconds * attempt_count)
                    retry_delay = retry_delay_seconds * job.attempt_count
                    next_exec = fields.Datetime.now() + timedelta(seconds=retry_delay)
                    job.write({
                        'status': 'failed',
                        'last_error': error_msg,
                        'log': f"{job.log or ''}\nFailed Attempt {job.attempt_count}: {error_msg}",
                        'next_execution': next_exec
                    })
                
            # Commit after each job
            self.env.cr.commit()

    @api.model
    def create_job(self, product, sync_type='price', priority=10, initial_log=None, old_value=None, new_value=None, config_id=None):
        """
        Helper to create or update existing pending job.

        config_id: site cụ thể job này nhắm tới (multi-site). Bỏ trống = job
        "legacy" dùng site mặc định lúc xử lý (product._get_wordpress_config()).
        Mỗi (product, sync_type, config) chỉ giữ tối đa 1 job pending/failed.
        """
        # Check if pending job exists for this product + site
        existing = self.search([
            ('product_id', '=', product.id),
            ('status', 'in', ['pending', 'failed']),
            ('sync_type', '=', sync_type),
            ('config_id', '=', config_id or False),
        ], limit=1)

        vals = {
            'status': 'pending',
            'next_execution': fields.Datetime.now(),
            'priority': max(existing.priority if existing else 0, priority),
            'attempt_count': 0,  # Reset retry count khi user chủ động sync lại
        }

        if old_value: vals['old_value'] = old_value
        if new_value: vals['new_value'] = new_value

        if initial_log:
             vals['log'] = f"{initial_log}\n{existing.log or ''}" if existing else initial_log

        if existing:
            # Just touch it to ensure it's processed
            existing.write(vals)
            return existing
        else:
            vals.update({
                'product_id': product.id,
                'sync_type': sync_type,
                'priority': priority,
                'old_value': old_value,
                'new_value': new_value,
                'config_id': config_id or False,
            })
            return self.create(vals)
