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

    def process_queue(self, limit=50):
        """
        Cron method to process pending queue items
        """
        # Get retry limit from default config
        config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)
        max_retries = config.max_retry_attempts if config else 3

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
                product = job.product_id
                config = product._get_wordpress_config()
                
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
                
                # Schedule retry
                retry_delay = 5 * job.attempt_count # 0, 5, 10 minutes
                next_exec = fields.Datetime.now() + timedelta(minutes=retry_delay)
                
                job.write({
                    'status': 'failed',
                    'last_error': error_msg,
                    'log': f"{job.log or ''}\nFailed Attempt {job.attempt_count}: {error_msg}",
                    'next_execution': next_exec
                })
                
            # Commit after each job
            self.env.cr.commit()

    @api.model
    def create_job(self, product, sync_type='price', priority=10, initial_log=None):
        """
        Helper to create or update existing pending job
        """
        # Check if pending job exists for this product
        existing = self.search([
            ('product_id', '=', product.id),
            ('status', 'in', ['pending', 'failed']),
            ('sync_type', '=', sync_type)
        ], limit=1)
        
        vals = {
            'status': 'pending', 
            'next_execution': fields.Datetime.now(),
            'priority': max(existing.priority if existing else 0, priority)
        }
        
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
                'priority': priority
            })
            return self.create(vals)
