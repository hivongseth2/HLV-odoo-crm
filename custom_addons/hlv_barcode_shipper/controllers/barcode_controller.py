# -*- coding: utf-8 -*-

import json
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class BarcodeShipperController(http.Controller):

    def _check_shipper_access(self):
        """
        Check if current user has shipper access
        """
        if not request.env.user.has_group('hlv_barcode_shipper.group_shipper'):
            return {
                'success': False,
                'error': 'Access denied. Shipper permissions required.'
            }
        return {'success': True}

    def _log_scan(self, barcode, scan_type, **kwargs):
        """
        Log barcode scan for audit trail
        """
        try:
            request.env['barcode.scan.log'].log_scan(
                barcode=barcode,
                scan_type=scan_type,
                **kwargs
            )
        except Exception as e:
            _logger.warning(f"Failed to log scan: {str(e)}")

    @http.route('/api/barcode/scan_pick', type='json', auth='user', methods=['POST'], csrf=False)
    def scan_pick_order(self, **kwargs):
        """
        Scan PICK order barcode and find related OUT order
        
        Expected payload:
        {
            "barcode": "PICK00001"
        }
        
        Returns:
        {
            "success": true/false,
            "out_picking_id": 123,
            "out_picking_name": "OUT00001",
            "message": "Success message",
            "error": "Error message if failed"
        }
        """
        try:
            # Check access
            access_check = self._check_shipper_access()
            if not access_check['success']:
                return access_check

            data = json.loads(request.httprequest.data.decode('utf-8'))
            barcode = data.get('barcode', '').strip()
            
            if not barcode:
                return {
                    'success': False,
                    'error': 'Barcode is required'
                }

            # Find OUT picking by PICK name
            picking_obj = request.env['stock.picking']
            out_picking = picking_obj.find_out_picking_by_pick_name(barcode)
            
            # Mark as scanned by shipper
            out_picking.mark_shipper_scanned()
            
            # Log the scan
            self._log_scan(
                barcode=barcode,
                scan_type='pick',
                picking_id=out_picking.id,
                status='success',
                message=f'Found OUT order {out_picking.name}'
            )
            
            return {
                'success': True,
                'out_picking_id': out_picking.id,
                'out_picking_name': out_picking.name,
                'message': f'Found delivery order {out_picking.name}'
            }
            
        except UserError as e:
            self._log_scan(
                barcode=barcode,
                scan_type='pick',
                status='error',
                message=str(e)
            )
            return {
                'success': False,
                'error': str(e)
            }
        except Exception as e:
            _logger.error(f"Error in scan_pick_order: {str(e)}")
            self._log_scan(
                barcode=barcode,
                scan_type='pick',
                status='error',
                message=f'System error: {str(e)}'
            )
            return {
                'success': False,
                'error': 'System error occurred'
            }

    @http.route('/api/barcode/get_out', type='json', auth='user', methods=['POST'], csrf=False)
    def get_out_order_details(self, **kwargs):
        """
        Get OUT order details including packages/products
        
        Expected payload:
        {
            "picking_id": 123
        }
        
        Returns:
        {
            "success": true/false,
            "picking": {
                "id": 123,
                "name": "OUT00001",
                "partner_name": "Customer Name",
                "state": "assigned"
            },
            "items": [
                {
                    "id": 1,
                    "name": "PACK001",
                    "barcode": "PACK001",
                    "scanned": false,
                    "type": "package"
                }
            ],
            "summary": {
                "total_items": 5,
                "scanned_items": 2,
                "all_scanned": false
            }
        }
        """
        try:
            # Check access
            access_check = self._check_shipper_access()
            if not access_check['success']:
                return access_check

            data = json.loads(request.httprequest.data.decode('utf-8'))
            picking_id = data.get('picking_id')
            
            if not picking_id:
                return {
                    'success': False,
                    'error': 'Picking ID is required'
                }

            picking = request.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {
                    'success': False,
                    'error': 'Picking not found'
                }

            # Get packages/products info
            items = picking.get_packages_info()
            
            return {
                'success': True,
                'picking': {
                    'id': picking.id,
                    'name': picking.name,
                    'partner_name': picking.partner_id.name if picking.partner_id else '',
                    'state': picking.state,
                    'origin': picking.origin or ''
                },
                'items': items,
                'summary': {
                    'total_items': len(items),
                    'scanned_items': len([item for item in items if item['scanned']]),
                    'all_scanned': picking.all_packages_scanned
                }
            }
            
        except Exception as e:
            _logger.error(f"Error in get_out_order_details: {str(e)}")
            return {
                'success': False,
                'error': 'System error occurred'
            }

    @http.route('/api/barcode/scan_package', type='json', auth='user', methods=['POST'], csrf=False)
    def scan_package_or_product(self, **kwargs):
        """
        Scan package or product barcode
        
        Expected payload:
        {
            "picking_id": 123,
            "barcode": "PACK001"
        }
        
        Returns:
        {
            "success": true/false,
            "type": "package/product",
            "name": "PACK001",
            "message": "Success message",
            "summary": {
                "total_items": 5,
                "scanned_items": 3,
                "all_scanned": false
            }
        }
        """
        try:
            # Check access
            access_check = self._check_shipper_access()
            if not access_check['success']:
                return access_check

            data = json.loads(request.httprequest.data.decode('utf-8'))
            picking_id = data.get('picking_id')
            barcode = data.get('barcode', '').strip()
            
            if not picking_id or not barcode:
                return {
                    'success': False,
                    'error': 'Picking ID and barcode are required'
                }

            picking = request.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {
                    'success': False,
                    'error': 'Picking not found'
                }

            # Scan the package/product
            result = picking.scan_package_or_product(barcode)
            
            # Log the scan
            log_kwargs = {
                'picking_id': picking.id,
                'status': 'success' if result['success'] else 'error',
                'message': result['message']
            }
            
            if result['success']:
                if result['type'] == 'package':
                    # Find package for logging
                    package = picking.package_level_ids.filtered(
                        lambda pl: pl.package_id.name == barcode
                    ).package_id
                    if package:
                        log_kwargs['package_id'] = package.id
                elif result['type'] == 'product':
                    # Find product for logging
                    move_line = picking.move_line_ids.filtered(
                        lambda ml: ml.product_id.barcode == barcode or 
                                  ml.product_id.default_code == barcode
                    )
                    if move_line:
                        log_kwargs['product_id'] = move_line.product_id.id
            
            self._log_scan(
                barcode=barcode,
                scan_type='package',
                **log_kwargs
            )
            
            # Add summary information
            if result['success']:
                items = picking.get_packages_info()
                result['summary'] = {
                    'total_items': len(items),
                    'scanned_items': len([item for item in items if item['scanned']]),
                    'all_scanned': picking.all_packages_scanned
                }
            
            return result
            
        except Exception as e:
            _logger.error(f"Error in scan_package_or_product: {str(e)}")
            self._log_scan(
                barcode=barcode,
                scan_type='package',
                picking_id=picking_id,
                status='error',
                message=f'System error: {str(e)}'
            )
            return {
                'success': False,
                'error': 'System error occurred'
            }

    @http.route('/api/barcode/complete_out', type='json', auth='user', methods=['POST'], csrf=False)
    def complete_delivery_order(self, **kwargs):
        """
        Complete delivery order by validating the picking
        
        Expected payload:
        {
            "picking_id": 123
        }
        
        Returns:
        {
            "success": true/false,
            "message": "Success/error message",
            "picking_state": "done"
        }
        """
        try:
            # Check access
            access_check = self._check_shipper_access()
            if not access_check['success']:
                return access_check

            data = json.loads(request.httprequest.data.decode('utf-8'))
            picking_id = data.get('picking_id')
            
            if not picking_id:
                return {
                    'success': False,
                    'error': 'Picking ID is required'
                }

            picking = request.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {
                    'success': False,
                    'error': 'Picking not found'
                }

            # Complete the delivery
            result = picking.complete_delivery()
            
            # Log the completion
            self._log_scan(
                barcode=picking.name,
                scan_type='complete',
                picking_id=picking.id,
                status='success' if result['success'] else 'error',
                message=result['message']
            )
            
            result['picking_state'] = picking.state
            return result
            
        except UserError as e:
            self._log_scan(
                barcode=f'COMPLETE_{picking_id}',
                scan_type='complete',
                picking_id=picking_id,
                status='error',
                message=str(e)
            )
            return {
                'success': False,
                'error': str(e)
            }
        except Exception as e:
            _logger.error(f"Error in complete_delivery_order: {str(e)}")
            self._log_scan(
                barcode=f'COMPLETE_{picking_id}',
                scan_type='complete',
                picking_id=picking_id,
                status='error',
                message=f'System error: {str(e)}'
            )
            return {
                'success': False,
                'error': 'System error occurred'
            }

    @http.route('/api/barcode/scan_history', type='json', auth='user', methods=['POST'], csrf=False)
    def get_scan_history(self, **kwargs):
        """
        Get scan history for current user
        
        Expected payload:
        {
            "picking_id": 123,  // optional
            "limit": 50         // optional
        }
        
        Returns:
        {
            "success": true,
            "history": [
                {
                    "barcode": "PACK001",
                    "scan_type": "package",
                    "scan_time": "2024-01-01 10:00:00",
                    "status": "success",
                    "message": "Package scanned successfully"
                }
            ]
        }
        """
        try:
            # Check access
            access_check = self._check_shipper_access()
            if not access_check['success']:
                return access_check

            data = json.loads(request.httprequest.data.decode('utf-8'))
            picking_id = data.get('picking_id')
            limit = data.get('limit', 50)
            
            # Get scan history
            scan_logs = request.env['barcode.scan.log'].get_scan_history(
                picking_id=picking_id,
                user_id=request.env.user.id,
                limit=limit
            )
            
            history = []
            for log in scan_logs:
                history.append({
                    'id': log.id,
                    'barcode': log.barcode,
                    'scan_type': log.scan_type,
                    'scan_time': log.scan_time.strftime('%Y-%m-%d %H:%M:%S') if log.scan_time else '',
                    'status': log.status,
                    'message': log.message or '',
                    'picking_name': log.picking_id.name if log.picking_id else '',
                    'package_name': log.package_id.name if log.package_id else '',
                    'product_name': log.product_id.display_name if log.product_id else ''
                })
            
            return {
                'success': True,
                'history': history
            }
            
        except Exception as e:
            _logger.error(f"Error in get_scan_history: {str(e)}")
            return {
                'success': False,
                'error': 'System error occurred'
            }

    @http.route('/barcode/shipper', type='http', auth='user', website=False)
    def shipper_interface(self, **kwargs):
        """
        Main shipper interface page
        """
        # Check if user has shipper access
        if not request.env.user.has_group('hlv_barcode_shipper.group_shipper'):
            # Return a simple access denied page instead of using web.access_denied
            return request.render('hlv_barcode_shipper.access_denied', {
                'user': request.env.user,
            })
        
        return request.render('hlv_barcode_shipper.shipper_interface', {
            'user': request.env.user,
        })

    @http.route('/api/barcode/reset_scan', type='json', auth='user', methods=['POST'], csrf=False)
    def reset_scan_status(self, **kwargs):
        """
        Reset scan status for a picking (for testing/debugging)
        
        Expected payload:
        {
            "picking_id": 123
        }
        """
        try:
            # Check access (only for admin or manager)
            if not request.env.user.has_group('stock.group_stock_manager'):
                return {
                    'success': False,
                    'error': 'Access denied. Manager permissions required.'
                }

            data = json.loads(request.httprequest.data.decode('utf-8'))
            picking_id = data.get('picking_id')
            
            if not picking_id:
                return {
                    'success': False,
                    'error': 'Picking ID is required'
                }

            picking = request.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {
                    'success': False,
                    'error': 'Picking not found'
                }

            picking.reset_scan_status()
            
            return {
                'success': True,
                'message': f'Scan status reset for {picking.name}'
            }
            
        except Exception as e:
            _logger.error(f"Error in reset_scan_status: {str(e)}")
            return {
                'success': False,
                'error': 'System error occurred'
            }