from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ProductSyncLog(models.Model):
    _name = 'product.sync.log'
    _description = 'Product Price Sync Log'
    _order = 'sync_date desc'

    product_id = fields.Many2one(
        'product.template',
        string='Product',
        ondelete='cascade',
        required=True
    )

    sku = fields.Char(
        string='SKU',
        help='Product SKU used for matching with WordPress'
    )

    sync_type = fields.Selection(
        [
            ('manual', 'Manual'),
            ('auto', 'Automatic (on product edit)'),
            ('test', 'Test Sync')
        ],
        string='Sync Type',
        default='auto'
    )

    status = fields.Selection(
        [
            ('success', 'Success ✅'),
            ('failed', 'Failed ❌'),
            ('skipped', 'Skipped ⏭️'),
            ('partial', 'Partial ⚠️')
        ],
        string='Status',
        required=True
    )

    message = fields.Text(
        string='Message',
        help='Details about sync result'
    )

    wc_product_id = fields.Char(
        string='WC Product ID',
        help='WooCommerce Product ID (for single product or parent)'
    )

    wc_variation_id = fields.Char(
        string='WC Variation ID',
        help='WooCommerce Variation ID (if applicable)'
    )

    sync_date = fields.Datetime(
        string='Sync Date',
        default=lambda self: fields.Datetime.now(),
        readonly=True
    )

    # Price information
    old_regular_price = fields.Float(
        string='Old Regular Price',
        help='Previous regular price'
    )

    new_regular_price = fields.Float(
        string='New Regular Price',
        help='New regular price synced to WordPress'
    )

    old_sale_price = fields.Float(
        string='Old Sale Price',
        help='Previous sale price'
    )

    new_sale_price = fields.Float(
        string='New Sale Price',
        help='New sale price synced to WordPress'
    )

    # Changed by information
    changed_by_id = fields.Many2one(
        'res.users',
        string='Changed By',
        readonly=True,
        default=lambda self: self.env.user
    )

    changed_by_name = fields.Char(
        string='Changed By Name',
        compute='_compute_changed_by_name',
        store=True
    )

    @staticmethod
    def _compute_changed_by_name():
        for record in self:
            record.changed_by_name = record.changed_by_id.name if record.changed_by_id else 'System'

    def _clean_old_logs(self):
        """Clean up old sync logs based on config retention days"""
        try:
            from datetime import timedelta
            config = self.env['wordpress.config'].search([], limit=1)
            if not config:
                return

            days_to_keep = config.sync_log_days or 30
            cutoff_date = fields.Datetime.now() - timedelta(days=days_to_keep)

            old_logs = self.search([('sync_date', '<', cutoff_date)])
            old_logs.unlink()

            _logger.info(f"🧹 Cleaned up {len(old_logs)} old sync logs (older than {days_to_keep} days)")
        except Exception as e:
            _logger.warning(f"⚠️ Error cleaning old logs: {str(e)}")
