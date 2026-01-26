# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class WordPressSyncQueue(models.Model):
    _name = 'wordpress.sync.queue'
    _description = 'WordPress Sync Queue'
    _order = 'priority desc, create_date asc'

    product_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade')
    product_name = fields.Char(related='product_id.name', string='Product Name', readonly=True)
    sku = fields.Char(related='product_id.default_code', string='SKU', readonly=True)
    
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed')
    ], string='Status', default='pending', index=True)
    
    sync_type = fields.Selection([
        ('price', 'Price Update'),
        ('stock', 'Stock Update'),
        ('full', 'Full Sync')
    ], string='Type', default='price')
    
    priority = fields.Integer(string='Priority', default=10, help='Higher number = process first')
    
    log = fields.Text(string='Log')
    last_error = fields.Char(string='Last Error')
    
    attempt_count = fields.Integer(string='Attempts', default=0)
    max_attempts = fields.Integer(string='Max Attempts', default=3)
    
    next_execution = fields.Datetime(string='Next Execution', default=fields.Datetime.now, index=True)

    def process_queue(self, limit=50):
        """
        Cron method to process pending queue items
        """
        # Find pending jobs
        jobs = self.search([
            ('status', 'in', ['pending', 'failed']),
            ('attempt_count', '<', 3), # Hardcoded max attempts check in query
            ('next_execution', '<=', fields.Datetime.now())
        ], limit=limit, order='priority desc, create_date asc')

        if not jobs:
            return

        # Get service mapping
        # We need config to init service. We assume default config for now, 
        # or we should store config_id on queue? 
        # For simplicity, we use the product's _get_wordpress_config logic.
        
        # Group by config to optimize init?
        # For now, simplistic loop
        
        for job in jobs:
            job.write({'status': 'processing', 'attempt_count': job.attempt_count + 1})
            self.env.cr.commit() # Commit status change
            
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

                # If stock sync needed? Current requirement focuses on Price.
                # But if we want to be generic...
                # For now, just price.
                
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
                
            # Commit after each job to prevent long transaction
            self.env.cr.commit()

    @api.model
    def create_job(self, product, sync_type='price', priority=10):
        """
        Helper to create or update existing pending job
        """
        # Check if pending job exists for this product
        existing = self.search([
            ('product_id', '=', product.id),
            ('status', 'in', ['pending', 'failed']),
            ('sync_type', '=', sync_type)
        ], limit=1)
        
        if existing:
            # Just touch it to ensure it's processed
            existing.write({
                'status': 'pending', 
                'next_execution': fields.Datetime.now(),
                'priority': max(existing.priority, priority)
            })
            return existing
        else:
            return self.create({
                'product_id': product.id,
                'sync_type': sync_type,
                'priority': priority,
                'status': 'pending'
            })
