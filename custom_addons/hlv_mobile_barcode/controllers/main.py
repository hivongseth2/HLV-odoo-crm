from odoo import http, _
# pyrefly: ignore [missing-import]
from odoo.http import request

class HLVMobileBarcodeController(http.Controller):

    @http.route('/hlv_mobile_barcode/smart_scan', type='json', auth='user')
    def smart_scan(self, barcode):
        """
        Smart Routing API: Determine what the scanned barcode represents.
        Priority: Picking > Product > Location > Package
        """
        # 1. Check if it's a Picking
        picking = request.env['stock.picking'].search([('name', '=', barcode)], limit=1)
        if picking:
            # Check if picking type is allowed based on settings
            allowed_types = request.env.company.hlv_barcode_picking_type_ids
            if allowed_types and picking.picking_type_id not in allowed_types:
                return {'error': _('This picking type is not allowed to be processed via Mobile Barcode.')}
            return {'type': 'picking', 'id': picking.id, 'name': picking.name, 'state': picking.state}

        # 2. Check if it's a Product
        product = request.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if product:
            return {'type': 'product', 'id': product.id, 'name': product.display_name}

        # 3. Check if it's a Location
        location = request.env['stock.location'].search([('barcode', '=', barcode)], limit=1)
        if location:
            return {'type': 'location', 'id': location.id, 'name': location.display_name}

        # 4. Check if it's a Package
        package = request.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
        if package:
            return {'type': 'package', 'id': package.id, 'name': package.name}

        return {'error': _('Barcode "%s" not found in the system.', barcode)}

    @http.route('/hlv_mobile_barcode/get_picking_data', type='json', auth='user')
    def get_picking_data(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        lines = []
        # Group by move_id to show products
        for move in picking.move_ids_without_package:
            # Compute total qty_done for this move from move_line_ids
            qty_done = sum(line.qty_done for line in move.move_line_ids)
            lines.append({
                'move_id': move.id,
                'product_id': move.product_id.id,
                'product_name': move.product_id.display_name,
                'product_barcode': move.product_id.barcode,
                'product_uom_qty': move.product_uom_qty,
                'qty_done': qty_done,
                'uom_name': move.product_uom.name,
                'state': move.state,
            })
            
        return {
            'id': picking.id,
            'name': picking.name,
            'state': picking.state,
            'picking_type_code': picking.picking_type_id.code,
            'lines': lines,
        }

    @http.route('/hlv_mobile_barcode/process_barcode', type='json', auth='user')
    def process_barcode(self, picking_id, barcode):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state not in ['confirmed', 'assigned']:
            return {'error': _('Picking is not ready to process.')}

        product = request.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if not product:
            return {'error': _('Product barcode not found.')}

        # Find the move for this product
        move = picking.move_ids_without_package.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])
        if not move:
            return {'error': _('This product is not required in this picking, or already completed.')}
        
        move = move[0]
        # In Odoo, we typically increase qty_done on the move_line
        # If there's an existing move_line without package that is not fully done, use it
        move_line = move.move_line_ids.filtered(lambda ml: ml.qty_done < ml.quantity and not ml.result_package_id)
        if move_line:
            move_line[0].qty_done += 1
        else:
            # Create a new move line if none exists or all are full
            request.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'qty_done': 1,
            })
            
        return {'success': True, 'product_id': product.id, 'product_name': product.display_name}

    @http.route('/hlv_mobile_barcode/put_in_pack', type='json', auth='user')
    def put_in_pack(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
            
        try:
            res = picking.action_put_in_pack()
            # res might be a package or an action dict
            package_id = False
            if isinstance(res, dict) and res.get('res_model') == 'stock.quant.package':
                package_id = res.get('res_id')
            elif getattr(res, 'id', False):
                package_id = res.id
                
            return {
                'success': True, 
                'package_id': package_id,
                'print_after_pack': request.env.company.hlv_barcode_print_after_pack
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route('/hlv_mobile_barcode/validate_picking', type='json', auth='user')
    def validate_picking(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
        try:
            picking.button_validate()
            return {'success': True}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/hlv_mobile_barcode/get_inventory_lookup', type='json', auth='user')
    def get_inventory_lookup(self, lookup_type, record_id):
        quants = request.env['stock.quant']
        title = ""
        results = []
        reservations = []
        
        if lookup_type == 'product':
            product = request.env['product.product'].browse(record_id)
            title = product.display_name
            # Only internal locations
            quants = quants.search([('product_id', '=', product.id), ('location_id.usage', '=', 'internal')])
            for q in quants:
                results.append({
                    'location_name': q.location_id.display_name,
                    'quantity': q.quantity,
                    'package_name': q.package_id.name if q.package_id else '',
                })
                
            # Fetch reservations (picking holding this product)
            moves = request.env['stock.move'].search([
                ('product_id', '=', product.id),
                ('state', 'not in', ['done', 'cancel', 'draft']),
                ('picking_id', '!=', False)
            ])
            for m in moves:
                reservations.append({
                    'picking': m.picking_id.name,
                    'partner': m.picking_id.partner_id.name or '',
                    'demand': getattr(m, 'product_uom_qty', 0.0),
                    'reserved': getattr(m, 'quantity', getattr(m, 'reserved_availability', 0.0)),
                    'state_desc': dict(m._fields['state'].selection).get(m.state, m.state)
                })
                
        elif lookup_type == 'location':
            location = request.env['stock.location'].browse(record_id)
            title = location.display_name
            quants = quants.search([('location_id', '=', location.id)])
            for q in quants:
                results.append({
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'package_name': q.package_id.name if q.package_id else '',
                })
        elif lookup_type == 'package':
            package = request.env['stock.quant.package'].browse(record_id)
            title = package.name
            quants = quants.search([('package_id', '=', package.id)])
            for q in quants:
                results.append({
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'location_name': q.location_id.display_name,
                })
                
        return {'title': title, 'results': results, 'reservations': reservations}

    @http.route('/hlv_mobile_barcode/move_location', type='json', auth='user')
    def move_location(self, product_id, source_barcode, dest_barcode, qty):
        product = request.env['product.product'].browse(product_id)
        if not product.exists():
            return {'error': _('Product not found')}
            
        source_loc = request.env['stock.location'].search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Source location not found')}
            
        dest_loc = request.env['stock.location'].search([('barcode', '=', dest_barcode)], limit=1)
        if not dest_loc:
            return {'error': _('Destination location not found')}
            
        picking_type = request.env['stock.picking.type'].search([('code', '=', 'internal'), ('company_id', '=', request.env.company.id)], limit=1)
        if not picking_type:
            return {'error': _('Internal transfer picking type not found')}

        picking = request.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
        })
        
        move = request.env['stock.move'].create({
            'name': _('Mobile Move'),
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
        })
        
        picking.action_confirm()
        picking.button_validate()
        
        return {'success': True}
