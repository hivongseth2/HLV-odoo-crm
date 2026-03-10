# wizard/misa_shipping_address_batch_update.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MisaShippingAddressBatchUpdate(models.TransientModel):
    _name = 'misa.shipping.address.batch.update'
    _description = 'Batch Update MISA Shipping Address'

    limit = fields.Integer(
        string='Limit',
        default=100,
        help='Max number of orders to process (0 = no limit)'
    )
    dry_run = fields.Boolean(
        string='Dry Run',
        default=False,
        help='If checked, will NOT save changes to database'
    )
    force_update = fields.Boolean(
        string='Force Update',
        default=False,
        help='If checked, will update orders that already have an address'
    )
    status = fields.Text(
        string='Status',
        readonly=True,
        help='Process status and summary'
    )

    def action_update_shipping_address(self):
        """Main action to update shipping addresses from MISA CRM"""
        self.ensure_one()
        
        try:
            # Import script utilities
            from ..scripts.update_shipping_address_batch import ShippingAddressUpdater
            
            # Get MISA credentials và headers
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            
            try:
                crm_token = misa_utils._fetch_login_crm_token()
            except Exception as e:
                raise UserError(_("Failed to login to MISA CRM: %s") % str(e))
            
            misa_headers = misa_config.get_crm_header(crm_token)
            
            # Create updater instance
            updater = ShippingAddressUpdater(self.env, misa_headers)
            
            # Run update
            limit = self.limit if self.limit > 0 else None
            updater.update_sale_orders(
                limit=limit,
                dry_run=self.dry_run,
                force_update=self.force_update
            )
            
            # Build summary
            summary = f"""
            Updated: {updater.updated_count} orders
            Failed: {updater.failed_count} orders
            """
            
            if updater.errors:
                summary += "\n\nErrors:\n"
                for err in updater.errors:
                    summary += f"  - {err['order_name']}: {err['error']}\n"
            
            self.status = summary
            
            _logger.info(f"Batch update completed: {updater.updated_count} updated, {updater.failed_count} failed")
            
            # Return action to show self in form view with results
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'misa.shipping.address.batch.update',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
            
        except ImportError:
            raise UserError(_("Update script not found. Ensure scripts directory is properly configured."))
        except Exception as e:
            _logger.error(f"Batch update error: {str(e)}", exc_info=True)
            raise UserError(_("Batch update failed: %s") % str(e))
