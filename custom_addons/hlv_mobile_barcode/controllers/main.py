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
        if not barcode:
            return {'error': _('Mã vạch không hợp lệ')}
        barcode = barcode.strip()

        # 1. Check if it's a Picking
        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if picking:
            # Block PACK and OUT steps (keep only PICK allowed)
            pt_name = (picking.picking_type_id.name or '').lower()
            pt_code = (picking.picking_type_id.sequence_code or '').lower()
            if picking.picking_type_id.code == 'outgoing' or 'pack' in pt_name or 'pack' in pt_code:
                return {'error': _('Ứng dụng Mobile Barcode chỉ hỗ trợ xử lý phiếu PICK (Lấy hàng). Phiếu PACK và OUT được đảm nhận bởi phân hệ khác.')}

            # Enforce warehouse scan permission (can_view)
            use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
            if use_independent:
                Permission = request.env.get('hlv.barcode.user.permission')
            else:
                Permission = request.env.get('warehouse.user.permission')
            if Permission:
                warehouse = picking.picking_type_id.warehouse_id
                code = picking.picking_type_id.sequence_code
                if warehouse and code:
                    if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_view'):
                        return {'error': _('Bạn không có quyền quét/xem phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}

            # Check if picking type is allowed based on settings
            allowed_types = request.env.company.hlv_barcode_picking_type_ids
            if allowed_types and picking.picking_type_id not in allowed_types:
                return {'error': _('This picking type is not allowed to be processed via Mobile Barcode.')}
            warehouse_code = picking.picking_type_id.warehouse_id.code or 'HLV'
            return {'type': 'picking', 'id': picking.id, 'name': picking.name, 'state': picking.state, 'warehouse_code': warehouse_code}

        # 2. Check if it's a Product (Barcode or SKU/Internal Reference)
        product = request.env['product.product'].sudo().search(['|', ('barcode', '=', barcode), ('default_code', '=', barcode)], limit=1)
        if product:
            return {'type': 'product', 'id': product.id, 'name': product.display_name}

        # 3. Check if it's a Location (Barcode or Name)
        location = request.env['stock.location'].sudo().search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
        if location:
            warehouse_code = location.warehouse_id.code or 'HLV'
            return {'type': 'location', 'id': location.id, 'name': location.display_name, 'warehouse_code': warehouse_code}

        # 4. Check if it's a Package
        allow_package = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_package_scan', 'True') == 'True'
        if allow_package:
            package = request.env['stock.quant.package'].sudo().search([('name', '=', barcode)], limit=1)
            if package:
                warehouse_code = 'HLV'
                location = package.location_id
                if not location:
                    quant = request.env['stock.quant'].sudo().search([('package_id', '=', package.id)], limit=1)
                    if quant:
                        location = quant.location_id
                if location:
                    warehouse_code = location.warehouse_id.code or 'HLV'
                return {'type': 'package', 'id': package.id, 'name': package.name, 'warehouse_code': warehouse_code}

        return {'error': _('Mã vạch hoặc mã SKU "%s" không tồn tại trên hệ thống.', barcode)}

    @http.route('/hlv_mobile_barcode/get_picking_data', type='json', auth='user')
    def get_picking_data(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        # Block PACK and OUT steps (keep only PICK allowed)
        pt_name = (picking.picking_type_id.name or '').lower()
        pt_code = (picking.picking_type_id.sequence_code or '').lower()
        if picking.picking_type_id.code == 'outgoing' or 'pack' in pt_name or 'pack' in pt_code:
            return {'error': _('Ứng dụng Mobile Barcode chỉ hỗ trợ xử lý phiếu PICK (Lấy hàng). Phiếu PACK và OUT được đảm nhận bởi phân hệ khác.')}

        # Enforce warehouse scan permission (can_view)
        use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
        if use_independent:
            Permission = request.env.get('hlv.barcode.user.permission')
        else:
            Permission = request.env.get('warehouse.user.permission')
        if Permission:
            warehouse = picking.picking_type_id.warehouse_id
            code = picking.picking_type_id.sequence_code
            if warehouse and code:
                if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_view'):
                    return {'error': _('Bạn không có quyền xem phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}

        pt_code = (picking.picking_type_id.sequence_code or '').upper()
        pt_type = picking.picking_type_id.code
        is_putaway = False
        if pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code):
            is_putaway = True

        lines = []
        for move in picking.move_ids_without_package:
            if move.move_line_ids:
                for ml in move.move_line_ids:
                    if is_putaway:
                        loc_name = ml.location_dest_id.display_name
                    else:
                        loc_name = ml.location_id.display_name

                    package_name = ml.result_package_id.name or ml.package_id.name or False
                    lines.append({
                        'id': ml.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_name': move.product_id.display_name,
                        'product_barcode': move.product_id.barcode,
                        'product_uom_qty': move.product_uom_qty,
                        'qty_done': ml.quantity,
                        'uom_name': move.product_uom.name,
                        'state': move.state,
                        'location_name': loc_name,
                        'package_name': package_name,
                        'result_package_id': ml.result_package_id.id or False,
                        'package_id': ml.package_id.id or False,
                    })
            else:
                if is_putaway:
                    loc_name = move.location_dest_id.display_name
                else:
                    loc_name = move.location_id.display_name
                    
                lines.append({
                    'id': False,
                    'move_id': move.id,
                    'product_id': move.product_id.id,
                    'product_name': move.product_id.display_name,
                    'product_barcode': move.product_id.barcode,
                    'product_uom_qty': move.product_uom_qty,
                    'qty_done': 0.0,
                    'uom_name': move.product_uom.name,
                    'state': move.state,
                    'location_name': loc_name,
                    'package_name': False,
                    'result_package_id': False,
                    'package_id': False,
                })
        # Find linked Step 2 picking (only active for pure internal transfers e.g. INT -> IN)
        linked_picking_id = False
        linked_picking_name = False
        
        pt_code = (picking.picking_type_id.sequence_code or '').lower()
        pt_name = (picking.picking_type_id.name or '').lower()
        is_pure_int = 'int' in pt_code and not any(x in pt_code or x in pt_name for x in ['pick', 'pack', 'out'])
        
        if picking.picking_type_id.code == 'internal' and is_pure_int:
            # Method 1: Via stock moves chain
            dest_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(
                lambda p: p.id != picking.id and p.state not in ['cancel']
            )
            if dest_pickings:
                linked_picking = dest_pickings[0]
                linked_picking_id = linked_picking.id
                linked_picking_name = linked_picking.name
                
            # Method 2: Fallback to same procurement group (sharing group_id)
            if not linked_picking_id and picking.group_id:
                group_pickings = request.env['stock.picking'].sudo().search([
                    ('group_id', '=', picking.group_id.id),
                    ('id', '!=', picking.id),
                    ('state', 'not in', ['cancel'])
                ])
                in_pickings = group_pickings.filtered(
                    lambda p: 'IN' in (p.picking_type_id.sequence_code or '').upper() 
                    or p.picking_type_id.code in ['incoming', 'internal']
                )
                if in_pickings:
                    linked_picking = in_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                elif group_pickings:
                    linked_picking = group_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                    
            # Method 3: Fallback to origin matching current picking name
            if not linked_picking_id:
                origin_pickings = request.env['stock.picking'].sudo().search([
                    ('origin', '=', picking.name),
                    ('id', '!=', picking.id),
                    ('state', 'not in', ['cancel'])
                ], limit=1)
                if origin_pickings:
                    linked_picking_id = origin_pickings.id
                    linked_picking_name = origin_pickings.name
            
        return {
            'id': picking.id,
            'name': picking.name,
            'state': picking.state,
            'picking_type_code': picking.picking_type_id.code,
            'warehouse_code': picking.picking_type_id.warehouse_id.code or 'HLV',
            'lines': lines,
            'linked_picking_id': linked_picking_id,
            'linked_picking_name': linked_picking_name,
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
        return {'success': True, 'picking_id': picking_int.id, 'picking_name': picking_int.name, 'warehouse_code': picking_int.picking_type_id.warehouse_id.code or 'HLV'}

    @http.route('/hlv_mobile_barcode/process_barcode', type='json', auth='user')
    def process_barcode(self, picking_id, barcode, destination_location_id=None, last_product_id=None):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu này không thể xử lý thêm sản phẩm.')}

        # Enforce warehouse edit permission (can_edit)
        use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
        if use_independent:
            Permission = request.env.get('hlv.barcode.user.permission')
        else:
            Permission = request.env.get('warehouse.user.permission')
        if Permission:
            warehouse = picking.picking_type_id.warehouse_id
            code = picking.picking_type_id.sequence_code
            if warehouse and code:
                if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_edit'):
                    return {'error': _('Bạn không có quyền chỉnh sửa/quét hàng cho phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}

        if not barcode:
            return {'error': _('Mã vạch không hợp lệ')}
        barcode = barcode.strip()

        pt_code = (picking.picking_type_id.sequence_code or '').upper()
        pt_type = picking.picking_type_id.code
        is_putaway = False
        if pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code):
            is_putaway = True
        
        # 1. Try to find location first
        location = request.env['stock.location'].sudo().search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
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

        # 1.5. Try to find package
        package = request.env['stock.quant.package'].sudo().search([('name', '=', barcode)], limit=1)
        if package:
            allow_package = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_package_scan', 'True') == 'True'
            if not allow_package:
                return {'error': _('Tính năng quét Kiện hàng hiện đang bị tắt trong cấu hình hệ thống!')}
            # We found a package! Let's process the package contents in the picking.
            # A. Check if the picking has a move line for this package_id
            move_lines = picking.move_line_ids.filtered(lambda ml: (ml.package_id == package or ml.result_package_id == package) and ml.state not in ['done', 'cancel'])
            if move_lines:
                processed_lines = []
                for ml in move_lines:
                    ml.quantity = ml.quantity_product_uom or ml.reserved_qty or 1.0
                    processed_lines.append(f"{ml.quantity} x {ml.product_id.display_name}")
                return {
                    'success': True,
                    'product_name': f"Kiện hàng {package.name} (Đã quét: {', '.join(processed_lines)})",
                    'product_id': False,
                }
            
            # B. If no move lines for this package, search for the products inside the package (quants)
            quants = request.env['stock.quant'].sudo().search([('package_id', '=', package.id)])
            if quants:
                processed_products = []
                for quant in quants:
                    product_in_pkg = quant.product_id
                    qty_in_pkg = quant.quantity
                    if qty_in_pkg <= 0:
                        continue
                    
                    # Find a move for this product in the picking
                    move = picking.move_ids_without_package.filtered(
                        lambda m: m.product_id == product_in_pkg and m.state not in ['done', 'cancel']
                    )
                    if move:
                        move = move[0]
                        # Check limit to prevent over-scanning
                        current_qty_done = sum(ml.quantity for ml in move.move_line_ids)
                        target_qty = move.product_uom_qty
                        
                        # In case we can scan, determine how much of this package qty we can accept
                        acceptable_qty = qty_in_pkg
                        if target_qty > 0.0 and current_qty_done + acceptable_qty > target_qty:
                            acceptable_qty = max(0.0, target_qty - current_qty_done)
                            
                        if acceptable_qty <= 0:
                            continue
                            
                        # Update or create move line
                        move_line = move.move_line_ids.filtered(lambda ml: ml.quantity < ml.quantity_product_uom and not ml.result_package_id)
                        if move_line:
                            move_line[0].quantity += acceptable_qty
                        else:
                            request.env['stock.move.line'].create({
                                'move_id': move.id,
                                'picking_id': picking.id,
                                'product_id': product_in_pkg.id,
                                'product_uom_id': move.product_uom.id,
                                'quantity': acceptable_qty,
                                'location_id': picking.location_id.id,
                                'location_dest_id': picking.location_dest_id.id,
                            })
                        processed_products.append(f"{acceptable_qty} x {product_in_pkg.display_name}")
                
                if processed_products:
                    return {
                        'success': True,
                        'product_name': f"Kiện hàng {package.name} (Đã xử lý: {', '.join(processed_products)})",
                        'product_id': False,
                    }
            
            return {'error': _('Kiện hàng "%s" không chứa sản phẩm nào phù hợp với phiếu này.', package.name)}

        product = request.env['product.product'].sudo().search(['|', ('barcode', '=', barcode), ('default_code', '=', barcode)], limit=1)
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

        # Check limit to prevent over-scanning
        current_qty_done = sum(ml.quantity for ml in move.move_line_ids)
        if move.product_uom_qty > 0.0 and current_qty_done + 1 > move.product_uom_qty:
            return {'error': _('Sản phẩm "%s" đã quét đủ số lượng yêu cầu (%g/%g). Không thể quét thêm!', product.display_name, current_qty_done, move.product_uom_qty)}

        # Find an unpacked move line that is not in any package
        move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id)
        
        ml_dest_id = destination_location_id if (destination_location_id and is_putaway) else picking.location_dest_id.id
        ml_src_id = destination_location_id if (destination_location_id and not is_putaway) else picking.location_id.id
        
        # Check actual physical stock in the source location to prevent over-picking (only when picking, i.e., not is_putaway)
        if not is_putaway:
            # Calculate how many of this product have already been processed in this picking from this exact source location
            processed_qty_from_loc = sum(
                ml.quantity for ml in move.move_line_ids 
                if ml.location_id.id == ml_src_id
            )
            
            # Find the actual physical stock available at this source location (including all sub-locations)
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', ml_src_id)
            ])
            available_qty = sum(q.quantity for q in quants)
            
            if processed_qty_from_loc + 1 > available_qty:
                return {
                    'error': _(
                        'Số lượng quét (%g) vượt quá tồn kho thực tế tại vị trí "%s" (%g). Không thể quét thêm!',
                        processed_qty_from_loc + 1,
                        request.env['stock.location'].sudo().browse(ml_src_id).display_name,
                        available_qty
                    )
                }
        
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
    def update_move_line_qty(self, move_id=None, move_line_id=None, qty_change=None, new_qty=None):
        if move_line_id:
            move_line = request.env['stock.move.line'].browse(move_line_id)
            if not move_line.exists():
                return {'error': _('Không tìm thấy dòng dịch chuyển')}
            move = move_line.move_id
        elif move_id:
            move = request.env['stock.move'].browse(move_id)
            if not move.exists():
                return {'error': _('Không tìm thấy dòng sản phẩm')}
            move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id)
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
        else:
            return {'error': _('Thiếu tham số')}
            
        if move.picking_id.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu không ở trạng thái cho phép sửa số lượng')}

        # Enforce warehouse edit permission (can_edit)
        use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
        if use_independent:
            Permission = request.env.get('hlv.barcode.user.permission')
        else:
            Permission = request.env.get('warehouse.user.permission')
        if Permission:
            warehouse = move.picking_id.picking_type_id.warehouse_id
            code = move.picking_id.picking_type_id.sequence_code
            if warehouse and code:
                if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_edit'):
                    return {'error': _('Bạn không có quyền thay đổi số lượng phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}

        if new_qty is not None:
            new_val = float(new_qty)
        elif qty_change is not None:
            new_val = move_line.quantity + float(qty_change)
        else:
            return {'error': _('Thiếu tham số số lượng')}

        if new_val < 0:
            new_val = 0

        # Check limit to prevent over-scanning/updating
        other_lines_qty = sum(ml.quantity for ml in move.move_line_ids if ml.id != move_line.id)
        if move.product_uom_qty > 0.0 and (new_val + other_lines_qty) > move.product_uom_qty:
            return {'error': _('Số lượng vượt quá yêu cầu cho phép (%g/%g).', (new_val + other_lines_qty), move.product_uom_qty)}

        # If we are picking from a location, validate physical stock
        pt_code = (move.picking_id.picking_type_id.sequence_code or '').upper()
        pt_type = move.picking_id.picking_type_id.code
        is_putaway = False
        if pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code):
            is_putaway = True
            
        if not is_putaway:
            ml_src_id = move_line.location_id.id
            processed_qty_from_loc = sum(
                ml.quantity for ml in move.move_line_ids 
                if ml.location_id.id == ml_src_id and ml.id != move_line.id
            )
            
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', move.product_id.id),
                ('location_id', 'child_of', ml_src_id)
            ])
            available_qty = sum(q.quantity for q in quants)
            
            if (new_val + processed_qty_from_loc) > available_qty:
                return {
                    'error': _(
                        'Số lượng cập nhật (%g) vượt quá tồn kho thực tế tại vị trí "%s" (%g).',
                        new_val + processed_qty_from_loc,
                        move_line.location_id.display_name,
                        available_qty
                    )
                }

        move_line.quantity = new_val
        
        return {'success': True, 'new_qty': move_line.quantity}

    @http.route('/hlv_mobile_barcode/clear_quantities', type='json', auth='user')
    def clear_quantities(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Không thể xoá số lượng của phiếu này')}
            
        try:
            # 1. Handle stock move lines
            for ml in picking.move_line_ids:
                if ml.quantity_product_uom == 0.0:
                    # Dynamically created line -> delete it!
                    ml.unlink()
                else:
                    # Reserved line -> reset quantity and clear packaging
                    ml.write({
                        'quantity': 0.0,
                        'result_package_id': False
                    })
                    
            # 2. Handle stock moves that were created dynamically on the fly (demand = 0)
            dynamic_moves = picking.move_ids_without_package.filtered(lambda m: m.product_uom_qty == 0.0)
            if dynamic_moves:
                dynamic_moves._action_cancel()
                dynamic_moves.unlink()
                
            return {'success': True}
        except Exception as e:
            return {'error': _('Lỗi khi làm mới: %s', str(e))}

    @http.route('/hlv_mobile_barcode/delete_move', type='json', auth='user')
    def delete_move(self, move_id=None, move_line_id=None):
        if move_line_id:
            move_line = request.env['stock.move.line'].browse(move_line_id)
            if not move_line.exists():
                return {'success': True}
            picking = move_line.picking_id
            move = move_line.move_id
        elif move_id:
            move = request.env['stock.move'].browse(move_id)
            if not move.exists():
                return {'success': True}
            picking = move.picking_id
            move_line = False
        else:
            return {'error': _('Thiếu tham số')}
            
        if picking.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu không ở trạng thái cho phép xóa sản phẩm')}

        # Enforce warehouse delete permission (can_delete)
        use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
        if use_independent:
            Permission = request.env.get('hlv.barcode.user.permission')
        else:
            Permission = request.env.get('warehouse.user.permission')
        if Permission:
            warehouse = picking.picking_type_id.warehouse_id
            code = picking.picking_type_id.sequence_code
            if warehouse and code:
                if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_delete'):
                    return {'error': _('Bạn không có quyền xóa sản phẩm trên phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}
            
        try:
            if move_line:
                move_line.unlink()
                if not move.move_line_ids and move.product_uom_qty == 0.0:
                    move._action_cancel()
                    move.unlink()
            else:
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
            
            package_id = False
            package_name = ""
            if isinstance(res, dict) and res.get('res_model') == 'stock.quant.package':
                package_id = res.get('res_id')
            elif getattr(res, 'id', False):
                package_id = res.id
                
            # Fallback to scanning picking move lines for the newest package
            packages = picking.move_line_ids.mapped('result_package_id')
            if packages:
                packages = packages.sorted(key=lambda p: p.id, reverse=True)
                if not package_id:
                    package_id = packages[0].id
                if not package_name:
                    package_name = packages[0].name

            return {
                'success': True, 
                'package_id': package_id,
                'package_name': package_name,
                'print_after_pack': request.env.company.hlv_barcode_print_after_pack
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route('/hlv_mobile_barcode/unpack_move_line', type='json', auth='user')
    def unpack_move_line(self, move_line_id):
        ml = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not ml.exists():
            return {'error': _('Không tìm thấy dòng dịch chuyển')}
            
        if ml.picking_id.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu không ở trạng thái cho phép chỉnh sửa')}
            
        # Clear packages
        ml.write({
            'result_package_id': False,
            'package_id': False
        })
        return {'success': True}

    @http.route('/hlv_mobile_barcode/validate_picking', type='json', auth='user')
    def validate_picking(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        # Enforce warehouse validation permission (can_confirm)
        use_independent = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_use_independent_permissions') == 'True'
        if use_independent:
            Permission = request.env.get('hlv.barcode.user.permission')
        else:
            Permission = request.env.get('warehouse.user.permission')
        if Permission:
            warehouse = picking.picking_type_id.warehouse_id
            code = picking.picking_type_id.sequence_code
            if warehouse and code:
                if not Permission.check_picking_operation(request.env.user, warehouse, code, 'can_confirm'):
                    return {'error': _('Bạn không có quyền xác nhận phiếu %s tại kho "%s". Vui lòng liên hệ Admin!', code, warehouse.name)}
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
            product = request.env['product.product'].sudo().browse(record_id)
            title = product.display_name
            # Use sudo() to bypass company/location security rules in lookup view so that warehouse keepers always see actual inventory
            quants = quants.sudo().search([('product_id', '=', product.id), ('location_id.usage', '=', 'internal'), ('quantity', '>', 0.0)])
            for q in quants:
                results.append({
                    'location_id': q.location_id.id,
                    'quant_id': q.id,
                    'location_name': q.location_id.display_name,
                    'quantity': q.quantity,
                    'package_name': q.package_id.name if q.package_id else '',
                })
                
            # Fetch reservations (picking holding this product)
            # Use sudo() to ensure reservation visibility regardless of record rules
            moves = request.env['stock.move'].sudo().search([
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
            location = request.env['stock.location'].sudo().browse(record_id)
            title = location.display_name
            location_barcode = location.barcode or location.name
            warehouse_code = location.warehouse_id.code or 'HLV'
            # Use child_of to aggregate stock in all sub-locations (essential for large warehouses like KBC)
            # Use sudo() to bypass company/location constraints so all actual stock is displayed
            quants = quants.sudo().search([('location_id', 'child_of', location.id), ('quantity', '>', 0.0)])
            for q in quants:
                results.append({
                    'product_id': q.product_id.id,
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'package_name': q.package_id.name if q.package_id else '',
                    'quant_id': q.id,
                    'location_name': q.location_id.display_name,
                })
            return {'title': title, 'location_barcode': location_barcode, 'location_name': title, 'results': results, 'reservations': reservations, 'warehouse_code': warehouse_code}
        elif lookup_type == 'package':
            package = request.env['stock.quant.package'].sudo().browse(record_id)
            title = package.name
            warehouse_code = 'HLV'
            location = package.location_id
            # Use sudo() to bypass company constraints on packages
            quants = quants.sudo().search([('package_id', '=', package.id), ('quantity', '>', 0.0)])
            for q in quants:
                results.append({
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'location_name': q.location_id.display_name,
                })
                if not location and q.location_id:
                    location = q.location_id
            if location:
                warehouse_code = location.warehouse_id.code or 'HLV'
            return {'title': title, 'results': results, 'reservations': reservations, 'warehouse_code': warehouse_code}
                
        return {'title': title, 'results': results, 'reservations': reservations}

    @http.route('/hlv_mobile_barcode/validate_location', type='json', auth='user')
    def validate_location(self, barcode):
        if not barcode:
            return {'error': _('Mã vạch không hợp lệ')}
        barcode = barcode.strip()
        location = request.env['stock.location'].sudo().search([('barcode', '=', barcode)], limit=1)
        if not location:
            location = request.env['stock.location'].sudo().search([('name', '=', barcode)], limit=1)
        
        if location:
            return {'success': True, 'location_name': location.display_name, 'location_barcode': location.barcode or location.name}
        return {'error': _('Không tìm thấy vị trí lấy hàng hợp lệ.')}

    @http.route('/hlv_mobile_barcode/move_location', type='json', auth='user')
    def move_location(self, product_id, source_barcode, qty):
        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'error': _('Không tìm thấy sản phẩm')}
            
        if not source_barcode:
            return {'error': _('Mã vạch nguồn không hợp lệ')}
        source_barcode = source_barcode.strip()
        source_loc = request.env['stock.location'].sudo().search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        company_id = request.env.company.id
        
        # Get Transit Location
        transit_loc = request.env['stock.location'].sudo().search([
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
            picking_type_int = request.env['stock.picking.type'].sudo().search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            picking_type_in = request.env['stock.picking.type'].sudo().search([('code', '=', 'incoming'), ('company_id', '=', company_id)], limit=1)
        
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
            dest_loc = request.env['stock.location'].sudo().search([('usage', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            
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
            
        if not source_barcode:
            return {'error': _('Mã vạch nguồn không hợp lệ')}
        source_barcode = source_barcode.strip()
        source_loc = request.env['stock.location'].sudo().search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        company_id = request.env.company.id
        
        # Get Transit Location
        transit_loc = request.env['stock.location'].sudo().search([
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
            picking_type_int = request.env['stock.picking.type'].sudo().search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            picking_type_in = request.env['stock.picking.type'].sudo().search([('code', '=', 'incoming'), ('company_id', '=', company_id)], limit=1)
        
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
            dest_loc = request.env['stock.location'].sudo().search([('usage', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            
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
