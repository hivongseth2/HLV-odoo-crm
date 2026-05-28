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
        if pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
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
        # Find linked Step 2 picking (only active for pure internal transfers e.g. INT -> IN / STOR)
        linked_picking_id = False
        linked_picking_name = False
        
        if picking.picking_type_id.code == 'internal':
            # Method 1 (highest priority per user rule): Chatter message
            # Odoo automatically posts a message in chatter when a step-2 picking is created from a step-1 picking.
            # e.g., "This transfer has been created from: KBC/INT/02042"
            # We search for mail.message containing the source picking name in model='stock.picking' and retrieve res_id.
            messages = request.env['mail.message'].sudo().search([
                ('model', '=', 'stock.picking'),
                ('body', 'like', picking.name)
            ], order='id desc', limit=10)
            
            for msg in messages:
                target_picking = request.env['stock.picking'].sudo().browse(msg.res_id)
                if target_picking.exists() and target_picking.id != picking.id and target_picking.state not in ['cancel']:
                    linked_picking_id = target_picking.id
                    linked_picking_name = target_picking.name
                    break

            # Method 2: Via stock moves chain (Odoo native stock move chain)
            if not linked_picking_id:
                dest_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(
                    lambda p: p.id != picking.id and p.state not in ['cancel']
                )
                if dest_pickings:
                    linked_picking = dest_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                    
            # Method 3: Same procurement group (sharing group_id)
            if not linked_picking_id and picking.group_id:
                group_pickings = request.env['stock.picking'].sudo().search([
                    ('group_id', '=', picking.group_id.id),
                    ('id', '!=', picking.id),
                    ('state', 'not in', ['cancel'])
                ])
                in_pickings = group_pickings.filtered(
                    lambda p: 'IN' in (p.picking_type_id.sequence_code or '').upper() 
                    or 'STOR' in (p.picking_type_id.sequence_code or '').upper()
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
                    
            # Method 4: Origin matching current picking name (case-insensitive substring or exact match)
            if not linked_picking_id:
                origin_pickings = request.env['stock.picking'].sudo().search([
                    '|',
                    ('origin', '=', picking.name),
                    ('origin', 'ilike', picking.name),
                    ('id', '!=', picking.id),
                    ('state', 'not in', ['cancel'])
                ], limit=1)
                if origin_pickings:
                    linked_picking_id = origin_pickings.id
                    linked_picking_name = origin_pickings.name
            
        packages = []
        all_result_pkgs = picking.move_line_ids.mapped('result_package_id')
        for pkg in all_result_pkgs:
            pkg_mls = picking.move_line_ids.filtered(
                lambda ml: ml.result_package_id.id == pkg.id
            )
            total_done = sum(ml.quantity for ml in pkg_mls)
            package_lines = [{
                'move_line_id': ml.id,
                'product_name': ml.product_id.display_name,
                'product_barcode': ml.product_id.barcode or '',
                'qty_done': ml.quantity,
                'uom': ml.product_uom_id.name,
            } for ml in pkg_mls if ml.quantity > 0]
            if package_lines:
                packages.append({
                    'id': pkg.id,
                    'name': pkg.name,
                    'total_done': total_done,
                    'lines': package_lines,
                })

        return {
            'id': picking.id,
            'name': picking.name,
            'state': picking.state,
            'picking_type_code': picking.picking_type_id.code,
            'warehouse_code': picking.picking_type_id.warehouse_id.code or 'HLV',
            'location_id': picking.location_id.id,
            'location_name': picking.location_id.display_name or picking.location_id.name,
            'lines': lines,
            'packages': packages,
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

        partner_id = False
        if warehouse and warehouse.partner_id:
            partner_id = warehouse.partner_id.id

        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
            'partner_id': partner_id,
        })
        
        # Keep it in draft so user can add lines
        return {
            'success': True, 
            'picking_id': picking_int.id, 
            'picking_name': picking_int.name, 
            'warehouse_code': picking_int.picking_type_id.warehouse_id.code or 'HLV',
            'location_id': source_loc.id,
            'location_name': source_loc.display_name or source_loc.name
        }

    @http.route('/hlv_mobile_barcode/process_barcode', type='json', auth='user')
    def process_barcode(self, picking_id, barcode, destination_location_id=None, last_product_id=None, location_mode=None):
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
        if location_mode == 'dest':
            is_putaway = True
        elif location_mode == 'source':
            is_putaway = False
        else:
            if pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
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

        # Check limit to prevent over-scanning (demand-based)
        current_qty_done = sum(ml.quantity for ml in move.move_line_ids)
        if move.product_uom_qty > 0.0 and current_qty_done + 1 > move.product_uom_qty:
            return {'error': _('Sản phẩm "%s" đã quét đủ số lượng yêu cầu (%g/%g). Không thể quét thêm!', product.display_name, current_qty_done, move.product_uom_qty)}

        # Find an unpacked move line that is not in any package
        move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id)
        
        ml_dest_id = destination_location_id if (destination_location_id and is_putaway) else picking.location_dest_id.id
        ml_src_id = destination_location_id if (destination_location_id and not is_putaway) else picking.location_id.id
        
        # Check actual physical stock in the source location to prevent over-picking (only when picking, i.e., not is_putaway)
        if not is_putaway:
            # Find the actual physical stock available at this source location (including all sub-locations)
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', ml_src_id)
            ])
            available_qty = sum(q.quantity for q in quants)
            
            # Calculate total processed qty for this product across ALL moves in this picking
            # that source from the same location tree (parent + children)
            source_loc = request.env['stock.location'].sudo().browse(ml_src_id)
            child_loc_ids = request.env['stock.location'].sudo().search([('id', 'child_of', ml_src_id)]).ids
            processed_qty_from_loc = sum(
                ml.quantity for ml in picking.move_line_ids
                if ml.product_id == product and ml.location_id.id in child_loc_ids
            )
            
            if available_qty <= 0:
                return {
                    'error': _(
                        'Sản phẩm "%s" không có tồn kho tại vị trí "%s" (bao gồm các vị trí con). Không thể quét!',
                        product.display_name,
                        source_loc.display_name
                    )
                }
            
            if processed_qty_from_loc + 1 > available_qty:
                return {
                    'error': _(
                        'Số lượng quét (%g) vượt quá tồn kho thực tế tại vị trí "%s" (%g). Không thể quét thêm!',
                        processed_qty_from_loc + 1,
                        source_loc.display_name,
                        available_qty
                    )
                }
            
            # Resolve actual child location where stock exists for accurate move line creation
            # If stock is not directly at ml_src_id but at a child location, use the child location
            actual_src_id = ml_src_id
            direct_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', ml_src_id),
                ('quantity', '>', 0)
            ])
            if not direct_quants:
                # No stock at exact location, find the child location that has stock
                child_quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', 'child_of', ml_src_id),
                    ('quantity', '>', 0)
                ], order='quantity desc')
                if child_quants:
                    # Use the child location with the most stock
                    actual_src_id = child_quants[0].location_id.id
            
            ml_src_id = actual_src_id
        
        if move_line:
            # Check if location matches, otherwise we might need a new move line
            last_ml = move_line[-1]
            if (is_putaway and destination_location_id and last_ml.location_dest_id.id != destination_location_id) or \
               (not is_putaway and destination_location_id and last_ml.location_id.id != ml_src_id):
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
            # Check across ALL move lines in the picking for this product (not just this one move)
            child_loc_ids = request.env['stock.location'].sudo().search([('id', 'child_of', ml_src_id)]).ids
            processed_qty_from_loc = sum(
                ml.quantity for ml in move.picking_id.move_line_ids
                if ml.product_id == move.product_id and ml.location_id.id in child_loc_ids and ml.id != move_line.id
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

    @http.route('/hlv_mobile_barcode/clear_and_cancel_picking', type='json', auth='user')
    def clear_and_cancel_picking(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'success': True}
            
        if picking.state == 'done':
            return {'error': _('Phiếu đã hoàn thành, không thể hủy.')}
            
        try:
            # 1. Clear quantities first to release any dynamic scanning
            self.clear_quantities(picking_id)
            
            # 2. Cancel picking to release all reserves
            if picking.state not in ['cancel']:
                picking.action_cancel()
                
            return {'success': True}
        except Exception as e:
            return {'error': _('Lỗi khi hủy phiếu: %s', str(e))}

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

        # Nếu là phiếu chuyển nội bộ 2 bước (INT) và chưa có partner_id, tự động gán partner của kho nguồn (location_id)
        if picking.picking_type_id.code == 'internal' and not picking.partner_id:
            is_transit = False
            complete_name = (picking.location_dest_id.complete_name or "").strip().lower()
            accepted_names = ["physical locations/inter-warehouse transit", "vị trí vật lý/trung chuyển liên kho", "kho trung gian"]
            if any(complete_name.endswith(name) or complete_name == name for name in accepted_names) or picking.location_dest_id.usage == 'transit':
                is_transit = True
                
            if is_transit:
                warehouse = picking.location_id.warehouse_id
                if not warehouse:
                    warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', picking.location_id.id)], limit=1)
                
                if warehouse and warehouse.partner_id:
                    picking.sudo().write({'partner_id': warehouse.partner_id.id})

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
        partner_id = False
        actual_warehouse = warehouse
        if not actual_warehouse:
            actual_warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
        if actual_warehouse and actual_warehouse.partner_id:
            partner_id = actual_warehouse.partner_id.id

        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
            'partner_id': partner_id,
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
        if hasattr(picking_int, 'second_transfer_created'):
            picking_int.write({'second_transfer_created': True})
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
        partner_id = False
        actual_warehouse = warehouse
        if not actual_warehouse:
            actual_warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
        if actual_warehouse and actual_warehouse.partner_id:
            partner_id = actual_warehouse.partner_id.id

        picking_int = request.env['stock.picking'].create({
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': transit_loc.id,
            'partner_id': partner_id,
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
                
        if hasattr(picking_int, 'second_transfer_created'):
            picking_int.write({'second_transfer_created': True})
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

    @http.route('/hlv_mobile_barcode/get_package_details', type='json', auth='user')
    def get_package_details(self, picking_id, package_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        Package = request.env['stock.quant.package']
        package = Package.sudo().browse(package_id)

        if not package.exists():
            return {'error': _('Gói hàng không tồn tại!')}

        # Lấy move_lines của package này trong picking hiện tại
        move_lines = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('result_package_id', '=', package.id)
        ])

        # Lấy TẤT CẢ move_lines của picking
        all_move_lines = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id)
        ])

        items = []
        for ml in move_lines:
            qty = float(ml.quantity or 0)
            if qty <= 0:
                continue
            
            product_barcode = ml.product_id.barcode or ''
            product_sku = ml.product_id.default_code or ''

            items.append({
                'move_line_id': ml.id,
                'product_id': ml.product_id.id,
                'product_name': ml.product_id.display_name,
                'product_sku': product_sku,
                'product_barcode': product_barcode,
                'qty_done': qty,
                'uom': ml.product_uom_id.name,
            })

        # Lấy các packages khác trong picking này
        all_packages_in_picking = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('result_package_id', '!=', False)
        ]).mapped('result_package_id')

        other_packages = []
        for pkg in all_packages_in_picking:
            if pkg.id != package.id:
                other_packages.append({
                    'package_id': pkg.id,
                    'package_name': pkg.name or f"PACK{pkg.id}"
                })

        # Xử lý sản phẩm lẻ chưa được đóng gói (available items)
        all_items = []
        product_map = {}

        # Quét từ Move Lines
        for ml in all_move_lines:
            pid = ml.product_id.id
            if pid not in product_map:
                product_map[pid] = {
                    'product_name': ml.product_id.display_name,
                    'product_sku': ml.product_id.default_code or '', 
                    'product_barcode': ml.product_id.barcode or '',
                    'move_line_id': ml.id,
                    'total_scanned': 0.0,
                    'unassigned_scanned': 0.0,
                    'demand': 0.0
                }
            
            qty = float(ml.quantity or 0)
            product_map[pid]['total_scanned'] += qty
            
            if not ml.result_package_id and qty > 0:
                product_map[pid]['unassigned_scanned'] += qty

        # Quét từ Demand
        for move in picking.move_ids_without_package:
             pid = move.product_id.id
             if pid in product_map:
                 product_map[pid]['demand'] += move.product_uom_qty
             else:
                 product_map[pid] = {
                    'product_name': move.product_id.display_name,
                    'product_sku': move.product_id.default_code or '',
                    'product_barcode': move.product_id.barcode or '',
                    'move_line_id': False, 
                    'total_scanned': 0.0,
                    'unassigned_scanned': 0.0,
                    'demand': move.product_uom_qty
                }

        # Tổng hợp lại thành list có sẵn hàng lẻ
        for pid, data in product_map.items():
            qty_available = data['unassigned_scanned']

            if qty_available > 0:
                ml_id = data['move_line_id']
                if not ml_id:
                    tmp_ml = request.env['stock.move.line'].sudo().search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', pid)
                    ], limit=1)
                    if tmp_ml:
                        ml_id = tmp_ml.id
                
                if ml_id:
                    all_items.append({
                        'move_line_id': ml_id,
                        'product_id': pid,
                        'product_name': data['product_name'],
                        'product_sku': data['product_sku'],         
                        'product_barcode': data['product_barcode'],
                        'qty_available': qty_available
                    })

        # Đồng bộ thông tin
        sync_info = []
        for pid, data in product_map.items():
            total = data['total_scanned']
            unassigned = data['unassigned_scanned']
            packed_qty = total - unassigned
            sync_info.append({
                'product_id': pid,
                'product_barcode': data['product_barcode'],
                'product_sku': data['product_sku'],
                'packed_qty': packed_qty
            })

        return {
            'package_id': package.id,
            'package_name': package.name,
            'items': items,
            'other_packages': other_packages,
            'all_items': all_items,
            'sync_info': sync_info
        }

    @http.route('/hlv_mobile_barcode/update_package_item_qty', type='json', auth='user')
    def update_package_item_qty(self, picking_id, package_id, move_line_id, new_qty):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if move_line.result_package_id.id != package_id:
            return {'error': _('Sản phẩm này không thuộc gói này!')}

        if new_qty < 0:
            return {'error': _('Số lượng không được âm!')}

        old_qty = move_line.quantity
        
        # Trường hợp tăng số lượng: kiểm tra available
        if new_qty > old_qty:
            original_move = move_line.move_id
            if original_move:
                total_current_done = sum(ml.quantity for ml in original_move.move_line_ids)
                available_qty = original_move.product_uom_qty - (total_current_done - old_qty)
                
                if new_qty > available_qty:
                    return {'error': _('⚠️ Số lượng không được vượt quá %s (tối đa cho sản phẩm này)', available_qty)}
            
            move_line.with_context(skip_qty_validation=True).write({'quantity': new_qty})
            
        # Trường hợp giảm số lượng: Unpack phần thừa
        elif new_qty < old_qty:
            diff = old_qty - new_qty
            
            # 1. Cập nhật dòng hiện tại trong package
            if new_qty == 0:
                move_line.with_context(skip_qty_validation=True).write({'result_package_id': False})
            else:
                move_line.with_context(skip_qty_validation=True).write({'quantity': new_qty})
                
                # 2. Tạo hoặc cộng dồn vào dòng hàng lẻ có sẵn
                existing_loose_line = request.env['stock.move.line'].sudo().search([
                    ('picking_id', '=', picking.id),
                    ('product_id', '=', move_line.product_id.id),
                    ('result_package_id', '=', False),
                    ('location_id', '=', move_line.location_id.id),
                    ('location_dest_id', '=', move_line.location_dest_id.id),
                ], limit=1)
                
                if existing_loose_line:
                    existing_loose_line.with_context(skip_qty_validation=True).write({
                        'quantity': existing_loose_line.quantity + diff
                    })
                else:
                    move_line.with_context(skip_qty_validation=True).copy({
                        'quantity': diff,
                        'result_package_id': False
                    })

        return {
            'success': True,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'message': _('Cập nhật thành công: %s → %s', old_qty, new_qty)
        }

    @http.route('/hlv_mobile_barcode/remove_package_item', type='json', auth='user')
    def remove_package_item(self, picking_id, package_id, move_line_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if move_line.result_package_id.id != package_id:
            return {'error': _('Sản phẩm này không thuộc gói này!')}

        move_line.with_context(skip_qty_validation=True).write({
            'result_package_id': False
        })
        
        return {
            'success': True,
            'message': _('Đã bỏ sản phẩm khỏi kiện (vẫn giữ trạng thái đã quét)')
        }

    @http.route('/hlv_mobile_barcode/add_item_to_package', type='json', auth='user')
    def add_item_to_package(self, picking_id, package_id, move_line_id, qty):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if qty <= 0:
            return {'error': _('Số lượng thêm phải lớn hơn 0!')}

        product = move_line.product_id

        # Lấy thông tin tổng quan
        all_product_lines = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('product_id', '=', product.id),
        ])

        # Tính unassigned scanned
        unassigned_lines = all_product_lines.filtered(lambda ml: not ml.result_package_id and ml.quantity > 0)
        total_unassigned = sum(float(ml.quantity or 0) for ml in unassigned_lines)
        
        if qty > total_unassigned:
            return {
                'error': _('⚠️ Không thể thêm %s vào package.\n• Chưa đóng gói (đã quét): %s\n• Yêu cầu: Bạn phải quét sản phẩm ở màn hình chính trước khi thêm vào gói!', qty, total_unassigned)
            }

        remaining_qty_to_add = qty
        if total_unassigned > 0:
            sorted_unassigned = unassigned_lines.sorted(key=lambda l: l.id)
            
            for ml in sorted_unassigned:
                if remaining_qty_to_add <= 0:
                    break
                
                available = float(ml.quantity or 0)
                take = min(remaining_qty_to_add, available)
                
                # Tìm dòng trong package đích
                dest_line = all_product_lines.filtered(lambda l: l.result_package_id.id == package_id and l.id != ml.id)
                
                if dest_line:
                    # Giảm source trước
                    if take == available:
                        ml.with_context(skip_qty_validation=True).unlink()
                    else:
                        ml.with_context(skip_qty_validation=True).write({'quantity': ml.quantity - take})
                        
                    # Merge vào dest_line
                    dest_line[0].with_context(skip_qty_validation=True).write({
                        'quantity': dest_line[0].quantity + take
                    })
                else:
                    # Không có dòng đích
                    if take == available:
                        ml.with_context(skip_qty_validation=True).write({'result_package_id': package_id})
                    else:
                        ml.with_context(skip_qty_validation=True).write({'quantity': ml.quantity - take})
                        ml.with_context(skip_qty_validation=True).copy({
                            'quantity': take,
                            'result_package_id': package_id
                        })
                
                remaining_qty_to_add -= take

        return {
            'success': True,
            'message': _('Đã thêm %s sản phẩm vào kiện thành công.', qty)
        }

    @http.route('/hlv_mobile_barcode/transfer_item_between_packages', type='json', auth='user')
    def transfer_item_between_packages(self, picking_id, from_package_id, to_package_id, move_line_id, qty):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}

        if from_package_id == to_package_id:
            return {'error': _('Gói nguồn và gói đích phải khác nhau!')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if move_line.result_package_id.id != from_package_id:
            return {'error': _('Sản phẩm này không thuộc gói nguồn!')}

        if qty <= 0 or qty > move_line.quantity:
            return {'error': _('Số lượng chuyển không hợp lệ!')}

        to_package = request.env['stock.quant.package'].sudo().browse(to_package_id)
        if not to_package.exists():
            return {'error': _('Gói đích không tồn tại!')}

        # Kiểm tra xem gói đích có trong phiếu này không
        to_ml_exists = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('result_package_id', '=', to_package_id)
        ], limit=1)
        if not to_ml_exists:
            return {'error': _('Gói đích không tồn tại hoặc không hợp lệ trong phiếu này!')}

        # Cập nhật package nguồn
        ctx = dict(request.env.context, skip_qty_validation=True)
        new_qty = move_line.quantity - qty
        
        # Tìm xem sản phẩm có trong package đích không
        existing_in_target = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('product_id', '=', move_line.product_id.id),
            ('result_package_id', '=', to_package_id),
            ('move_id', '=', move_line.move_id.id)
        ], limit=1)

        # Giảm số lượng ở nguồn trước
        if new_qty == 0:
            if existing_in_target:
                existing_in_target.with_context(ctx).write({
                    'quantity': existing_in_target.quantity + qty
                })
                move_line.with_context(ctx).unlink()
            else:
                move_line.with_context(ctx).write({
                    'result_package_id': to_package_id
                })
        else:
            move_line.with_context(ctx).write({'quantity': new_qty})
            if existing_in_target:
                existing_in_target.with_context(ctx).write({
                    'quantity': existing_in_target.quantity + qty
                })
            else:
                move_line.with_context(ctx).copy({
                    'result_package_id': to_package_id,
                    'quantity': qty
                })

        return {
            'success': True,
            'message': _('Đã chuyển %s sản phẩm sang gói đích thành công.', qty)
        }
