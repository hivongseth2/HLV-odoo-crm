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
                
                <!-- Step 1: Scan PICK Order -->
                <div class="section" id="step-1">
                    <h3>🔍 Step 1: Scan PICK Order</h3>
                    <p>Scan the PICK order barcode to find delivery order</p>
                    <div class="form-group">
                        <input type="text" id="pick-barcode" class="form-control" placeholder="Scan or enter PICK barcode (e.g., PICK00001)" />
                    </div>
                    <button class="btn btn-primary" onclick="scanPick()">📱 Scan PICK</button>
                    <div id="pick-result" class="alert" style="display: none;"></div>
                </div>
                
                <!-- Step 2: Order Info (Hidden initially) -->
                <div class="section" id="step-2" style="display: none;">
                    <h3>📋 Order Information</h3>
                    <div id="order-info">
                        <!-- Order details will be loaded here -->
                    </div>
                    <button class="btn btn-success" onclick="proceedToScan()">Continue to Scanning</button>
                    <button class="btn btn-secondary" onclick="startOver()">🔄 Start Over</button>
                </div>
                
                <!-- Step 3: Scan Items (Hidden initially) -->
                <div class="section" id="step-3" style="display: none;">
                    <h3>📦 Step 2: Scan Items</h3>
                    <p>Scan each package or product barcode in the delivery order</p>
                    <div class="form-group">
                        <input type="text" id="item-barcode" class="form-control" placeholder="Scan package or product barcode" />
                    </div>
                    <div class="progress-info" id="progress-info">0 / 0 items scanned</div>
                    <div class="progress">
                        <div class="progress-bar" id="progress-bar"></div>
                    </div>
                    <button class="btn btn-primary" onclick="scanItem()">📦 Scan Item</button>
                    <button class="btn btn-secondary" onclick="startOver()">🔄 Start Over</button>
                    
                    <!-- Items List -->
                    <div id="items-list" style="margin-top: 20px;">
                        <!-- Items will be loaded here -->
                    </div>
                </div>
                
                <!-- Step 4: Complete Delivery (Hidden initially) -->
                <div class="section" id="step-4" style="display: none;">
                    <h3>✅ Ready to Complete</h3>
                    <p>All items have been scanned successfully!</p>
                    <button class="btn btn-success" onclick="completeDelivery()">🚚 Complete Delivery</button>
                    <button class="btn btn-secondary" onclick="startOver()">📋 New Delivery</button>
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
                let itemsList = [];
                
                // Show only specific step
                function showStep(stepNumber) {{
                    // Hide all steps
                    for (let i = 1; i <= 4; i++) {{
                        const step = document.getElementById('step-' + i);
                        if (step) step.style.display = 'none';
                    }}
                    
                    // Show requested step
                    const targetStep = document.getElementById('step-' + stepNumber);
                    if (targetStep) targetStep.style.display = 'block';
                }}
                
                function scanPick() {{
                    const barcode = document.getElementById('pick-barcode').value.trim();
                    if (!barcode) {{
                        showAlert('pick-result', 'Please enter a PICK barcode', 'danger');
                        return;
                    }}
                    
                    // Show loading
                    showAlert('pick-result', 'Searching for delivery order...', 'info');
                    
                    // Simulate API call to scan PICK
                    fetch('/api/barcode/scan_pick', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{ barcode: barcode }})
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.success) {{
                            // Show success and order info
                            showAlert('pick-result', 'PICK order found! Loading delivery details...', 'success');
                            loadOrderInfo(data);
                        }} else {{
                            showAlert('pick-result', data.error || 'PICK order not found', 'danger');
                        }}
                    }})
                    .catch(error => {{
                        console.error('Error:', error);
                        showAlert('pick-result', 'Error connecting to server', 'danger');
                    }});
                }}
                
                function loadOrderInfo(data) {{
                    // Populate order information
                    const orderInfo = document.getElementById('order-info');
                    orderInfo.innerHTML = `
                        <div class="alert alert-info">
                            <strong>📋 Order Details:</strong><br>
                            <strong>PICK:</strong> ${{data.pick_name}}<br>
                            <strong>OUT:</strong> ${{data.out_name}}<br>
                            <strong>Customer:</strong> ${{data.customer_name}}<br>
                            <strong>Items:</strong> ${{data.total_items}} items to scan
                        </div>
                    `;
                    
                    // Store data
                    currentOutId = data.out_id;
                    totalItems = data.total_items;
                    itemsList = data.items || [];
                    scannedItems = 0;
                    
                    // Show step 2
                    showStep(2);
                }}
                
                function proceedToScan() {{
                    // Load items list
                    loadItemsList();
                    // Show step 3
                    showStep(3);
                    // Focus on item barcode input
                    document.getElementById('item-barcode').focus();
                }}
                
                function loadItemsList() {{
                    const itemsListDiv = document.getElementById('items-list');
                    if (itemsList.length === 0) {{
                        itemsListDiv.innerHTML = '<p>No items to scan</p>';
                        return;
                    }}
                    
                    let html = '<h4>Items to Scan:</h4><ul class="items-list">';
                    itemsList.forEach((item, index) => {{
                        const status = item.scanned ? 'scanned' : 'pending';
                        const icon = item.scanned ? '✅' : '⏳';
                        html += `
                            <li class="${{status}}" id="item-${{index}}">
                                <span>${{icon}} ${{item.name}} - ${{item.barcode || 'No barcode'}}</span>
                                <span class="scan-status ${{status}}">${{item.scanned ? 'Scanned' : 'Pending'}}</span>
                            </li>
                        `;
                    }});
                    html += '</ul>';
                    itemsListDiv.innerHTML = html;
                    
                    updateProgress();
                }}
                
                function scanItem() {{
                    const barcode = document.getElementById('item-barcode').value.trim();
                    if (!barcode) {{
                        alert('Please enter an item barcode');
                        return;
                    }}
                    
                    if (!currentOutId) {{
                        alert('Please scan a PICK order first');
                        return;
                    }}
                    
                    // Call API to scan item
                    fetch('/api/barcode/scan_package', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{ 
                            out_id: currentOutId,
                            barcode: barcode 
                        }})
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.success) {{
                            // Mark item as scanned
                            markItemScanned(barcode);
                            document.getElementById('item-barcode').value = '';
                            
                            // Check if all items scanned
                            if (scannedItems >= totalItems) {{
                                showStep(4);
                            }}
                        }} else {{
                            alert(data.error || 'Item not found or already scanned');
                        }}
                    }})
                    .catch(error => {{
                        console.error('Error:', error);
                        alert('Error scanning item');
                    }});
                }}
                
                function markItemScanned(barcode) {{
                    // Find and mark item as scanned
                    itemsList.forEach((item, index) => {{
                        if (item.barcode === barcode && !item.scanned) {{
                            item.scanned = true;
                            scannedItems++;
                            
                            // Update UI
                            const itemElement = document.getElementById('item-' + index);
                            if (itemElement) {{
                                itemElement.className = 'scanned';
                                itemElement.querySelector('span').innerHTML = '✅ ' + item.name + ' - ' + item.barcode;
                                itemElement.querySelector('.scan-status').innerHTML = 'Scanned';
                                itemElement.querySelector('.scan-status').className = 'scan-status scanned';
                            }}
                            return;
                        }}
                    }});
                    
                    updateProgress();
                }}
                
                function updateProgress() {{
                    const progressInfo = document.getElementById('progress-info');
                    const progressBar = document.getElementById('progress-bar');
                    
                    progressInfo.textContent = `${{scannedItems}} / ${{totalItems}} items scanned`;
                    const percentage = totalItems > 0 ? (scannedItems / totalItems) * 100 : 0;
                    progressBar.style.width = percentage + '%';
                }}
                
                function completeDelivery() {{
                    if (!currentOutId) {{
                        alert('No delivery to complete');
                        return;
                    }}
                    
                    if (confirm('Complete this delivery? This action cannot be undone.')) {{
                        fetch('/api/barcode/complete_out', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{ out_id: currentOutId }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.success) {{
                                alert('✅ Delivery completed successfully!');
                                startOver();
                            }} else {{
                                alert('❌ Error completing delivery: ' + (data.error || 'Unknown error'));
                            }}
                        }})
                        .catch(error => {{
                            console.error('Error:', error);
                            alert('Error completing delivery');
                        }});
                    }}
                }}
                
                function startOver() {{
                    // Reset all data
                    currentOutId = null;
                    totalItems = 0;
                    scannedItems = 0;
                    itemsList = [];
                    
                    // Clear inputs
                    document.getElementById('pick-barcode').value = '';
                    document.getElementById('item-barcode').value = '';
                    
                    // Hide alerts
                    document.getElementById('pick-result').style.display = 'none';
                    
                    // Show step 1
                    showStep(1);
                    
                    // Focus on pick barcode input
                    document.getElementById('pick-barcode').focus();
                }}
                
                function showAlert(elementId, message, type) {{
                    const alertElement = document.getElementById(elementId);
                    alertElement.className = 'alert alert-' + type;
                    alertElement.textContent = message;
                    alertElement.style.display = 'block';
                }}
                
                // Initialize on page load
                document.addEventListener('DOMContentLoaded', function() {{
                    showStep(1);
                    document.getElementById('pick-barcode').focus();
                }});
                
                // Handle Enter key
                document.getElementById('pick-barcode').addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        scanPick();
                    }}
                }});
                
                document.getElementById('item-barcode').addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        scanItem();
                    }}
                }});
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