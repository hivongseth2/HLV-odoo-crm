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
            # Compute total quantity for this move from move_line_ids (Odoo 18 uses quantity)
            qty_done = sum(line.quantity for line in move.move_line_ids)
            
            # Determine location name
            last_ml = move.move_line_ids and move.move_line_ids[-1] or False
            loc_name = False
            if last_ml:
                if picking.picking_type_id.code in ['incoming', 'internal']:
                    loc_name = last_ml.location_dest_id.display_name
                else:
                    loc_name = last_ml.location_id.display_name
                    
            lines.append({
                'move_id': move.id,
                'product_id': move.product_id.id,
                'product_name': move.product_id.display_name,
                'product_barcode': move.product_id.barcode,
                'product_uom_qty': move.product_uom_qty,
                'qty_done': qty_done,
                'uom_name': move.product_uom.name,
                'state': move.state,
                'location_name': loc_name,
            })
            
        return {
            'id': picking.id,
            'name': picking.name,
            'state': picking.state,
            'picking_type_code': picking.picking_type_id.code,
            'lines': lines,
        }

    @http.route('/hlv_mobile_barcode/create_empty_int', type='json', auth='user')
    def create_empty_int(self, location_id):
        source_loc = request.env['stock.location'].browse(location_id)
        if not source_loc.exists():
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        company_id = request.env.company.id
        transit_loc = request.env['stock.location'].search([
            ('usage', '=', 'transit'), 
            ('company_id', 'in', [False, company_id])
        ], limit=1)
        
        if not transit_loc:
            return {'error': _('Không tìm thấy kho trung chuyển (Transit Location)')}
            
        warehouse = source_loc.warehouse_id
        if not warehouse:
            warehouse = request.env['stock.warehouse'].search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
            
        picking_type_int = request.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('sequence_code', '=', 'INT'),
            ('company_id', '=', company_id),
            ('warehouse_id', '=', warehouse.id if warehouse else False)
        ], limit=1)
        
        if not picking_type_int and warehouse and warehouse.int_type_id:
            picking_type_int = warehouse.int_type_id
            
        if not picking_type_int:
            picking_type_int = request.env['stock.picking.type'].search([
                ('code', '=', 'internal'), 
                ('company_id', '=', company_id),
                ('warehouse_id', '=', warehouse.id if warehouse else False)
            ], limit=1)
            if not picking_type_int:
                picking_type_int = request.env['stock.picking.type'].search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            
        if not picking_type_int:
            return {'error': _('Chưa cấu hình Operation Types (INT)')}

        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
        })
        
        # Keep it in draft so user can add lines
        return {'success': True, 'picking_id': picking_int.id, 'picking_name': picking_int.name}

    @http.route('/hlv_mobile_barcode/process_barcode', type='json', auth='user')
    def process_barcode(self, picking_id, barcode, destination_location_id=None, last_product_id=None):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu này không thể xử lý thêm sản phẩm.')}

        is_putaway = picking.picking_type_id.code in ['incoming', 'internal']
        
        # 1. Try to find location first
        location = request.env['stock.location'].search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
        if location:
            res = {'type': 'location', 'location_id': location.id, 'location_name': location.display_name, 'is_putaway': is_putaway}
            if last_product_id:
                move = picking.move_ids_without_package.filtered(lambda m: m.product_id.id == last_product_id and m.state not in ['done', 'cancel'])
                if move:
                    move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id)
                    if move_line:
                        if is_putaway:
                            move_line[-1].location_dest_id = location.id
                        else:
                            move_line[-1].location_id = location.id
                        res['updated_product_id'] = last_product_id
            return res

        product = request.env['product.product'].search([('barcode', '=', barcode)], limit=1)
        if not product:
            return {'error': _('Không tìm thấy mã vạch hợp lệ (Sản phẩm hoặc Vị trí).')}

        # Find the move for this product
        move = picking.move_ids_without_package.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])
        
        if not move:
            # Create a new move on the fly
            move = request.env['stock.move'].create({
                'name': product.display_name,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_qty': 0.0,
                'product_uom': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
            
            # If picking was draft, maybe we need to confirm it so it gets move_line_ids?
            # Or we can just create the move_line manually. In Odoo 17+, moves usually get confirmed later.
            # But let's confirm the picking if it's draft so Odoo's internal state is happy.
            if picking.state == 'draft':
                picking.action_confirm()
                # Re-fetch move as action_confirm might replace/merge it
                move = picking.move_ids_without_package.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])
                if not move:
                    return {'error': _('Lỗi hệ thống khi tạo sản phẩm mới.')}
                move = move[0]
        else:
            move = move[0]

        # In Odoo 17/18, qty_done is replaced by quantity
        move_line = move.move_line_ids.filtered(lambda ml: ml.quantity < ml.quantity_product_uom and not ml.result_package_id)
        
        ml_dest_id = destination_location_id if (destination_location_id and is_putaway) else picking.location_dest_id.id
        ml_src_id = destination_location_id if (destination_location_id and not is_putaway) else picking.location_id.id
        
        if move_line:
            # Check if location matches, otherwise we might need a new move line
            last_ml = move_line[-1]
            if (is_putaway and destination_location_id and last_ml.location_dest_id.id != destination_location_id) or \
               (not is_putaway and destination_location_id and last_ml.location_id.id != destination_location_id):
                # Locations differ, create a new move line
                request.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': ml_src_id,
                    'location_dest_id': ml_dest_id,
                    'quantity': 1,
                })
            else:
                last_ml.quantity += 1
        else:
            # Create a new move line if none exists or all are full
            request.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': ml_src_id,
                'location_dest_id': ml_dest_id,
                'quantity': 1,
            })
            
        return {'success': True, 'type': 'product', 'product_id': product.id, 'product_name': product.display_name}

    @http.route('/hlv_mobile_barcode/update_move_line_qty', type='json', auth='user')
    def update_move_line_qty(self, move_id, qty_change=None, new_qty=None):
        move = request.env['stock.move'].browse(move_id)
        if not move.exists():
            return {'error': _('Không tìm thấy dòng sản phẩm')}
            
        if move.picking_id.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu không ở trạng thái cho phép sửa số lượng')}

        # Odoo 18 uses quantity on move_line
        # Find or create a move_line
        move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id)
        if not move_line:
            move_line = request.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': move.picking_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'quantity': 0,
            })
        else:
            move_line = move_line[0]

        if new_qty is not None:
            new_val = float(new_qty)
        elif qty_change is not None:
            new_val = move_line.quantity + float(qty_change)
        else:
            return {'error': _('Thiếu tham số số lượng')}

        if new_val < 0:
            new_val = 0

        move_line.quantity = new_val
        
        return {'success': True, 'new_qty': move_line.quantity}

    @http.route('/hlv_mobile_barcode/clear_quantities', type='json', auth='user')
    def clear_quantities(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if picking.exists() and picking.state in ['draft', 'confirmed', 'assigned']:
            # In Odoo 18, quantity is the done quantity on move_line
            picking.move_line_ids.write({'quantity': 0})
            return {'success': True}
        return {'error': _('Không thể xoá số lượng của phiếu này')}

    @http.route('/hlv_mobile_barcode/delete_move', type='json', auth='user')
    def delete_move(self, move_id):
        move = request.env['stock.move'].browse(move_id)
        if not move.exists():
            return {'success': True} # Already deleted
            
        if move.picking_id.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu không ở trạng thái cho phép xóa sản phẩm')}
            
        try:
            move._action_cancel()
            move.unlink()
            return {'success': True}
        except Exception as e:
            return {'error': _('Lỗi khi xóa: %s', str(e))}

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
                    'location_id': q.location_id.id,
                    'quant_id': q.id,
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
                    'picking_id': m.picking_id.id,
                    'partner': m.picking_id.partner_id.name or '',
                    'demand': getattr(m, 'product_uom_qty', 0.0),
                    'reserved': getattr(m, 'quantity', getattr(m, 'reserved_availability', 0.0)),
                    'state_desc': dict(m._fields['state'].selection).get(m.state, m.state)
                })
                
        elif lookup_type == 'location':
            location = request.env['stock.location'].browse(record_id)
            title = location.display_name
            location_barcode = location.barcode or location.name
            quants = quants.search([('location_id', '=', location.id)])
            for q in quants:
                results.append({
                    'product_id': q.product_id.id,
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'package_name': q.package_id.name if q.package_id else '',
                    'quant_id': q.id,
                })
            return {'title': title, 'location_barcode': location_barcode, 'location_name': title, 'results': results, 'reservations': reservations}
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

    @http.route('/hlv_mobile_barcode/validate_location', type='json', auth='user')
    def validate_location(self, barcode):
        location = request.env['stock.location'].search([('barcode', '=', barcode)], limit=1)
        if not location:
            location = request.env['stock.location'].search([('name', '=', barcode)], limit=1)
        
        if location:
            return {'success': True, 'location_name': location.display_name, 'location_barcode': location.barcode or location.name}
        return {'error': _('Không tìm thấy vị trí lấy hàng hợp lệ.')}

    @http.route('/hlv_mobile_barcode/move_location', type='json', auth='user')
    def move_location(self, product_id, source_barcode, qty):
        product = request.env['product.product'].browse(product_id)
        if not product.exists():
            return {'error': _('Không tìm thấy sản phẩm')}
            
        source_loc = request.env['stock.location'].search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        company_id = request.env.company.id
        
        # Get Transit Location
        transit_loc = request.env['stock.location'].search([
            ('usage', '=', 'transit'), 
            ('company_id', 'in', [False, company_id])
        ], limit=1)
        
        if not transit_loc:
            return {'error': _('Không tìm thấy kho trung chuyển (Transit Location)')}
            
        warehouse = source_loc.warehouse_id
        if warehouse and warehouse.int_type_id and warehouse.in_type_id:
            picking_type_int = warehouse.int_type_id
            picking_type_in = warehouse.in_type_id
        else:
            picking_type_int = request.env['stock.picking.type'].search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            picking_type_in = request.env['stock.picking.type'].search([('code', '=', 'incoming'), ('company_id', '=', company_id)], limit=1)
        
        if not picking_type_int or not picking_type_in:
            return {'error': _('Chưa cấu hình Operation Types (INT, IN)')}

        # 1. Create and Validate INT picking (Source -> Transit)
        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
        })
        
        request.env['stock.move'].create({
            'name': _('Mobile Move OUT'),
            'picking_id': picking_int.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
        })
        
        picking_int.action_confirm()
        picking_int.button_validate()
        
        # 2. Create IN picking (Transit -> Destination)
        dest_loc = picking_type_in.default_location_dest_id
        if not dest_loc:
            dest_loc = request.env['stock.location'].search([('usage', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            
        picking_in = request.env['stock.picking'].create({
            'picking_type_id': picking_type_in.id,
            'location_id': transit_loc.id,
            'location_dest_id': dest_loc.id,
        })
        
        request.env['stock.move'].create({
            'name': _('Mobile Move IN'),
            'picking_id': picking_in.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': transit_loc.id,
            'location_dest_id': dest_loc.id,
        })
        
        picking_in.action_confirm()
        
        return {'success': True, 'in_picking_name': picking_in.name}

    @http.route('/hlv_mobile_barcode/move_location_batch', type='json', auth='user')
    def move_location_batch(self, source_barcode, lines, pack=False):
        if not lines:
            return {'error': _('Không có sản phẩm nào để chuyển')}
            
        source_loc = request.env['stock.location'].search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        company_id = request.env.company.id
        
        # Get Transit Location
        transit_loc = request.env['stock.location'].search([
            ('usage', '=', 'transit'), 
            ('company_id', 'in', [False, company_id])
        ], limit=1)
        
        if not transit_loc:
            return {'error': _('Không tìm thấy kho trung chuyển (Transit Location)')}
            
        warehouse = source_loc.warehouse_id
        if warehouse and warehouse.int_type_id and warehouse.in_type_id:
            picking_type_int = warehouse.int_type_id
            picking_type_in = warehouse.in_type_id
        else:
            picking_type_int = request.env['stock.picking.type'].search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            picking_type_in = request.env['stock.picking.type'].search([('code', '=', 'incoming'), ('company_id', '=', company_id)], limit=1)
        
        if not picking_type_int or not picking_type_in:
            return {'error': _('Chưa cấu hình Operation Types (INT, IN)')}

        # 1. Create INT picking (Source -> Transit)
        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
        })
        
        for line in lines:
            product = request.env['product.product'].browse(line['product_id'])
            if not product.exists():
                continue
            request.env['stock.move'].create({
                'name': _('Mobile Batch Move OUT: %s', product.display_name),
                'picking_id': picking_int.id,
                'product_id': product.id,
                'product_uom_qty': line['qty'],
                'product_uom': product.uom_id.id,
                'location_id': source_loc.id,
                'location_dest_id': transit_loc.id,
            })
        
        picking_int.action_confirm()
        
        package_name = False
        if pack:
            # Set quantity so put_in_pack knows what to pack
            for move in picking_int.move_ids_without_package:
                move.quantity = move.product_uom_qty
            
            try:
                res = picking_int.action_put_in_pack()
                if isinstance(res, dict) and res.get('res_model') == 'stock.quant.package':
                    package_id = res.get('res_id')
                    package = request.env['stock.quant.package'].browse(package_id)
                    package_name = package.name
                elif getattr(res, 'id', False):
                    package_name = res.name
            except Exception as e:
                return {'error': _('Lỗi khi đóng gói: %s', str(e))}
                
        picking_int.button_validate()
        
        # 2. Create IN picking (Transit -> Destination)
        dest_loc = picking_type_in.default_location_dest_id
        if not dest_loc:
            dest_loc = request.env['stock.location'].search([('usage', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            
        picking_in = request.env['stock.picking'].create({
            'picking_type_id': picking_type_in.id,
            'location_id': transit_loc.id,
            'location_dest_id': dest_loc.id,
        })
        
        for line in lines:
            product = request.env['product.product'].browse(line['product_id'])
            if not product.exists():
                continue
            request.env['stock.move'].create({
                'name': _('Mobile Batch Move IN: %s', product.display_name),
                'picking_id': picking_in.id,
                'product_id': product.id,
                'product_uom_qty': line['qty'],
                'product_uom': product.uom_id.id,
                'location_id': transit_loc.id,
                'location_dest_id': dest_loc.id,
            })
        
        picking_in.action_confirm()
        
        return {'success': True, 'in_picking_name': picking_in.name, 'package_name': package_name}
