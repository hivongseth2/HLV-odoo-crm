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

    @http.route('/barcode/shipper/demo', type='http', auth='user', website=False)
    def shipper_interface_demo(self, **kwargs):
        """
        Demo shipper interface page - bypasses permission check for testing
        """
        return request.render('hlv_barcode_shipper.shipper_interface', {
            'user': request.env.user,
        })

    @http.route('/barcode/shipper/simple', type='http', auth='user', website=False)
    def shipper_interface_simple(self, **kwargs):
        """
        Simple shipper interface with embedded CSS for testing
        """
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Shipper Scanner</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f8f9fa;
                    color: #2c3e50;
                }}
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                }}
                .header {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    text-align: center;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .header h1 {{
                    margin: 0 0 10px 0;
                    color: #2c3e50;
                    font-size: 24px;
                }}
                .user-info {{
                    color: #6c757d;
                    font-size: 14px;
                }}
                .section {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .section h3 {{
                    margin: 0 0 15px 0;
                    color: #2c3e50;
                    font-size: 18px;
                }}
                .form-group {{
                    margin-bottom: 15px;
                }}
                .form-control {{
                    width: 100%;
                    padding: 12px 16px;
                    border: 2px solid #e9ecef;
                    border-radius: 6px;
                    font-size: 16px;
                    box-sizing: border-box;
                }}
                .form-control:focus {{
                    outline: none;
                    border-color: #007bff;
                    box-shadow: 0 0 0 0.2rem rgba(0,123,255,0.25);
                }}
                .btn {{
                    display: inline-block;
                    padding: 12px 24px;
                    font-size: 16px;
                    font-weight: 500;
                    text-align: center;
                    text-decoration: none;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    margin: 4px;
                    transition: all 0.15s ease-in-out;
                }}
                .btn-primary {{
                    background-color: #007bff;
                    color: white;
                }}
                .btn-primary:hover {{
                    background-color: #0056b3;
                }}
                .btn-success {{
                    background-color: #28a745;
                    color: white;
                }}
                .btn-success:hover {{
                    background-color: #1e7e34;
                }}
                .btn-secondary {{
                    background-color: #6c757d;
                    color: white;
                }}
                .btn-secondary:hover {{
                    background-color: #545b62;
                }}
                .progress-info {{
                    font-size: 14px;
                    color: #6c757d;
                    margin-bottom: 10px;
                }}
                .progress {{
                    height: 8px;
                    background-color: #e9ecef;
                    border-radius: 4px;
                    overflow: hidden;
                    margin-bottom: 15px;
                }}
                .progress-bar {{
                    height: 100%;
                    background-color: #28a745;
                    width: 0%;
                    transition: width 0.3s ease;
                }}
                .alert {{
                    padding: 12px 16px;
                    border-radius: 6px;
                    margin-bottom: 15px;
                }}
                .alert-success {{
                    background-color: #d4edda;
                    border: 1px solid #c3e6cb;
                    color: #155724;
                }}
                .alert-danger {{
                    background-color: #f8d7da;
                    border: 1px solid #f5c6cb;
                    color: #721c24;
                }}
                .alert-info {{
                    background-color: #d1ecf1;
                    border: 1px solid #bee5eb;
                    color: #0c5460;
                }}
                @media (max-width: 768px) {{
                    body {{
                        padding: 10px;
                    }}
                    .section {{
                        padding: 15px;
                    }}
                    .btn {{
                        width: 100%;
                        margin: 4px 0;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📱 Shipper Scanner</h1>
                    <div class="user-info">👤 {request.env.user.name}</div>
                </div>
                
                <div class="section">
                    <h3>🔍 Step 1: Scan PICK Order</h3>
                    <p>Scan the PICK order barcode to find delivery order</p>
                    <div class="form-group">
                        <input type="text" id="pick-barcode" class="form-control" placeholder="Scan or enter PICK barcode" />
                    </div>
                    <button class="btn btn-primary" onclick="scanPick()">📱 Scan PICK</button>
                </div>
                
                <div class="section">
                    <h3>📦 Step 2: Scan Items</h3>
                    <p>Scan each package or product barcode in the delivery order</p>
                    <div class="form-group">
                        <input type="text" id="item-barcode" class="form-control" placeholder="Scan package or product" disabled />
                    </div>
                    <div class="progress-info">0 / 0 items scanned</div>
                    <div class="progress">
                        <div class="progress-bar" id="progress-bar"></div>
                    </div>
                    <button class="btn btn-secondary" onclick="scanItem()" disabled>📦 Scan Item</button>
                    <button class="btn btn-secondary" onclick="startOver()">🔄 Start Over</button>
                </div>
                
                <div class="section">
                    <h3>✅ Delivery Completed</h3>
                    <button class="btn btn-success" onclick="completeDelivery()" disabled>🚚 Complete Delivery</button>
                    <button class="btn btn-secondary" onclick="newDelivery()">📋 New Delivery</button>
                    <button class="btn btn-secondary" onclick="viewHistory()">📊 View History</button>
                    <button class="btn btn-secondary" onclick="showHelp()">❓ Help</button>
                </div>
                
                <div class="section">
                    <h3>📋 Scan History</h3>
                    <div id="scan-history">
                        <p>Loading...</p>
                    </div>
                </div>
                
                <div class="section">
                    <h3>❓ How to Use</h3>
                    <ol>
                        <li><strong>Scan PICK Order:</strong> Use your device camera or type the PICK barcode (e.g., PICK00001)</li>
                        <li><strong>Scan Items:</strong> Scan each package (PACK) or product barcode in the delivery order</li>
                        <li><strong>Complete:</strong> When all items are scanned, tap "Complete Delivery"</li>
                        <li><strong>Alternative:</strong> You can re-scan the PICK barcode to complete directly</li>
                    </ol>
                    <h4>Tips:</h4>
                    <ul>
                        <li>Make sure your camera has good lighting</li>
                        <li>Hold the barcode steady in the camera view</li>
                        <li>You can also type barcodes manually if needed</li>
                    </ul>
                </div>
            </div>
            
            <script>
                let currentOutId = null;
                let totalItems = 0;
                let scannedItems = 0;
                
                function scanPick() {{
                    const barcode = document.getElementById('pick-barcode').value.trim();
                    if (!barcode) {{
                        alert('Please enter a PICK barcode');
                        return;
                    }}
                    
                    // Simulate API call
                    console.log('Scanning PICK:', barcode);
                    alert('PICK scan functionality will be implemented with backend API');
                }}
                
                function scanItem() {{
                    const barcode = document.getElementById('item-barcode').value.trim();
                    if (!barcode) {{
                        alert('Please enter an item barcode');
                        return;
                    }}
                    
                    console.log('Scanning item:', barcode);
                    alert('Item scan functionality will be implemented with backend API');
                }}
                
                function completeDelivery() {{
                    if (confirm('Complete this delivery?')) {{
                        alert('Delivery completion will be implemented with backend API');
                    }}
                }}
                
                function startOver() {{
                    document.getElementById('pick-barcode').value = '';
                    document.getElementById('item-barcode').value = '';
                    document.getElementById('item-barcode').disabled = true;
                    document.querySelector('.progress-info').textContent = '0 / 0 items scanned';
                    document.getElementById('progress-bar').style.width = '0%';
                }}
                
                function newDelivery() {{
                    startOver();
                }}
                
                function viewHistory() {{
                    alert('History view will be implemented');
                }}
                
                function showHelp() {{
                    alert('Help documentation will be implemented');
                }}
            </script>
        </body>
        </html>
        """
        return html_content

    @http.route('/barcode/shipper/grant_access', type='http', auth='user', website=False)
    def grant_shipper_access(self, **kwargs):
        """
        Grant shipper access to current user (for testing/setup)
        """
        try:
            # Get the shipper group
            shipper_group = request.env.ref('hlv_barcode_shipper.group_shipper')
            
            # Add current user to shipper group
            current_user = request.env.user
            current_user.write({
                'groups_id': [(4, shipper_group.id)]
            })
            
            return f"""
            <html>
                <head>
                    <title>Access Granted</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                        .success {{ color: #28a745; font-size: 24px; margin-bottom: 20px; }}
                        .btn {{ display: inline-block; padding: 12px 24px; background: #007bff; color: white; text-decoration: none; border-radius: 6px; }}
                    </style>
                </head>
                <body>
                    <div class="success">✅ Shipper Access Granted!</div>
                    <p>User <strong>{current_user.name}</strong> now has Shipper permissions.</p>
                    <a href="/barcode/shipper" class="btn">Go to Shipper Scanner</a>
                </body>
            </html>
            """
        except Exception as e:
            return f"""
            <html>
                <head><title>Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h2 style="color: #dc3545;">❌ Error</h2>
                    <p>Could not grant access: {str(e)}</p>
                    <p>Please contact your administrator.</p>
                    <a href="/web" style="display: inline-block; padding: 12px 24px; background: #007bff; color: white; text-decoration: none; border-radius: 6px;">Back to Odoo</a>
                </body>
            </html>
            """

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