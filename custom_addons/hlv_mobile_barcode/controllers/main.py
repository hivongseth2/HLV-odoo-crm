import logging

from odoo import http, _
# pyrefly: ignore [missing-import]
from odoo.http import request

_logger = logging.getLogger(__name__)

def _is_pick_picking(picking):
    if not picking or not picking.exists():
        return False
    pt = picking.picking_type_id
    if not pt:
        return False
        
    picking_name = (picking.name or '').lower()
    pt_name = (pt.name or '').lower()
    seq_code = (pt.sequence_code or '').lower()
    
    seq_prefix = ''
    seq_name = ''
    try:
        if pt.sequence_id:
            seq_prefix = (pt.sequence_id.prefix or '').lower()
            seq_name = (pt.sequence_id.name or '').lower()
    except Exception:
        pass
        
    return (
        'pick' in picking_name or
        'pick' in pt_name or
        'pick' in seq_code or
        'pick' in seq_prefix or
        'pick' in seq_name or
        'lấy hàng' in pt_name or
        'lấy hàng' in seq_name
    )

def _is_return_picking(picking):
    return bool(picking and picking.exists() and getattr(picking, 'return_id', False))

def _same_warehouse_one_step_enabled():
    param = request.env['ir.config_parameter'].sudo().get_param(
        'hlv_mobile_barcode.hlv_barcode_same_warehouse_one_step',
        'True'
    )
    return str(param).strip().lower() in ['true', '1']

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
            is_return_picking = _is_return_picking(picking)
            # Block PACK and OUT steps (keep only PICK allowed)
            pt_name = (picking.picking_type_id.name or '').lower()
            pt_code = (picking.picking_type_id.sequence_code or '').lower()
            if not is_return_picking and (picking.picking_type_id.code == 'outgoing' or 'pack' in pt_name or 'pack' in pt_code):
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
        allow_package = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_package_scan', 'False') == 'True'
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

        is_return_picking = _is_return_picking(picking)

        # Block PACK and OUT steps (keep only PICK allowed)
        pt_name = (picking.picking_type_id.name or '').lower()
        pt_code = (picking.picking_type_id.sequence_code or '').lower()
        if not is_return_picking and (picking.picking_type_id.code == 'outgoing' or 'pack' in pt_name or 'pack' in pt_code):
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
        if is_return_picking:
            is_putaway = picking.location_dest_id.usage == 'internal'
        elif pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
            is_putaway = True

        # Auto-fix Step 2 pickings generated by deltatech_picking_transit
        # Deltatech creates Step 2 with product_uom_qty=0 and quantity=X.
        # Barcode app needs product_uom_qty=X and quantity=0 to allow scanning.
        if picking.source_transfer_id and picking.state in ['draft', 'confirmed', 'assigned']:
            for move in picking.sudo().move_ids:
                if move.state in ['draft', 'confirmed', 'assigned'] and move.product_uom_qty == 0:
                    total_qty = sum(l.quantity for l in move.move_line_ids)
                    if total_qty > 0:
                        move.product_uom_qty = total_qty
                        for line in move.move_line_ids:
                            line.quantity = 0.0

        is_pick_picking = _is_pick_picking(picking) and not is_return_picking

        product_ids = picking.move_ids.mapped('product_id').ids
        warehouse_qty_by_product = {}
        if product_ids:
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', 'in', product_ids),
                ('location_id', 'child_of', picking.location_id.id)
            ])
            for q in quants:
                warehouse_qty_by_product[q.product_id.id] = warehouse_qty_by_product.get(q.product_id.id, 0.0) + q.quantity

        lines = []
        for move in picking.move_ids:
            if move.move_line_ids:
                for ml in move.move_line_ids:
                    if is_putaway:
                        loc_name = ml.location_dest_id.display_name
                    else:
                        loc_name = ml.location_id.display_name

                    package_name = ml.result_package_id.name or ml.package_id.name or False
                    
                    # Calculate individual line demand for Step 2
                    line_demand = move.product_uom_qty
                    if is_pick_picking:
                        line_demand = ml.quantity
                    elif picking.source_transfer_id:
                        orig_mls = picking.source_transfer_id.move_line_ids.filtered(lambda l: l.product_id == ml.product_id)
                        if ml.package_id or ml.result_package_id:
                            pkg_id = ml.package_id or ml.result_package_id
                            matched_orig = orig_mls.filtered(lambda l: l.result_package_id == pkg_id)
                            if matched_orig:
                                line_demand = sum(matched_orig.mapped('quantity'))
                        else:
                            matched_orig = orig_mls.filtered(lambda l: not l.result_package_id)
                            if matched_orig:
                                line_demand = sum(matched_orig.mapped('quantity'))

                    lines.append({
                        'id': ml.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_name': move.product_id.display_name,
                        'product_barcode': move.product_id.barcode,
                        'product_uom_qty': line_demand,
                        # PICK: dùng qty_scanned thay quantity để tránh xung đột với assign bên ngoài
                        'qty_done': ml.qty_scanned if is_pick_picking else ml.quantity,
                        'warehouse_qty': warehouse_qty_by_product.get(move.product_id.id, 0.0),
                        'uom_name': move.product_uom.name,
                        'state': move.state,
                        'location_name': loc_name,
                        'package_name': package_name,
                        'result_package_id': ml.result_package_id.id or False,
                        'package_id': ml.package_id.id or False,
                    })
            else:
                if is_pick_picking:
                    continue
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
                    'warehouse_qty': warehouse_qty_by_product.get(move.product_id.id, 0.0),
                    'uom_name': move.product_uom.name,
                    'state': move.state,
                    'location_name': loc_name,
                    'package_name': False,
                    'result_package_id': False,
                    'package_id': False,
                })

        if is_pick_picking and not lines:
            return {'error': _('Phiếu PICK này chưa có sản phẩm nào được gán vị trí lấy hàng. Vui lòng chờ hệ thống phân bổ xong!')}
        # Find linked Step 2 picking (only active for pure internal transfers e.g. INT -> IN / STOR)
        linked_picking_id = False
        linked_picking_name = False
        
        if picking.picking_type_id.code == 'internal':
            _logger.info(
                "[LINKED_PICKING_SEARCH] === START for picking %s (id=%s, state=%s, dest_loc=%s) ===",
                picking.name, picking.id, picking.state, picking.location_dest_id.display_name
            )

            # Method 1 (highest priority per user rule): Chatter message
            # Odoo automatically posts a message in chatter when a step-2 picking is created from a step-1 picking.
            # e.g., "This transfer has been created from: KBC/INT/02042"
            # We search for mail.message containing the source picking name in model='stock.picking' and retrieve res_id.
            messages = request.env['mail.message'].sudo().search([
                ('model', '=', 'stock.picking'),
                ('body', 'like', picking.name)
            ], order='id desc', limit=10)
            _logger.info(
                "[LINKED_PICKING_SEARCH] Method 1 (Chatter): found %d messages for picking.name='%s' with model='stock.picking'",
                len(messages), picking.name
            )
            
            for msg in messages:
                target_picking = request.env['stock.picking'].sudo().browse(msg.res_id)
                _logger.info(
                    "[LINKED_PICKING_SEARCH] Method 1 (Chatter): msg.id=%s, res_id=%s, target exists=%s, target.name=%s, target.state=%s",
                    msg.id, msg.res_id, target_picking.exists(), target_picking.name if target_picking.exists() else 'N/A',
                    target_picking.state if target_picking.exists() else 'N/A'
                )
                if target_picking.exists() and target_picking.id > picking.id and target_picking.state not in ['cancel']:
                    linked_picking_id = target_picking.id
                    linked_picking_name = target_picking.name
                    _logger.info("[LINKED_PICKING_SEARCH] Method 1 (Chatter): ✅ FOUND linked picking %s (id=%s)", linked_picking_name, linked_picking_id)
                    break

            # Method 2: Via stock moves chain (Odoo native stock move chain)
            if not linked_picking_id:
                dest_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(
                    lambda p: p.id > picking.id and p.state not in ['cancel']
                )
                _logger.info(
                    "[LINKED_PICKING_SEARCH] Method 2 (Move Chain): move_ids=%s, move_dest_ids=%s, dest_pickings=%s",
                    picking.move_ids.ids,
                    picking.move_ids.mapped('move_dest_ids').ids,
                    [(p.id, p.name, p.state) for p in dest_pickings] if dest_pickings else 'NONE'
                )
                if dest_pickings:
                    linked_picking = dest_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                    _logger.info("[LINKED_PICKING_SEARCH] Method 2 (Move Chain): ✅ FOUND linked picking %s (id=%s)", linked_picking_name, linked_picking_id)
                    
            # Method 3: Same procurement group (sharing group_id)
            if not linked_picking_id and picking.group_id:
                group_pickings = request.env['stock.picking'].sudo().search([
                    ('group_id', '=', picking.group_id.id),
                    ('id', '>', picking.id),
                    ('state', 'not in', ['cancel'])
                ], order='id asc')
                _logger.info(
                    "[LINKED_PICKING_SEARCH] Method 3 (Group): group_id=%s, group_pickings=%s",
                    picking.group_id.id,
                    [(p.id, p.name, p.picking_type_id.sequence_code, p.state) for p in group_pickings] if group_pickings else 'NONE'
                )
                in_pickings = group_pickings.filtered(
                    lambda p: 'IN' in (p.picking_type_id.sequence_code or '').upper() 
                    or 'STOR' in (p.picking_type_id.sequence_code or '').upper()
                    or p.picking_type_id.code in ['incoming', 'internal']
                )
                if in_pickings:
                    linked_picking = in_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                    _logger.info("[LINKED_PICKING_SEARCH] Method 3 (Group): ✅ FOUND linked picking %s (id=%s)", linked_picking_name, linked_picking_id)
                elif group_pickings:
                    linked_picking = group_pickings[0]
                    linked_picking_id = linked_picking.id
                    linked_picking_name = linked_picking.name
                    _logger.info("[LINKED_PICKING_SEARCH] Method 3 (Group fallback): ✅ FOUND linked picking %s (id=%s)", linked_picking_name, linked_picking_id)
            elif not linked_picking_id:
                _logger.info("[LINKED_PICKING_SEARCH] Method 3 (Group): SKIPPED - no group_id on picking")
                    
            # Method 4: Origin matching current picking name (case-insensitive substring or exact match)
            if not linked_picking_id:
                origin_pickings = request.env['stock.picking'].sudo().search([
                    '|',
                    ('origin', '=', picking.name),
                    ('origin', 'ilike', picking.name),
                    ('id', '>', picking.id),
                    ('state', 'not in', ['cancel'])
                ], order='id asc', limit=1)
                _logger.info(
                    "[LINKED_PICKING_SEARCH] Method 4 (Origin): searching origin='%s', found=%s",
                    picking.name,
                    [(p.id, p.name, p.origin, p.state) for p in origin_pickings] if origin_pickings else 'NONE'
                )
                if origin_pickings:
                    linked_picking_id = origin_pickings.id
                    linked_picking_name = origin_pickings.name
                    _logger.info("[LINKED_PICKING_SEARCH] Method 4 (Origin): ✅ FOUND linked picking %s (id=%s)", linked_picking_name, linked_picking_id)
            
            _logger.info(
                "[LINKED_PICKING_SEARCH] === END for picking %s: result linked_picking_id=%s, linked_picking_name=%s ===",
                picking.name, linked_picking_id, linked_picking_name
            )
            
        packages = []
        # Hỗ trợ cả result_package_id (khi đóng gói ở Bước 1) và package_id (kiện hàng đi kèm ở Bước 2)
        all_pkgs = picking.move_line_ids.mapped('result_package_id') | picking.move_line_ids.mapped('package_id')
        for pkg in all_pkgs:
            pkg_mls = picking.move_line_ids.filtered(
                lambda ml: ml.result_package_id.id == pkg.id or ml.package_id.id == pkg.id
            )
            total_done = sum(ml.quantity for ml in pkg_mls)
            package_lines = [{
                'move_line_id': ml.id,
                'product_name': ml.product_id.display_name,
                'product_barcode': ml.product_id.barcode or '',
                'qty_done': ml.quantity or ml.product_uom_id._compute_quantity(ml.move_id.product_uom_qty, ml.product_id.uom_id) if ml.move_id else 0,
                'uom': ml.product_uom_id.name,
            } for ml in pkg_mls]
            if package_lines:
                packages.append({
                    'id': pkg.id,
                    'name': pkg.name,
                    'total_done': total_done,
                    'lines': package_lines,
                })

        show_qty_buttons = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_show_qty_buttons', 'True') == 'True'
        camera_param = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_camera_default_on')
        camera_default_on = camera_param is None or str(camera_param).strip().lower() in ['true', '1']

        # Kiểm tra xem có qty_scanned nào chưa (để frontend biết cần check availability khi vào lại)
        has_scanned_data = is_pick_picking and any(
            ml.qty_scanned > 0 for ml in picking.move_line_ids
        )

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
            'source_transfer_id': picking.source_transfer_id.id if picking.source_transfer_id else False,
            'source_transfer_name': picking.source_transfer_id.name if picking.source_transfer_id else False,
            'is_putaway': is_putaway,
            'show_qty_buttons': show_qty_buttons,
            'camera_default_on': camera_default_on,
            'is_pick': is_pick_picking,
            'is_return': is_return_picking,
            'return_of_id': picking.return_id.id if is_return_picking else False,
            'return_of_name': picking.return_id.name if is_return_picking else False,
            'has_scanned_data': has_scanned_data,
            'hlv_barcode_auto_cleared': getattr(picking, 'hlv_barcode_auto_cleared', False),
        }

    @http.route('/hlv_mobile_barcode/get_warehouses', type='json', auth='user')
    def get_warehouses(self):
        warehouses = request.env['stock.warehouse'].search([])
        return [{
            'id': w.id,
            'name': w.name,
            'code': w.code,
        } for w in warehouses]

    @http.route('/hlv_mobile_barcode/get_settings', type='json', auth='user')
    def get_settings(self):
        camera_param = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_camera_default_on')
        camera_default_on = camera_param is None or str(camera_param).strip().lower() in ['true', '1']
        return {
            'camera_default_on': camera_default_on,
        }

    @http.route('/hlv_mobile_barcode/create_empty_int', type='json', auth='user')
    def create_empty_int(self, location_id=None, dest_warehouse_id=False, dest_location_id=False, is_multi_location=False, source_warehouse_id=False):
        source_loc = request.env['stock.location'].browse()
        warehouse = None
        
        if location_id:
            source_loc = request.env['stock.location'].browse(location_id)
            if not source_loc.exists():
                return {'error': _('Không tìm thấy vị trí nguồn')}
            warehouse = source_loc.warehouse_id
            if not warehouse:
                warehouse = request.env['stock.warehouse'].search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
        elif is_multi_location:
            # Ưu tiên lấy kho nguồn do user chọn, nếu không thì suy đoán từ đích
            if source_warehouse_id:
                warehouse = request.env['stock.warehouse'].browse(int(source_warehouse_id))
            elif dest_location_id:
                dest_loc = request.env['stock.location'].browse(dest_location_id)
                warehouse = dest_loc.warehouse_id
            if not warehouse and dest_warehouse_id:
                warehouse = request.env['stock.warehouse'].browse(int(dest_warehouse_id))
            
            if not warehouse:
                warehouse = request.env['stock.warehouse'].search([('company_id', '=', request.env.company.id)], limit=1)
                
            if warehouse and warehouse.lot_stock_id:
                source_loc = warehouse.lot_stock_id
        
        if not source_loc or not source_loc.exists():
            return {'error': _('Không xác định được vị trí nguồn')}
            
        company_id = request.env.company.id
        transit_loc = request.env['stock.location'].search([
            ('usage', '=', 'transit'), 
            ('company_id', 'in', [False, company_id])
        ], limit=1)
        
        if not transit_loc:
            return {'error': _('Không tìm thấy kho trung chuyển (Transit Location)')}
            
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
        target_location_dest_id = transit_loc.id
        override_dest_loc_id = False
        same_warehouse_one_step = _same_warehouse_one_step_enabled()
        
        if dest_location_id:
            dest_loc = request.env['stock.location'].browse(dest_location_id)
            if dest_loc.exists():
                if dest_loc.warehouse_id and dest_loc.warehouse_id == warehouse and same_warehouse_one_step:
                    # Same warehouse -> direct 1 step move
                    target_location_dest_id = dest_loc.id
                else:
                    # Different warehouse, or same warehouse with 1-step disabled -> use transit and override step 2.
                    override_dest_loc_id = dest_loc.id
                    if dest_loc.warehouse_id and dest_loc.warehouse_id.partner_id:
                        partner_id = dest_loc.warehouse_id.partner_id.id
                        
        if not partner_id and dest_warehouse_id:
            dest_warehouse = request.env['stock.warehouse'].browse(dest_warehouse_id)
            if dest_warehouse.exists() and dest_warehouse.partner_id:
                partner_id = dest_warehouse.partner_id.id
                
        if not partner_id and warehouse and warehouse.partner_id:
            partner_id = warehouse.partner_id.id

        picking_vals = {
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': target_location_dest_id,
            'partner_id': partner_id,
        }
        
        if override_dest_loc_id:
            picking_vals['note'] = f"DEST_LOC_OVERRIDE:{override_dest_loc_id}\n"
            
        picking_int = request.env['stock.picking'].create(picking_vals)
        
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
    def process_barcode(self, picking_id, barcode, destination_location_id=None, last_product_id=None, location_mode=None, is_multi_location=False):
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
        is_return_picking = _is_return_picking(picking)
        is_pick_picking = _is_pick_picking(picking) and not is_return_picking
        if is_return_picking:
            is_putaway = picking.location_dest_id.usage == 'internal'
        elif pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
            is_putaway = True
        else:
            is_putaway = False

        if location_mode == 'dest':
            is_putaway = True
        elif location_mode == 'source' and (is_multi_location or is_pick_picking):
            is_putaway = False
        
        # 1. Try to find location first
        location = request.env['stock.location'].sudo().search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
        if location:
            res = {'type': 'location', 'location_id': location.id, 'location_name': location.display_name, 'is_putaway': is_putaway}
            if last_product_id and not is_multi_location:
                move = picking.move_ids.filtered(lambda m: m.product_id.id == last_product_id and m.state not in ['done', 'cancel'])
                if move:
                    move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id)
                    if move_line:
                        updated_ml = move_line[-1]
                        if is_putaway:
                            updated_ml.location_dest_id = location.id
                        else:
                            updated_ml.location_id = location.id
                        res['updated_product_id'] = last_product_id
                        res['updated_move_line_id'] = updated_ml.id
            return res

        # 1.5. Try to find package
        package = request.env['stock.quant.package'].sudo().search([('name', '=', barcode)], limit=1)
        if package:
            allow_package = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_package_scan', 'False') == 'True'
            if not allow_package:
                return {'error': _('Tính năng quét Kiện hàng hiện đang bị tắt trong cấu hình hệ thống!')}
            # We found a package! Let's process the package contents in the picking.
            # A. Check if the picking has a move line for this package_id
            move_lines = picking.move_line_ids.filtered(lambda ml: (ml.package_id == package or ml.result_package_id == package) and ml.state not in ['done', 'cancel'])
            if move_lines:
                processed_lines = []
                for ml in move_lines:
                    line_demand = ml.move_id.product_uom_qty
                    if picking.source_transfer_id:
                        orig_mls = picking.source_transfer_id.move_line_ids.filtered(lambda l: l.product_id == ml.product_id)
                        pkg_id = ml.package_id or ml.result_package_id
                        matched_orig = orig_mls.filtered(lambda l: l.result_package_id == pkg_id)
                        if matched_orig:
                            line_demand = sum(matched_orig.mapped('quantity'))
                    
                    ml.quantity = line_demand
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
                    move = picking.move_ids.filtered(
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

        is_in_picking = pt_type == 'incoming'

        if (is_pick_picking or (is_multi_location and not is_putaway)) and not destination_location_id:
            return {'error': _('Vui lòng quét mã Vị trí (Kệ hàng) trước khi quét sản phẩm!')}

        product = request.env['product.product'].sudo().search(['|', ('barcode', '=', barcode), ('default_code', '=', barcode)], limit=1)
        if not product:
            return {'error': _('Không tìm thấy mã vạch hợp lệ (Sản phẩm hoặc Vị trí).')}

        # Find the move for this product
        move = picking.move_ids.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])
        
        # PRE-CHECK: Physical stock check BEFORE creating any new move
        temp_move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id) if move else []
        ml_src_id = destination_location_id if (destination_location_id and not is_putaway) else (temp_move_line[0].location_id.id if temp_move_line else picking.location_id.id)
        
        if not is_putaway:
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', ml_src_id),
                ('company_id', '=', picking.company_id.id),
                ('package_id', '=', False)
            ])
            free_qty = sum(q.quantity - q.reserved_quantity for q in quants)
            
            source_loc = request.env['stock.location'].sudo().browse(ml_src_id)
            child_loc_ids = request.env['stock.location'].sudo().search([('id', 'child_of', ml_src_id)]).ids
            
            reserved_by_this = sum(
                ml.product_uom_id._compute_quantity(ml.quantity_product_uom, product.uom_id)
                for ml in picking.move_line_ids
                if ml.product_id == product and ml.location_id.id in child_loc_ids and not ml.package_id
            )
            available_qty = free_qty + reserved_by_this
            
            processed_qty_from_loc_base = sum(
                ml.product_uom_id._compute_quantity(
                    ml.qty_scanned if is_pick_picking else ml.quantity,
                    product.uom_id
                )
                for ml in picking.move_line_ids
                if ml.product_id == product and ml.location_id.id in child_loc_ids
            )
            
            if available_qty <= 0:
                return {'error': _('Sản phẩm "%s" không có tồn kho khả dụng tại vị trí "%s" (bao gồm các vị trí con). Không thể quét!', product.display_name, source_loc.display_name)}
                
            scan_qty_base = 1.0
            if move and move[0].product_uom:
                scan_qty_base = move[0].product_uom._compute_quantity(1.0, product.uom_id)
            
            if processed_qty_from_loc_base + scan_qty_base > available_qty:
                return {'error': _('Số lượng quét vượt quá tồn kho thực tế khả dụng tại vị trí "%s" (Tối đa: %g %s). Không thể quét thêm!', source_loc.display_name, available_qty, product.uom_id.name)}
        
        if not move:
            if picking.source_transfer_id:
                return {'error': _('Không được quét thêm sản phẩm mới vào phiếu Bước 2! Chỉ được quét các sản phẩm đã có trong phiếu.')}
            
            allow_add = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_add_product', 'True') == 'True'
            if not allow_add:
                return {'error': _('Tính năng thêm sản phẩm mới hiện đang bị tắt trong cấu hình hệ thống!')}
                
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
            
            if picking.state == 'draft':
                picking.action_confirm()
                move = picking.move_ids.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])
                if not move:
                    return {'error': _('Lỗi hệ thống khi tạo sản phẩm mới.')}
                move = move[0]
        else:
            # Select the most appropriate move if there are multiple
            if is_pick_picking:
                incomplete_moves = move.filtered(lambda m: m.product_uom_qty > sum(m.move_line_ids.mapped('qty_scanned')))
            else:
                incomplete_moves = move.filtered(lambda m: m.product_uom_qty > sum(m.move_line_ids.mapped('quantity')))
            target_moves = incomplete_moves if incomplete_moves else move
            
            best_move = False
            if len(target_moves) > 1 and destination_location_id:
                if is_pick_picking:
                    moves_with_loc = target_moves.filtered(lambda m: destination_location_id in m.move_line_ids.mapped('location_id').ids)
                    if moves_with_loc:
                        best_move = moves_with_loc[0]
                elif is_in_picking:
                    moves_with_loc = target_moves.filtered(lambda m: destination_location_id in m.move_line_ids.mapped('location_dest_id').ids)
                    if moves_with_loc:
                        best_move = moves_with_loc[0]
            
            move = best_move if best_move else target_moves[0]

        # Check limit to prevent over-scanning (demand-based)
        if picking.source_transfer_id and is_putaway:
            line_demand = move.product_uom_qty
            step2_qty_done = sum(ml.quantity for ml in move.move_line_ids)
            if line_demand > 0.0 and step2_qty_done + 1 > line_demand:
                return {'error': _('Sáº£n pháº©m "%s" Ä‘Ã£ quÃ©t Ä‘á»§ sá»‘ lÆ°á»£ng yÃªu cáº§u cá»§a phiáº¿u BÆ°á»›c 2 (%g/%g). KhÃ´ng thá»ƒ quÃ©t thÃªm!', product.display_name, step2_qty_done, line_demand)}
        elif picking.source_transfer_id:
            # In Step 2, we specifically restrict the LOOSE product quantity
            line_demand = move.product_uom_qty
            orig_mls = picking.source_transfer_id.move_line_ids.filtered(lambda l: l.product_id == product)
            matched_orig = orig_mls.filtered(lambda l: not l.result_package_id)
            if matched_orig:
                line_demand = sum(matched_orig.mapped('quantity'))
            
            loose_qty_done = sum(ml.qty_scanned if is_pick_picking else ml.quantity for ml in move.move_line_ids if not ml.package_id and not ml.result_package_id)
            if line_demand > 0.0 and loose_qty_done + 1 > line_demand:
                return {'error': _('Sản phẩm rời "%s" đã quét đủ số lượng yêu cầu (%g/%g). Không thể quét thêm hàng rời!', product.display_name, loose_qty_done, line_demand)}
        
        if is_pick_picking:
            # PICK: kiểm tra tổng qty_scanned không vượt quá demand và không vượt quá tổng quantity đã assign (số lượng thực tế)
            current_qty_scanned = sum(ml.qty_scanned for ml in move.move_line_ids)
            total_assigned = sum(ml.quantity for ml in move.move_line_ids)
            
            # Chỉ giới hạn theo assigned nếu phiếu đã được assign (total_assigned > 0)
            max_allowed = min(move.product_uom_qty, total_assigned) if total_assigned > 0 else move.product_uom_qty
            
            if move.product_uom_qty > 0.0 and current_qty_scanned + 1 > max_allowed:
                return {'error': _('Sản phẩm "%s" đã quét đủ số lượng yêu cầu và thực tế (%g/%g). Không thể quét thêm!', product.display_name, current_qty_scanned, max_allowed)}
        elif not picking.source_transfer_id:
            current_qty_done = sum(ml.quantity for ml in move.move_line_ids)
            if move.product_uom_qty > 0.0 and current_qty_done + 1 > move.product_uom_qty:
                return {'error': _('Sản phẩm "%s" đã quét đủ tổng số lượng yêu cầu của dòng này (%g/%g). Không thể quét thêm!', product.display_name, current_qty_done, move.product_uom_qty)}

        # Step 2 putaway must update the existing Odoo-created move lines, including package lines.
        if picking.source_transfer_id and is_putaway:
            move_line = move.move_line_ids.filtered(lambda ml: ml.state not in ['done', 'cancel'])
            available_move_line = move_line.filtered(lambda ml: not ml.quantity_product_uom or ml.quantity < ml.quantity_product_uom)
            if available_move_line:
                move_line = available_move_line
            if not move_line:
                return {'error': _('KhÃ´ng tÃ¬m tháº¥y dÃ²ng BÆ°á»›c 2 phÃ¹ há»£p cho sáº£n pháº©m "%s". Vui lÃ²ng kiá»ƒm tra phiáº¿u sinh tá»« BÆ°á»›c 1.', product.display_name)}
        else:
            # Find an unpacked move line that is not in any package
            move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id)

        if is_pick_picking:
            if destination_location_id:
                move_line = move_line.filtered(lambda ml: ml.location_id.id == destination_location_id)
                if not move_line:
                    return {'error': _('Sản phẩm "%s" không có dòng lấy hàng tại vị trí đang quét.', product.display_name)}
            
            # Lọc các dòng chưa quét đủ số lượng assign (số lượng tại vị trí)
            available_move_line = move_line.filtered(lambda ml: ml.quantity <= 0 or ml.qty_scanned < ml.quantity)
            if not available_move_line:
                # Nếu tất cả dòng đã quét đủ quantity
                loc_msg = _(' tại vị trí này') if destination_location_id else ''
                return {'error': _('Sản phẩm "%s"%s đã được quét đủ số lượng phân bổ (%g).', product.display_name, loc_msg, sum(move_line.mapped('qty_scanned')))}
            move_line = available_move_line
        elif is_in_picking and destination_location_id:
            move_line = move_line.filtered(lambda ml: ml.location_dest_id.id == destination_location_id)
        
        ml_dest_id = destination_location_id if (destination_location_id and is_putaway) else (move_line[0].location_dest_id.id if move_line else picking.location_dest_id.id)
        
        if not is_putaway:
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
        
        updated_move_line = request.env['stock.move.line'].browse()
        if move_line:
            # Check if location matches, otherwise we might need a new move line
            last_ml = move_line[-1]
            if (is_putaway and destination_location_id and last_ml.location_dest_id.id != destination_location_id) or \
               (not is_putaway and destination_location_id and last_ml.location_id.id != ml_src_id):
                # Locations differ, create a new move line
                new_ml_vals = {
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': ml_src_id,
                    'location_dest_id': ml_dest_id,
                }
                if is_pick_picking:
                    new_ml_vals['qty_scanned'] = 1
                else:
                    new_ml_vals['quantity'] = 1
                updated_move_line = request.env['stock.move.line'].create(new_ml_vals)
            else:
                if is_pick_picking:
                    last_ml.qty_scanned += 1
                else:
                    last_ml.quantity += 1
                updated_move_line = last_ml
        else:
            # Create a new move line if none exists or all are full
            new_ml_vals = {
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': ml_src_id,
                'location_dest_id': ml_dest_id,
            }
            if is_pick_picking:
                new_ml_vals['qty_scanned'] = 1
            else:
                new_ml_vals['quantity'] = 1
            updated_move_line = request.env['stock.move.line'].create(new_ml_vals)
            
        return {
            'success': True,
            'type': 'product',
            'product_id': product.id,
            'product_name': product.display_name,
            'move_line_id': updated_move_line.id or False,
        }

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
                if move.picking_id.source_transfer_id:
                    return {'error': _('Không được phép tự tạo dòng mới trong phiếu Bước 2!')}
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

        is_pick = _is_pick_picking(move.picking_id) and not _is_return_picking(move.picking_id)

        if new_qty is not None:
            new_val = float(new_qty)
        elif qty_change is not None:
            # PICK: đọc từ qty_scanned; phiếu khác đọc từ quantity
            current_val = move_line.qty_scanned if is_pick else move_line.quantity
            new_val = current_val + float(qty_change)
        else:
            return {'error': _('Thiếu tham số số lượng')}

        if new_val < 0:
            new_val = 0

        # Check limit to prevent over-scanning/updating
        warning_msg = False
        if move.picking_id.source_transfer_id:
            # Step 2 specific limit check (strict per line)
            line_demand = move.product_uom_qty
            orig_mls = move.picking_id.source_transfer_id.move_line_ids.filtered(lambda l: l.product_id == move.product_id)
            if move_line.package_id or move_line.result_package_id:
                pkg_id = move_line.package_id or move_line.result_package_id
                matched_orig = orig_mls.filtered(lambda l: l.result_package_id == pkg_id)
            else:
                matched_orig = orig_mls.filtered(lambda l: not l.result_package_id)
            
            if matched_orig:
                line_demand = sum(matched_orig.mapped('quantity'))
                
            if line_demand > 0.0 and new_val > line_demand:
                capped_val = line_demand
                
                # Compare with current value depending on picking type
                current_val_compare = move_line.qty_scanned if is_pick else move_line.quantity
                if capped_val == current_val_compare:
                    return {'error': _('Số lượng vượt quá yêu cầu cho phép của dòng này (%g/%g).', new_val, line_demand)}
                
                new_val = capped_val
                warning_msg = _('Số lượng đã tự lùi về mức tối đa theo yêu cầu (%g).', capped_val)
        
        if is_pick:
            # PICK: so sánh tổng qty_scanned thay vì quantity
            other_lines_scanned = sum(ml.qty_scanned for ml in move.move_line_ids if ml.id != move_line.id)
            total_assigned = sum(ml.quantity for ml in move.move_line_ids)
            
            # Số lượng tối đa của tổng các move line
            max_allowed_total = min(move.product_uom_qty, total_assigned) if total_assigned > 0 else move.product_uom_qty
            
            capped_val = new_val
            
            # Số lượng trên move line không được vượt quá số lượng tại vị trí (ml.quantity)
            if move_line.quantity > 0 and capped_val > move_line.quantity:
                capped_val = move_line.quantity
                
            # Số lượng tổng cộng lại không được vượt quá số lượng yêu cầu và số lượng thực tế
            if move.product_uom_qty > 0.0 and (capped_val + other_lines_scanned) > max_allowed_total:
                capped_val = max(0.0, max_allowed_total - other_lines_scanned)
                
            if capped_val < new_val:
                if capped_val == move_line.qty_scanned:
                    return {'error': _('Số lượng vượt quá yêu cầu cho phép hoặc vượt quá số lượng tại vị trí (%g).', new_val)}
                new_val = capped_val
                warning_msg = _('Số lượng đã tự lùi về tối đa có thể (%g).', capped_val)
        elif not move.picking_id.source_transfer_id:
            other_lines_qty = sum(ml.quantity for ml in move.move_line_ids if ml.id != move_line.id)
            if move.product_uom_qty > 0.0 and (new_val + other_lines_qty) > move.product_uom_qty:
                capped_val = max(0.0, move.product_uom_qty - other_lines_qty)
                if capped_val == move_line.quantity:
                    return {'error': _('Số lượng vượt quá yêu cầu cho phép (%g/%g).', (new_val + other_lines_qty), move.product_uom_qty)}
                
                new_val = capped_val
                warning_msg = _('Số lượng đã tự lùi về tối đa theo yêu cầu phiếu (%g).', capped_val)

        # If we are picking from a location, validate physical stock
        pt_code = (move.picking_id.picking_type_id.sequence_code or '').upper()
        pt_type = move.picking_id.picking_type_id.code
        is_putaway = False
        if _is_return_picking(move.picking_id):
            is_putaway = move.picking_id.location_dest_id.usage == 'internal'
        elif pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code):
            is_putaway = True
            
        if not is_putaway:
            ml_src_id = move_line.location_id.id
            child_loc_ids = request.env['stock.location'].sudo().search([('id', 'child_of', ml_src_id)]).ids
            
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', move.product_id.id),
                ('location_id', 'child_of', ml_src_id),
                ('company_id', '=', move.company_id.id),
                ('package_id', '=', move_line.package_id.id if move_line.package_id else False)
            ])
            free_qty = sum(q.quantity - q.reserved_quantity for q in quants)
            
            reserved_by_this = sum(
                ml.product_uom_id._compute_quantity(ml.quantity_product_uom, move.product_id.uom_id)
                for ml in move.picking_id.move_line_ids
                if ml.product_id == move.product_id and ml.location_id.id in child_loc_ids
                and (ml.package_id.id if ml.package_id else False) == (move_line.package_id.id if move_line.package_id else False)
            )
            available_qty = free_qty + reserved_by_this
            
            new_val_base = move_line.product_uom_id._compute_quantity(new_val, move.product_id.uom_id)
            
            processed_qty_from_loc_base = sum(
                ml.product_uom_id._compute_quantity(ml.qty_scanned if is_pick else ml.quantity, move.product_id.uom_id)
                for ml in move.picking_id.move_line_ids
                if ml.product_id == move.product_id and ml.location_id.id in child_loc_ids and ml.id != move_line.id
            )
            
            if (new_val_base + processed_qty_from_loc_base) > available_qty:
                capped_val_base = max(0.0, available_qty - processed_qty_from_loc_base)
                capped_val = move.product_id.uom_id._compute_quantity(capped_val_base, move_line.product_uom_id)
                
                current_val_for_compare = move_line.qty_scanned if is_pick else move_line.quantity
                if capped_val == current_val_for_compare:
                    return {
                        'error': _(
                            'Số lượng cập nhật vượt quá tồn kho thực tế khả dụng tại vị trí "%s" (Tối đa: %g %s).',
                            move_line.location_id.display_name,
                            available_qty,
                            move.product_id.uom_id.name
                        )
                    }
                
                new_val = capped_val
                warning_msg = _(
                    'Số lượng đã tự lùi về mức tối đa khả dụng tại vị trí "%s" (%g %s).',
                    move_line.location_id.display_name,
                    capped_val,
                    move.product_id.uom_id.name
                )

        # Ghi vào đúng field dựa theo loại phiếu
        if is_pick:
            move_line.qty_scanned = new_val
        else:
            move_line.quantity = new_val
        
        new_qty_result = move_line.qty_scanned if is_pick else move_line.quantity
        res = {'success': True, 'new_qty': new_qty_result}
        if warning_msg:
            res['warning'] = warning_msg
            
        return res

    @http.route('/hlv_mobile_barcode/clear_quantities', type='json', auth='user')
    def clear_quantities(self, picking_id):
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'waiting', 'confirmed', 'assigned']:
            return {'error': _('Không thể xoá số lượng của phiếu này')}
            
        try:
            is_pick = _is_pick_picking(picking) and not _is_return_picking(picking)
            
            changed = False
            
            # 1. Handle stock move lines - dùng sudo() để đảm bảo quyền ghi
            move_lines = picking.move_line_ids.sudo()
            
            if is_pick:
                # PICK: reset qty_scanned về 0 (quantity do Odoo quản lý, không đụng vào)
                lines_to_reset = move_lines.filtered(lambda l: l.qty_scanned != 0.0)
                if lines_to_reset:
                    lines_to_reset.write({'qty_scanned': 0.0})
                    changed = True
            else:
                # For other picking types, delete dynamically created lines, reset the rest
                lines_to_unlink = move_lines.filtered(
                    lambda ml: ml.quantity == 0.0 and not ml.move_id.move_orig_ids and not picking.source_transfer_id
                )
                lines_to_reset = move_lines - lines_to_unlink
                
                if lines_to_unlink:
                    lines_to_unlink.unlink()
                    changed = True
                
                if lines_to_reset:
                    actual_reset = lines_to_reset.filtered(lambda l: l.quantity != 0.0 or (not picking.source_transfer_id and l.result_package_id))
                    if actual_reset:
                        vals = {'quantity': 0.0}
                        if not picking.source_transfer_id:
                            vals['result_package_id'] = False
                        actual_reset.write(vals)
                        changed = True
                    
            # 2. Handle stock moves that were created dynamically on the fly (demand = 0)
            # Only delete if it has no move_orig_ids (meaning it wasn't generated by a previous step)
            if not is_pick:
                dynamic_moves = picking.move_ids.sudo().filtered(lambda m: m.product_uom_qty == 0.0 and not m.move_orig_ids)
                if dynamic_moves:
                    dynamic_moves._action_cancel()
                    dynamic_moves.unlink()
                    changed = True
                
            # Đánh dấu đã auto-clear để không lặp lại
            if hasattr(picking, 'hlv_barcode_auto_cleared'):
                picking.sudo().write({'hlv_barcode_auto_cleared': True})
                
            if not changed:
                return {'error': 'Đã hoàn tất kiểm tra số lượng ban đầu.'}
                
            return {'success': True}
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error("clear_quantities error for picking %s: %s", picking_id, str(e), exc_info=True)
            return {'error': _('Lỗi khi làm mới: %s', str(e))}

    @http.route('/hlv_mobile_barcode/check_pick_scanned_availability', type='json', auth='user')
    def check_pick_scanned_availability(self, picking_id):
        """
        Kiểm tra tính khả dụng của qty_scanned đã lưu khi user vào lại phiếu PICK.
        Trả về danh sách xung đột nếu tồn kho thực tế tại vị trí đã thay đổi.
        """
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists() or not _is_pick_picking(picking):
            return {'has_conflicts': False, 'conflicts': [], 'has_saved_data': False}

        conflicts = []
        has_saved_data = False

        for ml in picking.move_line_ids:
            if ml.qty_scanned <= 0:
                continue
            has_saved_data = True

            # Tính available qty tại vị trí lấy hàng của move line này
            child_loc_ids = request.env['stock.location'].sudo().search(
                [('id', 'child_of', ml.location_id.id)]
            ).ids
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', ml.product_id.id),
                ('location_id', 'child_of', ml.location_id.id),
                ('company_id', '=', picking.company_id.id),
                ('package_id', '=', ml.package_id.id if ml.package_id else False),
            ])
            free_qty = sum(q.quantity - q.reserved_quantity for q in quants)
            # Cộng thêm phần đã reserve bởi picking này (tránh đếm nhầm)
            reserved_by_this = sum(
                m.product_uom_id._compute_quantity(m.quantity_product_uom, ml.product_id.uom_id)
                for m in picking.move_line_ids
                if m.product_id == ml.product_id and m.location_id.id in child_loc_ids
                and (m.package_id.id if m.package_id else False) == (ml.package_id.id if ml.package_id else False)
            )
            available_qty = free_qty + reserved_by_this
            line_assigned_qty = ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            available_qty = min(available_qty, line_assigned_qty)
            scanned_in_base = ml.product_uom_id._compute_quantity(ml.qty_scanned, ml.product_id.uom_id)

            if scanned_in_base > available_qty + 0.001:
                available_qty_display = ml.product_id.uom_id._compute_quantity(
                    max(0.0, available_qty),
                    ml.product_uom_id
                )
                conflicts.append({
                    'move_line_id': ml.id,
                    'product_name': ml.product_id.display_name,
                    'location_name': ml.location_id.display_name,
                    'saved_qty': ml.qty_scanned,
                    'available_qty': available_qty_display,
                    'uom_name': ml.product_uom_id.name,
                })

        return {
            'has_conflicts': bool(conflicts),
            'conflicts': conflicts,
            'has_saved_data': has_saved_data,
        }

    @http.route('/hlv_mobile_barcode/cap_pick_scanned_to_available', type='json', auth='user')
    def cap_pick_scanned_to_available(self, picking_id):
        """
        Khi có xung đột tồn kho, user chọn 'Lấy số tối đa':
        Giảm qty_scanned của từng move line xuống mức khả dụng thực tế.
        """
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists() or not _is_pick_picking(picking):
            return {'error': _('Phiếu không hợp lệ')}

        for ml in picking.move_line_ids:
            if ml.qty_scanned <= 0:
                continue
            child_loc_ids = request.env['stock.location'].sudo().search(
                [('id', 'child_of', ml.location_id.id)]
            ).ids
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', ml.product_id.id),
                ('location_id', 'child_of', ml.location_id.id),
                ('company_id', '=', picking.company_id.id),
                ('package_id', '=', ml.package_id.id if ml.package_id else False),
            ])
            free_qty = sum(q.quantity - q.reserved_quantity for q in quants)
            reserved_by_this = sum(
                m.product_uom_id._compute_quantity(m.quantity_product_uom, ml.product_id.uom_id)
                for m in picking.move_line_ids
                if m.product_id == ml.product_id and m.location_id.id in child_loc_ids
                and (m.package_id.id if m.package_id else False) == (ml.package_id.id if ml.package_id else False)
            )
            available_qty = free_qty + reserved_by_this
            line_assigned_qty = ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            available_qty = min(available_qty, line_assigned_qty)
            scanned_in_base = ml.product_uom_id._compute_quantity(ml.qty_scanned, ml.product_id.uom_id)

            if scanned_in_base > available_qty + 0.001:
                # Convert available back to move line's UoM
                capped = ml.product_id.uom_id._compute_quantity(
                    max(0.0, available_qty), ml.product_uom_id
                )
                ml.qty_scanned = capped

        return {'success': True}


    @http.route('/hlv_mobile_barcode/get_return_wizard_data', type='json', auth='user')
    def get_return_wizard_data(self, picking_id):
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
        if picking.state != 'done':
            return {'error': _('Chỉ có thể tạo phiếu trả hàng từ phiếu đã hoàn thành.')}

        Wizard = request.env['stock.return.picking'].sudo().with_context(
            active_model='stock.picking',
            active_id=picking.id,
            active_ids=[picking.id],
        )
        try:
            wizard = Wizard.create({})
        except Exception as e:
            return {'error': _('Không thể mở wizard trả hàng: %s', str(e))}

        lines = []
        for line in wizard.product_return_moves:
            uom = getattr(line, 'uom_id', False) or getattr(line, 'product_uom_id', False)
            lines.append({
                'line_id': line.id,
                'product_id': line.product_id.id,
                'product_name': line.product_id.display_name,
                'quantity': line.quantity,
                'uom_id': uom.id if uom else False,
                'uom_name': uom.name if uom else '',
            })

        if not lines:
            wizard.unlink()
            return {'error': _('Phiếu này không có sản phẩm có thể trả.')}

        return {
            'success': True,
            'wizard_id': wizard.id,
            'picking_id': picking.id,
            'picking_name': picking.name,
            'lines': lines,
        }

    @http.route('/hlv_mobile_barcode/create_return', type='json', auth='user')
    def create_return(self, wizard_id, lines=None, mode='selected'):
        wizard = request.env['stock.return.picking'].sudo().browse(wizard_id)
        if not wizard.exists():
            return {'error': _('Wizard trả hàng không còn tồn tại. Vui lòng mở lại popup trả hàng.')}

        picking = getattr(wizard, 'picking_id', False)
        if not picking:
            return {'error': _('Không xác định được phiếu gốc của wizard trả hàng.')}

        line_by_id = {line.id: line for line in wizard.product_return_moves}
        for item in lines or []:
            try:
                line_id = int(item.get('line_id'))
            except Exception:
                continue
            line = line_by_id.get(line_id)
            if not line:
                continue
            if item.get('remove'):
                line.unlink()
                continue
            try:
                quantity = float(item.get('quantity', 0.0))
            except Exception:
                quantity = 0.0
            line.quantity = quantity

        if not wizard.product_return_moves.exists():
            return {'error': _('Không còn dòng sản phẩm nào để trả.')}

        if mode == 'all':
            if not hasattr(wizard, 'action_create_returns_all'):
                return {'error': _('Odoo hiện tại không có action_create_returns_all.')}
            action_method = wizard.action_create_returns_all
        else:
            action_method = wizard.action_create_returns

        existing_return_ids = request.env['stock.picking'].sudo().search([
            ('return_id', '=', picking.id)
        ]).ids

        try:
            action = action_method()
        except Exception as e:
            return {'error': _('Lỗi khi tạo phiếu trả hàng: %s', str(e))}

        return_picking = request.env['stock.picking'].sudo().browse()
        if isinstance(action, dict):
            res_model = action.get('res_model')
            res_id = action.get('res_id')
            if res_model == 'stock.picking' and res_id:
                return_picking = request.env['stock.picking'].sudo().browse(res_id)

        if not return_picking.exists():
            return_picking = request.env['stock.picking'].sudo().search([
                ('return_id', '=', picking.id),
                ('id', 'not in', existing_return_ids),
            ], order='id desc', limit=1)

        if not return_picking.exists():
            return_picking = request.env['stock.picking'].sudo().search([
                ('return_id', '=', picking.id),
            ], order='id desc', limit=1)

        if not return_picking.exists():
            return {'error': _('Đã gọi trả hàng nhưng không tìm thấy phiếu trả hàng vừa tạo.')}

        return {
            'success': True,
            'return_picking_id': return_picking.id,
            'return_picking_name': return_picking.name,
        }


    @http.route('/hlv_mobile_barcode/clear_and_cancel_picking', type='json', auth='user')
    def clear_and_cancel_picking(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'success': True}
            
        if picking.state == 'done':
            return {'error': _('Phiếu đã hoàn thành, không thể hủy.')}

        # Không cho phép tự động hủy phiếu Bước 2
        if picking.source_transfer_id:
            return {'error': _('Không thể hủy phiếu Bước 2 được tự động sinh ra. Bạn sẽ thoát khỏi phiếu mà không hủy.')}
            
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

        if _is_pick_picking(picking) and not _is_return_picking(picking):
            return {'error': _('Không được phép xóa sản phẩm trong phiếu Lấy hàng (PICK). Nếu sai, vui lòng thoát và xóa số lượng, hoặc hủy phiếu ngoài hệ thống để tạo lại.')}

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

    @http.route('/hlv_mobile_barcode/unpack_package', type='json', auth='user')
    def unpack_package(self, picking_id, package_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state in ['done', 'cancel']:
            return {'error': _('Phiếu không tồn tại hoặc đã hoàn thành/hủy.')}
            
        move_lines = request.env['stock.move.line'].search([
            ('picking_id', '=', picking.id),
            '|',
            ('result_package_id', '=', package_id),
            ('package_id', '=', package_id)
        ])
        
        if not move_lines:
            return {'error': _('Không tìm thấy sản phẩm nào trong kiện này.')}
            
        move_lines.write({
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
            is_pick_picking = _is_pick_picking(picking) and not _is_return_picking(picking)

            # PICK: ghi đè quantity = qty_scanned trước khi validate
            # Đây là bước chốt: chỉ số lượng thực tế đã quét mới được xác nhận,
            # không phải số lượng Odoo assign tự động
            if is_pick_picking:
                for ml in picking.sudo().move_line_ids:
                    ml.quantity = ml.qty_scanned

            # STRICT PRE-VALIDATION STOCK CHECK
            # To completely prevent negative stock due to concurrent transactions
            pt_type = picking.picking_type_id.code
            pt_code = (picking.picking_type_id.sequence_code or '').upper()
            if _is_return_picking(picking):
                is_putaway = picking.location_dest_id.usage == 'internal'
            else:
                is_putaway = (pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code))

            
            if not is_putaway:
                grouped_mls = {}
                for ml in picking.move_line_ids:
                    if ml.quantity > 0 and ml.product_id.type == 'product':
                        key = (ml.product_id.id, ml.location_id.id, ml.package_id.id if ml.package_id else False)
                        if key not in grouped_mls:
                            grouped_mls[key] = {
                                'product': ml.product_id,
                                'location': ml.location_id,
                                'qty_to_consume': 0.0,
                                'reserved_by_this': 0.0
                            }
                        grouped_mls[key]['qty_to_consume'] += ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
                        grouped_mls[key]['reserved_by_this'] += ml.product_uom_id._compute_quantity(ml.quantity_product_uom, ml.product_id.uom_id)
                
                for key, data in grouped_mls.items():
                    product = data['product']
                    location = data['location']
                    qty_to_consume = data['qty_to_consume']
                    reserved_by_this = data['reserved_by_this']
                    
                    quants = request.env['stock.quant'].sudo().search([
                        ('product_id', '=', product.id),
                        ('location_id', '=', location.id),
                        ('company_id', '=', picking.company_id.id),
                        ('package_id', '=', key[2])
                    ])
                    free_qty = sum(q.quantity - q.reserved_quantity for q in quants)
                    available_qty = free_qty + reserved_by_this
                    
                    if qty_to_consume > available_qty:
                        return {
                            'error': _(
                                'LỖI TỒN KHO: Không thể xác nhận!\n'
                                'Số lượng ghi nhận của sản phẩm "%s" tại vị trí "%s" không chính xác '
                                '(đang xác nhận %g nhưng kho chỉ còn tối đa %g khả dụng). '
                                'Vui lòng kiểm tra lại tồn kho thực tế hoặc nhấn "Làm lại" để đồng bộ dữ liệu!',
                                product.display_name,
                                location.display_name,
                                qty_to_consume,
                                available_qty
                            )
                        }

            note = picking.note or ''
            dest_loc_id = None
            if 'DEST_LOC_OVERRIDE:' in note:
                import re
                match = re.search(r'DEST_LOC_OVERRIDE:(\d+)', note)
                if match:
                    dest_loc_id = int(match.group(1))
            res_dict = picking.button_validate()
            
            # Xử lý tự động tạo backorder nếu quét không đủ số lượng
            backorder_info = {}
            if isinstance(res_dict, dict) and res_dict.get('res_model') == 'stock.backorder.confirmation':
                wizard_context = res_dict.get('context', {})
                if 'default_pick_ids' not in wizard_context:
                    wizard_context['default_pick_ids'] = [(4, picking.id)]
                
                existing_backorders = request.env['stock.picking'].search([('backorder_id', '=', picking.id)]).ids
                
                backorder_wizard = request.env['stock.backorder.confirmation'].with_context(wizard_context).create({
                    'pick_ids': [(4, picking.id)]
                })
                backorder_wizard.process()
                
                new_backorders = request.env['stock.picking'].search([
                    ('backorder_id', '=', picking.id),
                    ('id', 'not in', existing_backorders)
                ])
                if new_backorders:
                    backorder_info = {
                        'backorder_created': True,
                        'backorder_id': new_backorders[0].id,
                        'backorder_name': new_backorders[0].name
                    }
            
            # Override destination location for Step 2 if requested
            if dest_loc_id:
                step2_picking = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', picking.id)], limit=1)
                if step2_picking:
                    request.env.cr.execute("""
                        UPDATE stock_picking SET location_dest_id = %s WHERE id = %s
                    """, (dest_loc_id, step2_picking.id))
                    request.env.cr.execute("""
                        UPDATE stock_move SET location_dest_id = %s WHERE picking_id = %s
                    """, (dest_loc_id, step2_picking.id))
                    request.env.cr.execute("""
                        UPDATE stock_move_line SET location_dest_id = %s WHERE picking_id = %s
                    """, (dest_loc_id, step2_picking.id))
                    step2_picking.invalidate_recordset()
                    
            result = {'success': True}
            result.update(backorder_info)
            return result
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
                    'location_barcode': q.location_id.barcode or q.location_id.name,
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
                    'state_desc': {
                        'draft': 'Nháp',
                        'waiting': 'Chờ bước khác',
                        'confirmed': 'Chờ hàng',
                        'partially_available': 'Sẵn sàng một phần',
                        'assigned': 'Sẵn sàng',
                        'done': 'Hoàn thành',
                        'cancel': 'Đã hủy',
                        'Draft': 'Nháp',
                        'Waiting Another Move': 'Chờ bước khác',
                        'Waiting Availability': 'Chờ hàng',
                        'Available': 'Sẵn sàng',
                        'Done': 'Hoàn thành',
                        'Cancelled': 'Đã hủy'
                    }.get(m.state, dict(m._fields['state'].selection).get(m.state, m.state))
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
    def move_location(self, product_id, source_barcode, qty, dest_warehouse_id=False, dest_location_id=False):
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
        target_location_dest_id = transit_loc.id
        override_dest_loc_id = False
        same_warehouse_one_step = _same_warehouse_one_step_enabled()
        
        if dest_location_id:
            dest_loc = request.env['stock.location'].sudo().browse(dest_location_id)
            if dest_loc.exists():
                if dest_loc.warehouse_id and dest_loc.warehouse_id == warehouse and same_warehouse_one_step:
                    # Same warehouse
                    target_location_dest_id = dest_loc.id
                else:
                    override_dest_loc_id = dest_loc.id
                    if dest_loc.warehouse_id and dest_loc.warehouse_id.partner_id:
                        partner_id = dest_loc.warehouse_id.partner_id.id
                        
        if not partner_id and dest_warehouse_id:
            dest_warehouse = request.env['stock.warehouse'].browse(dest_warehouse_id)
            if dest_warehouse.exists() and dest_warehouse.partner_id:
                partner_id = dest_warehouse.partner_id.id
                
        if not partner_id:
            actual_warehouse = warehouse
            if not actual_warehouse:
                actual_warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
            if actual_warehouse and actual_warehouse.partner_id:
                partner_id = actual_warehouse.partner_id.id

        picking_vals = {
            'picking_type_id': picking_type_int.id,
            'location_id': source_loc.id,
            'location_dest_id': target_location_dest_id,
            'partner_id': partner_id,
        }
        
        if override_dest_loc_id:
            picking_vals['note'] = f"DEST_LOC_OVERRIDE:{override_dest_loc_id}\n"
            
        picking_int = request.env['stock.picking'].create(picking_vals)
        
        move_int = request.env['stock.move'].create({
            'name': product.name,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': source_loc.id,
            'location_dest_id': target_location_dest_id,
            'picking_id': picking_int.id,
            'picking_type_id': picking_type_int.id,
        })
        
        picking_int.action_confirm()
        picking_int.action_assign()
        
        for ml in picking_int.move_line_ids:
            ml.quantity = qty
            
        picking_int.button_validate()
        
        # Override step 2 destination if requested
        if override_dest_loc_id:
            step2_picking = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', picking_int.id)], limit=1)
            if step2_picking:
                request.env.cr.execute("""
                    UPDATE stock_picking SET location_dest_id = %s WHERE id = %s
                """, (override_dest_loc_id, step2_picking.id))
                request.env.cr.execute("""
                    UPDATE stock_move SET location_dest_id = %s WHERE picking_id = %s
                """, (override_dest_loc_id, step2_picking.id))
                request.env.cr.execute("""
                    UPDATE stock_move_line SET location_dest_id = %s WHERE picking_id = %s
                """, (override_dest_loc_id, step2_picking.id))
                step2_picking.invalidate_recordset()
                
        picking_in = request.env['stock.picking'].search([('source_transfer_id', '=', picking_int.id)], limit=1)
        in_picking_name = picking_in.name if picking_in else False
        
        return {'success': True, 'in_picking_name': in_picking_name}

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
            for move in picking_int.move_ids:
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
        
        picking_in = request.env['stock.picking'].search([('source_transfer_id', '=', picking_int.id)], limit=1)
        in_picking_name = picking_in.name if picking_in else False
        
        return {'success': True, 'in_picking_name': in_picking_name, 'package_name': package_name}

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
            '|',
            ('result_package_id', '=', package.id),
            ('package_id', '=', package.id)
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
        for move in picking.move_ids:
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
