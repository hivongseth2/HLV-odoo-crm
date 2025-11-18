# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    shipper_scanned = fields.Boolean(
        string='Shipper Scanned',
        default=False,
        help='Indicates if this picking has been scanned by shipper'
    )
    
    shipper_scan_time = fields.Datetime(
        string='Shipper Scan Time',
        help='When the shipper first scanned this picking'
    )
    
    shipper_user_id = fields.Many2one(
        'res.users',
        string='Shipper',
        help='User who scanned this picking'
    )
    
    packages_scanned_count = fields.Integer(
        string='Packages Scanned',
        compute='_compute_packages_scanned_count',
        help='Number of packages that have been scanned'
    )
    
    total_packages_count = fields.Integer(
        string='Total Packages',
        compute='_compute_total_packages_count',
        help='Total number of packages in this picking'
    )
    
    all_packages_scanned = fields.Boolean(
        string='All Packages Scanned',
        compute='_compute_all_packages_scanned',
        help='True if all packages have been scanned'
    )
    
    scan_log_ids = fields.One2many(
        'barcode.scan.log',
        'picking_id',
        string='Scan Logs',
        help='Barcode scan logs for this picking'
    )

    @api.depends('package_level_ids.scanned')
    def _compute_packages_scanned_count(self):
        for picking in self:
            picking.packages_scanned_count = len(
                picking.package_level_ids.filtered('scanned')
            )

    @api.depends('package_level_ids')
    def _compute_total_packages_count(self):
        for picking in self:
            picking.total_packages_count = len(picking.package_level_ids)

    @api.depends('packages_scanned_count', 'total_packages_count')
    def _compute_all_packages_scanned(self):
        for picking in self:
            if picking.total_packages_count > 0:
                picking.all_packages_scanned = (
                    picking.packages_scanned_count == picking.total_packages_count
                )
            else:
                # If no packages, check if all move lines are scanned
                picking.all_packages_scanned = all(
                    line.scanned for line in picking.move_line_ids
                )

    @api.model
    def find_out_picking_by_pick_name(self, pick_name):
        """
        Find OUT picking related to PICK order name
        Logic: PICK order is usually the internal transfer, OUT is the delivery
        """
        # First try to find the PICK order
        pick_picking = self.search([
            ('name', '=', pick_name),
            ('picking_type_id.code', '=', 'internal')
        ], limit=1)
        
        if not pick_picking:
            # Try broader search if exact match fails
            pick_picking = self.search([
                ('name', 'ilike', pick_name)
            ], limit=1)
        
        if not pick_picking:
            raise UserError(f"PICK order {pick_name} not found")
        
        # Find related OUT picking
        # Method 1: Check if there's a related delivery order through origin
        out_picking = None
        if pick_picking.origin:
            out_picking = self.search([
                ('origin', '=', pick_picking.origin),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', 'in', ['assigned', 'partially_available'])
            ], limit=1)
        
        # Method 2: Check through sale order
        if not out_picking and pick_picking.sale_id:
            out_picking = self.search([
                ('sale_id', '=', pick_picking.sale_id.id),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', 'in', ['assigned', 'partially_available'])
            ], limit=1)
        
        # Method 3: Check through group_id (procurement group)
        if not out_picking and pick_picking.group_id:
            out_picking = self.search([
                ('group_id', '=', pick_picking.group_id.id),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', 'in', ['assigned', 'partially_available'])
            ], limit=1)
        
        if not out_picking:
            raise UserError(f"No related OUT order found for PICK {pick_name}")
        
        return out_picking

    def mark_shipper_scanned(self, user_id=None):
        """
        Mark this picking as scanned by shipper
        """
        self.ensure_one()
        self.write({
            'shipper_scanned': True,
            'shipper_scan_time': fields.Datetime.now(),
            'shipper_user_id': user_id or self.env.user.id
        })

    def get_packages_info(self):
        """
        Get packages information for mobile interface
        """
        self.ensure_one()
        packages_info = []
        
        if self.package_level_ids:
            # If packages exist, return package info
            for package_level in self.package_level_ids:
                packages_info.append({
                    'id': package_level.id,
                    'name': package_level.package_id.name,
                    'barcode': package_level.package_id.name,  # Assuming package name is barcode
                    'scanned': package_level.scanned,
                    'type': 'package'
                })
        else:
            # If no packages, return product info
            for move_line in self.move_line_ids:
                packages_info.append({
                    'id': move_line.id,
                    'name': move_line.product_id.display_name,
                    'barcode': move_line.product_id.barcode or move_line.product_id.default_code,
                    'scanned': getattr(move_line, 'scanned', False),
                    'qty': move_line.quantity,
                    'type': 'product'
                })
        
        return packages_info

    def scan_package_or_product(self, barcode):
        """
        Scan a package or product barcode
        """
        self.ensure_one()
        
        # Try to find package first
        package_level = self.package_level_ids.filtered(
            lambda pl: pl.package_id.name == barcode
        )
        
        if package_level:
            package_level.write({'scanned': True})
            return {
                'success': True,
                'type': 'package',
                'name': package_level.package_id.name,
                'message': f'Package {barcode} scanned successfully'
            }
        
        # Try to find product
        move_line = self.move_line_ids.filtered(
            lambda ml: ml.product_id.barcode == barcode or 
                      ml.product_id.default_code == barcode
        )
        
        if move_line:
            # Add scanned field if not exists
            if not hasattr(move_line, 'scanned'):
                # Create a custom field or use a different approach
                # For now, we'll use a context flag
                move_line.with_context(scanned=True)
            else:
                move_line.write({'scanned': True})
            
            return {
                'success': True,
                'type': 'product',
                'name': move_line.product_id.display_name,
                'message': f'Product {barcode} scanned successfully'
            }
        
        return {
            'success': False,
            'message': f'Barcode {barcode} not found in this order'
        }

    def complete_delivery(self):
        """
        Complete the delivery by validating the picking
        """
        self.ensure_one()
        
        if self.state != 'assigned':
            raise UserError("Order must be in 'Ready' state to complete delivery")
        
        # Check if all packages/products are scanned
        if not self.all_packages_scanned:
            raise UserError("Please scan all packages/products before completing delivery")
        
        # Validate the picking
        try:
            self.button_validate()
            return {
                'success': True,
                'message': f'Delivery {self.name} completed successfully'
            }
        except Exception as e:
            raise UserError(f"Error completing delivery: {str(e)}")

    def reset_scan_status(self):
        """
        Reset scan status for all packages/products
        """
        self.ensure_one()
        self.package_level_ids.write({'scanned': False})
        # Reset move lines if they have scanned field
        for move_line in self.move_line_ids:
            if hasattr(move_line, 'scanned'):
                move_line.write({'scanned': False})