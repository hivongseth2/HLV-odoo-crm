import logging

from odoo import http, _
# pyrefly: ignore [missing-import]
from odoo.http import request
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

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

def _is_putaway_picking(picking):
    if not picking or not picking.exists():
        return False
    if _is_return_picking(picking):
        return picking.location_dest_id.usage == 'internal'

    if picking.source_transfer_id:
        return True

    pt_type = picking.picking_type_id.code
    pt_code = (picking.picking_type_id.sequence_code or '').upper()
    return pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code)

def _uses_qty_scanned_progress(picking):
    if not picking or not picking.exists():
        return False
    return bool(picking.source_transfer_id) or _is_pick_picking(picking) or _is_putaway_picking(picking) or _is_return_picking(picking)

def _can_edit_packages(picking):
    return bool(
        picking
        and picking.exists()
        and picking.state not in ['done', 'cancel']
        and (not _is_putaway_picking(picking) or _is_return_picking(picking))
    )

def _line_package(line):
    if line.picking_id.source_transfer_id:
        return line.result_package_id
    return line.result_package_id or line.package_id

def _line_in_package(line, package_id):
    return bool(
        line
        and package_id
        and _line_package(line).id == package_id
    )

def _package_write_vals(picking, package_id):
    vals = {'result_package_id': package_id}
    if picking.source_transfer_id:
        vals['package_id'] = package_id
    return vals

def _loose_package_vals():
    return {
        'result_package_id': False,
        'package_id': False,
        'package_level_id': False,
        'package_transfer_qty': 0.0,
        'package_transfer_qty_set': False,
    }

def _pick_line_remaining_qty(move_line):
    return max(0.0, (move_line.quantity or 0.0) - (move_line.qty_scanned or 0.0))

def _can_override_pick_line(move_line):
    return bool(
        move_line
        and move_line.exists()
        and move_line.state not in ['done', 'cancel']
        and not move_line.package_id
        and not move_line.result_package_id
        and not move_line.package_level_id
        and _pick_line_remaining_qty(move_line) > 0
    )

def _redistribute_pick_reservation_to_location(source_line, dest_location):
    """Move the unscanned PICK reservation of one loose line to a scanned source location."""
    if not _can_override_pick_line(source_line):
        raise UserError(_('Dòng lấy hàng đã chọn không còn số lượng chưa quét để đổi vị trí.'))
    if source_line.location_id == dest_location:
        return source_line

    picking = source_line.picking_id
    product = source_line.product_id
    rounding = source_line.product_uom_id.rounding
    qty_to_move = _pick_line_remaining_qty(source_line)

    quant_domain = [
        ('product_id', '=', product.id),
        ('location_id', '=', dest_location.id),
        ('company_id', '=', picking.company_id.id),
        ('package_id', '=', False),
        ('quantity', '>', 0),
    ]
    if source_line.lot_id:
        quant_domain.append(('lot_id', '=', source_line.lot_id.id))
    else:
        quant_domain.append(('lot_id', '=', False))
    if source_line.owner_id:
        quant_domain.append(('owner_id', '=', source_line.owner_id.id))
    else:
        quant_domain.append(('owner_id', '=', False))

    quants = request.env['stock.quant'].sudo().search(quant_domain)
    available_qty = sum(quant.quantity - quant.reserved_quantity for quant in quants)
    if float_compare(available_qty, 0.0, precision_rounding=rounding) <= 0:
        raise UserError(_(
            'Không có tồn khả dụng của sản phẩm "%s" tại vị trí "%s" để đổi kệ.',
            product.display_name,
            dest_location.display_name,
        ))

    if float_compare(available_qty, qty_to_move, precision_rounding=rounding) < 0:
        qty_to_move = available_qty

    actual_dest_location = dest_location
    matching_quant = quants[:1]
    if matching_quant:
        actual_dest_location = matching_quant.location_id

    dest_line = source_line.move_id.move_line_ids.filtered(
        lambda ml: (
            ml.id != source_line.id
            and ml.state not in ['done', 'cancel']
            and ml.product_id == product
            and ml.location_id == actual_dest_location
            and ml.location_dest_id == source_line.location_dest_id
            and ml.product_uom_id == source_line.product_uom_id
            and ml.lot_id == source_line.lot_id
            and ml.owner_id == source_line.owner_id
            and not ml.package_id
            and not ml.result_package_id
            and not ml.package_level_id
        )
    )[:1]

    source_new_qty = source_line.quantity - qty_to_move
    if float_compare(source_new_qty, 0.0, precision_rounding=rounding) <= 0:
        source_line.with_context(skip_qty_validation=True).write({'quantity': 0.0})
    else:
        source_line.with_context(skip_qty_validation=True).write({'quantity': source_new_qty})

    if dest_line:
        dest_line.with_context(skip_qty_validation=True).write({
            'quantity': dest_line.quantity + qty_to_move,
        })
    else:
        dest_line = request.env['stock.move.line'].sudo().with_context(skip_qty_validation=True).create({
            'move_id': source_line.move_id.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': source_line.product_uom_id.id,
            'location_id': actual_dest_location.id,
            'location_dest_id': source_line.location_dest_id.id,
            'lot_id': source_line.lot_id.id or False,
            'owner_id': source_line.owner_id.id or False,
            'quantity': qty_to_move,
            'qty_scanned': 0.0,
        })

    if not _can_override_pick_line(dest_line):
        raise UserError(_('Không thể tạo dòng lấy hàng mới tại vị trí "%s". Giao dịch đã được hoàn tác.', dest_location.display_name))
    return dest_line

def _step2_canonical_line_entries(picking):
    """Use current Step 2 lines while validating totals against the source transfer.
    Relaxed strict equality to support backorders (where Step 2 demand < Step 1 done).
    """
    if not picking or not picking.exists() or not picking.source_transfer_id:
        return [], []

    source_lines = picking.source_transfer_id.move_line_ids.filtered(
        lambda ml: ml.quantity > 0 and ml.state not in ['cancel']
    ).sorted('id')
    
    # In Odoo 18, newly created backorders might have quantity = 0, but quantity_product_uom > 0
    target_lines = picking.move_line_ids.filtered(
        lambda ml: (ml.quantity > 0 or ml.quantity_product_uom > 0) and ml.state != 'cancel'
    ).sorted('id')
    
    entries = []
    missing_source_lines = []
    if not target_lines and source_lines:
        missing_source_lines.extend(source_lines)
        return entries, missing_source_lines

    # A Step 2 backorder only carries the remaining products. Do not require
    # products already received on earlier backorders to still exist here.
    for product in target_lines.mapped('product_id'):
        product_source_lines = source_lines.filtered(lambda ml: ml.product_id == product)
        product_target_lines = target_lines.filtered(lambda ml: ml.product_id == product)
        
        source_qty = sum(product_source_lines.mapped('quantity'))
        
        # Use quantity_product_uom (demand) for the target lines, fallback to quantity if needed
        target_qty = sum(product_target_lines.mapped(lambda ml: ml.quantity_product_uom or ml.quantity))
        
        # Allow target_qty to be LESS than source_qty (due to partial backorders)
        if (
            not product_source_lines
            or float_compare(source_qty, target_qty, precision_rounding=product.uom_id.rounding) < 0
        ):
            missing_source_lines.extend(product_source_lines or product_target_lines)
            continue

        for target_line in product_target_lines:
            entries.append({
                'source_line': product_source_lines[0],
                'target_line': target_line,
                'demand': target_line.quantity_product_uom or target_line.quantity,
                'package': _line_package(target_line),
            })

    return entries, missing_source_lines

def _step2_line_error(missing_source_lines):
    products = ', '.join(dict.fromkeys(
        line.product_id.display_name for line in missing_source_lines
    ))
    return _(
        'Phiếu Bước 2 thiếu dòng tương ứng với phiếu nguồn cho sản phẩm: %s. '
        'Vui lòng kiểm tra dữ liệu phiếu trước khi tiếp tục.',
        products,
    )

def _is_new_internal_transfer(picking):
    return bool(
        picking
        and picking.exists()
        and picking.picking_type_id.code == 'internal'
        and not picking.source_transfer_id
        and not _is_return_picking(picking)
        and 'HLV_MOBILE_DYNAMIC_INT' in (picking.note or '')
        and picking.state not in ['done', 'cancel']
    )

def _lock_packages(package_ids):
    package_ids = sorted(set(package_ids))
    if not package_ids:
        return
    request.env.cr.execute(
        'SELECT id FROM stock_quant_package WHERE id IN %s ORDER BY id FOR UPDATE',
        [tuple(package_ids)],
    )
    _lock_package_reservations(package_ids)

def _barcode_operation_error(warehouse, picking_type_code, operation_field):
    if not warehouse or not picking_type_code:
        return None
    use_independent = request.env['ir.config_parameter'].sudo().get_param(
        'hlv_mobile_barcode.hlv_barcode_use_independent_permissions'
    ) == 'True'
    if use_independent:
        Permission = request.env.get('hlv.barcode.user.permission')
    else:
        Permission = request.env.get('warehouse.user.permission')
    if not Permission:
        return None
    if Permission.check_picking_operation(request.env.user, warehouse, picking_type_code, operation_field):
        return None
    operation_label = {
        'can_view': _('xem/quét'),
        'can_edit': _('sửa/quét hàng'),
        'can_delete': _('xóa dòng'),
        'can_confirm': _('xác nhận'),
    }.get(operation_field, operation_field)
    return {
        'error': _(
            'Bạn không có quyền %s phiếu %s tại kho "%s". Vui lòng liên hệ Admin!',
            operation_label,
            picking_type_code,
            warehouse.name,
        )
    }

def _package_positive_quants(package):
    return request.env['stock.quant'].sudo().search([
        ('package_id', '=', package.id),
        ('quantity', '>', 0.0),
    ], order='id')

def _single_package_location(package):
    quants = _package_positive_quants(package)
    if not quants:
        raise UserError(_('Kiện "%s" không còn tồn kho.', package.name))
    locations = quants.mapped('location_id')
    if len(locations) != 1:
        raise UserError(_('Kiện "%s" đang nằm ở nhiều vị trí, không thể xử lý nguyên kiện.', package.name))
    return locations[0]

def _move_package_quants_to_loose(package):
    _lock_packages([package.id])
    Quant = request.env['stock.quant'].sudo()
    package_quants = _package_positive_quants(package)
    if not package_quants:
        raise UserError(_('Kiện "%s" không còn tồn kho để gỡ.', package.name))

    conflicts = request.env['stock.move.line'].sudo().search([
        ('picking_id.state', 'not in', ['done', 'cancel']),
        '|',
        ('package_id', '=', package.id),
        ('result_package_id', '=', package.id),
    ], limit=5)
    if conflicts:
        raise UserError(_(
            'Kiện "%s" đang được giữ bởi phiếu: %s.',
            package.name,
            ', '.join(sorted(set(conflicts.mapped('picking_id.name')))),
        ))

    reserved_quants = package_quants.filtered(
        lambda quant: float_compare(
            quant.reserved_quantity,
            0.0,
            precision_rounding=quant.product_id.uom_id.rounding,
        ) > 0
    )
    if reserved_quants:
        raise UserError(_('Kiện "%s" đang có số lượng được dự trữ bởi nghiệp vụ khác.', package.name))

    moved_qty = 0.0
    for quant in package_quants:
        qty = quant.quantity
        if float_compare(qty, 0.0, precision_rounding=quant.product_id.uom_id.rounding) <= 0:
            continue
            
        if quant.location_id.should_bypass_reservation():
            quant.sudo().write({'package_id': False})
        else:
            Quant._update_available_quantity(
                quant.product_id,
                quant.location_id,
                -qty,
                lot_id=quant.lot_id,
                package_id=package,
                owner_id=quant.owner_id,
            )
            Quant._update_available_quantity(
                quant.product_id,
                quant.location_id,
                qty,
                lot_id=quant.lot_id,
                package_id=False,
                owner_id=quant.owner_id,
            )
        moved_qty += qty
    return moved_qty

def _add_exact_package_to_new_transfer(picking, package):
    """Reserve every physical item from one exact package on a new INT transfer."""
    _lock_packages([package.id])
    package_quants = request.env['stock.quant'].sudo().search([
        ('package_id', '=', package.id),
        ('quantity', '>', 0),
        ('location_id', 'child_of', picking.location_id.id),
    ], order='id')
    all_quants = request.env['stock.quant'].sudo().search([
        ('package_id', '=', package.id),
        ('quantity', '>', 0),
    ])
    if not package_quants or set(package_quants.ids) != set(all_quants.ids):
        raise UserError(_(
            'Kiện "%s" không nằm hoàn toàn trong vị trí nguồn "%s".',
            package.name,
            picking.location_id.display_name,
        ))

    own_lines = picking.move_line_ids.filtered(
        lambda ml: ml.state not in ['done', 'cancel']
        and (ml.package_id == package or ml.result_package_id == package)
    )
    if own_lines:
        raise UserError(_('Kiện "%s" đã được thêm vào phiếu này.', package.name))

    conflicts = request.env['stock.move.line'].sudo().search([
        ('picking_id', '!=', picking.id),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('quantity', '>', 0),
        '|',
        ('package_id', '=', package.id),
        ('result_package_id', '=', package.id),
    ])
    if conflicts:
        raise UserError(_(
            'Kiện "%s" đang được giữ bởi phiếu: %s.',
            package.name,
            ', '.join(sorted(set(conflicts.mapped('picking_id.name')))),
        ))

    unavailable = package_quants.filtered(
        lambda quant: float_compare(
            quant.reserved_quantity,
            0.0,
            precision_rounding=quant.product_id.uom_id.rounding,
        ) > 0
    )
    if unavailable:
        raise UserError(_('Kiện "%s" đang có số lượng được dự trữ bởi nghiệp vụ khác.', package.name))

    moves_by_product = {}
    new_moves = request.env['stock.move']
    for product in package_quants.mapped('product_id'):
        qty = sum(quant.quantity for quant in package_quants.filtered(lambda q: q.product_id == product))
        move = request.env['stock.move'].sudo().create({
            'name': product.display_name,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })
        moves_by_product[product.id] = move
        new_moves |= move

    new_moves._action_confirm(merge=False)
    auto_reserved_lines = new_moves.mapped('move_line_ids')
    if auto_reserved_lines:
        auto_reserved_lines.unlink()

    created_lines = request.env['stock.move.line']
    for quant in package_quants:
        move = moves_by_product[quant.product_id.id]
        qty = quant.product_id.uom_id._compute_quantity(quant.quantity, move.product_uom)
        created_lines |= request.env['stock.move.line'].sudo().create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': quant.product_id.id,
            'product_uom_id': move.product_uom.id,
            'location_id': quant.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'package_id': package.id,
            'result_package_id': package.id,
            'lot_id': quant.lot_id.id or False,
            'owner_id': quant.owner_id.id or False,
            'quantity': qty,
            'package_transfer_qty': qty,
            'package_transfer_qty_set': True,
        })
    return created_lines

def _prepare_partial_packages_for_validation(picking):
    """Keep the remainder in the source package and move the selected part as loose stock."""
    if not _is_new_internal_transfer(picking):
        raise UserError(_('Luồng tách kiện này chỉ áp dụng cho phiếu INT tạo từ Mobile Barcode.'))

    selection_lines = picking.sudo().move_line_ids.filtered(
        lambda ml: ml.package_transfer_qty_set
        and ml.package_id
        and ml.state not in ['done', 'cancel']
    )
    if not selection_lines:
        return

    package_ids = selection_lines.mapped('package_id').ids
    _lock_packages(package_ids)
    conflicts = request.env['stock.move.line'].sudo().search([
        ('picking_id', '!=', picking.id),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('quantity', '>', 0),
        '|',
        ('package_id', 'in', package_ids),
        ('result_package_id', 'in', package_ids),
    ])
    if conflicts:
        raise UserError(_(
            'Không thể tách kiện vì kiện đang được phiếu khác giữ: %s.',
            ', '.join(sorted(set(conflicts.mapped('picking_id.name')))),
        ))

    Quant = request.env['stock.quant'].sudo()
    MoveLine = request.env['stock.move.line'].sudo()
    for package in selection_lines.mapped('package_id'):
        package_lines = selection_lines.filtered(lambda ml: ml.package_id == package)
        has_selected = any(
            float_compare(
                ml.package_transfer_qty,
                0.0,
                precision_rounding=ml.product_uom_id.rounding,
            ) > 0
            for ml in package_lines
        )
        is_partial = any(
            float_compare(
                ml.package_transfer_qty,
                ml.quantity,
                precision_rounding=ml.product_uom_id.rounding,
            ) < 0
            for ml in package_lines
        )
        if not is_partial:
            continue
        if not has_selected:
            package_lines.unlink()
            continue

        package_quants = Quant.search([
            ('package_id', '=', package.id),
            ('quantity', '>', 0),
        ], order='id')
        if not package_quants:
            raise UserError(_('Kiện "%s" không còn tồn kho để tách.', package.name))
        package_qty_by_key = {}
        for quant in package_quants:
            key = (
                quant.product_id.id,
                quant.location_id.id,
                quant.lot_id.id or False,
                quant.owner_id.id or False,
            )
            package_qty_by_key[key] = package_qty_by_key.get(key, 0.0) + quant.quantity

        picking.package_level_ids.filtered(lambda level: level.package_id == package).unlink()

        selected_by_key = {}
        for ml in package_lines:
            key = (
                ml.product_id.id,
                ml.location_id.id,
                ml.lot_id.id or False,
                ml.owner_id.id or False,
            )
            selected_base = ml.product_uom_id._compute_quantity(
                ml.package_transfer_qty,
                ml.product_id.uom_id,
            )
            selected_by_key[key] = selected_by_key.get(key, 0.0) + selected_base

        selected_required_by_key = dict(selected_by_key)
        selected_line_ids = package_lines.filtered(
            lambda ml: float_compare(
                ml.package_transfer_qty,
                0.0,
                precision_rounding=ml.product_uom_id.rounding,
            ) > 0
        ).ids
        # Release the package reservation before changing its physical quant.
        package_lines.with_context(skip_qty_validation=True).write({'quantity': 0.0})
        for quant in package_quants:
            key = (
                quant.product_id.id,
                quant.location_id.id,
                quant.lot_id.id or False,
                quant.owner_id.id or False,
            )
            selected_qty = min(quant.quantity, selected_by_key.get(key, 0.0))
            selected_by_key[key] = max(0.0, selected_by_key.get(key, 0.0) - selected_qty)
            if float_compare(
                selected_qty,
                0.0,
                precision_rounding=quant.product_id.uom_id.rounding,
            ) <= 0:
                continue
            Quant._update_available_quantity(
                quant.product_id,
                quant.location_id,
                -selected_qty,
                lot_id=quant.lot_id,
                package_id=package,
                owner_id=quant.owner_id,
            )
            Quant._update_available_quantity(
                quant.product_id,
                quant.location_id,
                selected_qty,
                lot_id=quant.lot_id,
                package_id=False,
                owner_id=quant.owner_id,
            )

        unmatched = [
            key for key, qty in selected_by_key.items()
            if float_compare(
                qty,
                0.0,
                precision_rounding=request.env['product.product'].browse(key[0]).uom_id.rounding,
            ) > 0
        ]
        if unmatched:
            raise UserError(_('Số lượng chọn chuyển không khớp tồn vật lý của kiện "%s".', package.name))

        for ml in package_lines:
            if float_compare(
                ml.package_transfer_qty,
                0.0,
                precision_rounding=ml.product_uom_id.rounding,
            ) <= 0:
                ml.unlink()
                continue
            ml.with_context(skip_qty_validation=True).write({
                'quantity': ml.package_transfer_qty,
                'package_id': False,
                'result_package_id': False,
                'package_level_id': False,
            })

        for key, selected_qty in selected_required_by_key.items():
            product = request.env['product.product'].browse(key[0])
            picked_loose_qty = sum(
                ml.product_uom_id._compute_quantity(ml.quantity, product.uom_id)
                for ml in MoveLine.search([
                    ('id', 'in', selected_line_ids),
                    ('product_id', '=', key[0]),
                    ('location_id', '=', key[1]),
                    ('lot_id', '=', key[2]),
                    ('owner_id', '=', key[3]),
                    ('package_id', '=', False),
                    ('result_package_id', '=', False),
                    ('quantity', '>', 0),
                ])
            )
            if float_compare(
                picked_loose_qty,
                selected_qty,
                precision_rounding=product.uom_id.rounding,
            ) != 0:
                raise UserError(_('Reservation hàng lẻ chuyển đi từ kiện "%s" không khớp.', package.name))
            loose_qty = sum(Quant.search([
                ('product_id', '=', key[0]),
                ('location_id', '=', key[1]),
                ('lot_id', '=', key[2]),
                ('owner_id', '=', key[3]),
                ('package_id', '=', False),
            ]).mapped('quantity'))
            if float_compare(
                loose_qty,
                selected_qty,
                precision_rounding=product.uom_id.rounding,
            ) < 0:
                raise UserError(_('Kiểm tra hàng lẻ chuyển đi từ kiện "%s" không khớp.', package.name))
        old_package_lines = MoveLine.search([
            ('picking_id', '=', picking.id),
            ('state', 'not in', ['done', 'cancel']),
            ('quantity', '>', 0),
            '|',
            ('package_id', '=', package.id),
            ('result_package_id', '=', package.id),
        ])
        if old_package_lines:
            raise UserError(_(
                'Phiếu chuyển vẫn còn giữ kiện cũ "%s". Giao dịch đã được hoàn tác.',
                package.name,
            ))
        old_package_qty = sum(Quant.search([
            ('package_id', '=', package.id),
            ('quantity', '>', 0),
        ]).mapped('quantity'))
        if float_compare(old_package_qty, 0.0, precision_rounding=0.00001) <= 0:
            raise UserError(_(
                'Kiện cũ "%s" không còn phần hàng ở lại kho nguồn. Giao dịch đã được hoàn tác.',
                package.name,
            ))
        for key, original_qty in package_qty_by_key.items():
            product = request.env['product.product'].browse(key[0])
            expected_remaining = original_qty - selected_required_by_key.get(key, 0.0)
            actual_remaining = sum(Quant.search([
                ('product_id', '=', key[0]),
                ('location_id', '=', key[1]),
                ('lot_id', '=', key[2]),
                ('owner_id', '=', key[3]),
                ('package_id', '=', package.id),
            ]).mapped('quantity'))
            if float_compare(
                actual_remaining,
                expected_remaining,
                precision_rounding=product.uom_id.rounding,
            ) != 0:
                raise UserError(_('Phần còn lại trong kiện "%s" không khớp.', package.name))

    for move in picking.sudo().move_ids.filtered(lambda m: m.state not in ['done', 'cancel']):
        demand = sum(
            ml.product_uom_id._compute_quantity(ml.quantity, move.product_uom)
            for ml in move.move_line_ids
            if ml.state != 'cancel' and ml.quantity > 0
        )
        move.product_uom_qty = demand
    empty_moves = picking.sudo().move_ids.filtered(
        lambda move: move.state not in ['done', 'cancel']
        and not move.move_line_ids
        and not move.move_orig_ids
    )
    if empty_moves:
        empty_moves._action_cancel()
        empty_moves.unlink()
    return

def _lock_package_reservations(package_ids):
    if not package_ids:
        return
    request.env.cr.execute(
        'SELECT id FROM stock_quant WHERE package_id IN %s ORDER BY id FOR UPDATE',
        [tuple(package_ids)],
    )
    request.env.cr.execute(
        '''
            SELECT id
              FROM stock_move_line
             WHERE state NOT IN ('done', 'cancel')
               AND (package_id IN %s OR result_package_id IN %s)
             ORDER BY id
             FOR UPDATE
        ''',
        [tuple(package_ids), tuple(package_ids)],
    )

def _reserve_exact_packages(backorder, package_infos):
    if not package_infos:
        return

    grouped_infos = {}
    for info in package_infos:
        key = (
            info['product_id'],
            info['location_id'],
            info['location_dest_id'],
            info['package_id'],
            info['product_uom_id'],
            info['lot_id'],
            info['owner_id'],
        )
        if key in grouped_infos:
            grouped_infos[key]['qty_remaining'] += info['qty_remaining']
        else:
            grouped_infos[key] = dict(info)
    package_infos = list(grouped_infos.values())

    package_ids = sorted({info['package_id'] for info in package_infos if info['package_id']})
    _lock_package_reservations(package_ids)
    MoveLine = request.env['stock.move.line'].sudo().with_context(skip_qty_validation=True)
    package_conflicts = MoveLine.search([
        ('picking_id', '!=', backorder.id),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('quantity', '>', 0),
        '|',
        ('package_id', 'in', package_ids),
        ('result_package_id', 'in', package_ids),
    ])
    invalid_conflicts = package_conflicts.filtered(lambda ml: not ml.picking_id.source_transfer_id)
    if invalid_conflicts:
        raise UserError(_(
            'Kiện cần chuyển đang được dự trữ bởi phiếu không phải Bước 2: %s. '
            'Không thể tự động lấy lại kiện.',
            ', '.join(invalid_conflicts.mapped('picking_id.name')),
        ))
    displaced_pickings = package_conflicts.mapped('picking_id')
    package_conflicts.unlink()
    for displaced in displaced_pickings:
        displaced.message_post(body=_(
            'Reservation kiện đã được chuyển sang phiếu tách ưu tiên "%s".',
            backorder.name,
        ))
        displaced.move_ids._recompute_state()

    for info in package_infos:
        product = request.env['product.product'].sudo().browse(info['product_id'])
        rounding = request.env['uom.uom'].sudo().browse(info['product_uom_id']).rounding
        qty_to_reserve = info['qty_remaining']
        existing_exact_lines = MoveLine.search([
            ('picking_id', '=', backorder.id),
            ('product_id', '=', info['product_id']),
            ('location_id', '=', info['location_id']),
            ('lot_id', '=', info['lot_id']),
            ('owner_id', '=', info['owner_id']),
            '|',
            ('package_id', '=', info['package_id']),
            ('result_package_id', '=', info['package_id']),
        ])
        existing_exact_lines.unlink()

        package_quants = request.env['stock.quant'].sudo().search([
            ('product_id', '=', info['product_id']),
            ('location_id', '=', info['location_id']),
            ('package_id', '=', info['package_id']),
            ('lot_id', '=', info['lot_id']),
            ('owner_id', '=', info['owner_id']),
        ])
        available_qty = sum(
            quant.quantity - quant.reserved_quantity for quant in package_quants
        )
        if float_compare(available_qty, qty_to_reserve, precision_rounding=rounding) < 0:
            raise UserError(_(
                'Kiện "%s" không còn đủ số lượng khả dụng của sản phẩm "%s" để gán cho phiếu tách '
                '(%g/%g).',
                request.env['stock.quant.package'].browse(info['package_id']).name,
                product.display_name,
                available_qty,
                qty_to_reserve,
            ))

        matching_moves = backorder.move_ids.filtered(
            lambda move: move.product_id.id == info['product_id'] and move.state not in ['done', 'cancel']
        )
        if not matching_moves:
            raise UserError(_(
                'Phiếu tách "%s" không có dòng sản phẩm "%s" để gán kiện.',
                backorder.name,
                product.display_name,
            ))

        MoveLine.create({
            'move_id': matching_moves[0].id,
            'picking_id': backorder.id,
            'product_id': info['product_id'],
            'product_uom_id': info['product_uom_id'],
            'location_id': info['location_id'],
            'location_dest_id': info['location_dest_id'] or backorder.location_dest_id.id,
            'package_id': info['package_id'],
            'result_package_id': info['package_id'],
            'lot_id': info['lot_id'],
            'owner_id': info['owner_id'],
            'quantity': qty_to_reserve,
            'picked': False,
        })

        reserved_qty = sum(MoveLine.search([
            ('picking_id', '=', backorder.id),
            ('product_id', '=', info['product_id']),
            ('location_id', '=', info['location_id']),
            ('package_id', '=', info['package_id']),
            ('lot_id', '=', info['lot_id']),
            ('owner_id', '=', info['owner_id']),
            ('quantity', '>', 0),
            ('state', 'not in', ['done', 'cancel']),
        ]).mapped('quantity'))
        if float_compare(reserved_qty, qty_to_reserve, precision_rounding=rounding) != 0:
            raise UserError(_(
                'Không thể gán chính xác kiện "%s" cho phiếu tách "%s" (%g/%g).',
                request.env['stock.quant.package'].browse(info['package_id']).name,
                backorder.name,
                reserved_qty,
                qty_to_reserve,
            ))

    backorder.move_ids._recompute_state()
    remaining_conflicts = MoveLine.search([
        ('picking_id', '!=', backorder.id),
        ('picking_id.state', 'not in', ['done', 'cancel']),
        ('quantity', '>', 0),
        '|',
        ('package_id', 'in', package_ids),
        ('result_package_id', 'in', package_ids),
    ])
    if remaining_conflicts:
        raise UserError(_(
            'Vẫn còn phiếu khác giữ reservation của kiện: %s. Giao dịch đã được hoàn tác.',
            ', '.join(remaining_conflicts.mapped('picking_id.name')),
        ))

def _same_warehouse_one_step_enabled():
    param = request.env['ir.config_parameter'].sudo().get_param(
        'hlv_mobile_barcode.hlv_barcode_same_warehouse_one_step',
        'True'
    )
    return str(param).strip().lower() in ['true', '1']

def _pick_assignment_error(picking):
    try:
        picking._check_hlv_mobile_pick_assignment_access(user=request.env.user)
    except UserError as error:
        return {'error': str(error)}
    return False

# Bảo vệ idempotency cho move_location / move_location_batch: tránh tạo phiếu INT
# trùng nhau khi 2 RPC gần nhau (double-click, retry, hay 2 client).
MOBILE_DYN_MOVE_WINDOW_SECONDS = 10
MOBILE_DYN_MOVE_MARKER = 'HLV_MOBILE_DYN_MOVE'


def _find_recent_mobile_dyn_move_picking(source_loc, dest_loc, marker_value):
    """Trả về picking INT gần đây của cùng user khớp marker (idempotency)."""
    from datetime import datetime, timedelta
    window_start = datetime.now() - timedelta(seconds=MOBILE_DYN_MOVE_WINDOW_SECONDS)
    note_token = '{}:{}'.format(MOBILE_DYN_MOVE_MARKER, marker_value)
    candidates = request.env['stock.picking'].sudo().search([
        ('picking_type_id.code', '=', 'internal'),
        ('create_date', '>=', window_start),
        ('create_uid', '=', request.env.user.id),
        ('location_id', '=', source_loc.id),
        '|',
        ('location_dest_id', '=', dest_loc.id if dest_loc else False),
        ('note', 'like', note_token),
    ], order='id desc', limit=20)
    # Lọc chính xác theo marker trong note để tránh match nhầm picking khác.
    for picking in candidates:
        if note_token in (picking.note or ''):
            return picking
    return request.env['stock.picking'].browse()


def _build_mobile_dyn_move_marker(product, dest_loc, qty, extra=''):
    base = '{p}:{l}:{q}:{e}'.format(
        p=product.id,
        l=dest_loc.id if dest_loc else 0,
        q=qty,
        e=extra,
    )
    return base


def _lock_source_quants(product, source_loc):
    """Khóa row quants nguồn để chống 2 request đồng thời tranh quant."""
    request.env.cr.execute(
        """
            SELECT id
              FROM stock_quant
             WHERE product_id = %s
               AND location_id = %s
               AND quantity > 0
             ORDER BY id
             FOR UPDATE
        """,
        (product.id, source_loc.id),
    )


class HLVMobileBarcodeLocationMove(http.Controller):


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
    def create_empty_int(self, location_id=None, dest_warehouse_id=False, dest_location_id=False, is_multi_location=False, source_warehouse_id=False, package_id=False):
        source_loc = request.env['stock.location'].browse()
        warehouse = None
        package = request.env['stock.quant.package'].sudo().browse()

        if package_id:
            package = request.env['stock.quant.package'].sudo().browse(int(package_id))
            if not package.exists():
                return {'error': _('Không tìm thấy kiện hàng')}
            if not location_id:
                try:
                    location_id = _single_package_location(package).id
                except UserError as error:
                    return {'error': str(error)}
        
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

        if package:
            permission_error = _barcode_operation_error(
                warehouse,
                picking_type_int.sequence_code or 'INT',
                'can_edit',
            )
            if permission_error:
                return permission_error

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
            'note': 'HLV_MOBILE_DYNAMIC_INT\n',
        }
        
        if override_dest_loc_id:
            picking_vals['note'] += f"DEST_LOC_OVERRIDE:{override_dest_loc_id}\n"
            
        picking_int = request.env['stock.picking'].create(picking_vals)

        if package:
            try:
                with request.env.cr.savepoint():
                    _add_exact_package_to_new_transfer(picking_int, package)
            except UserError as error:
                picking_int.sudo().unlink()
                return {'error': str(error)}
            except Exception as error:
                picking_int.sudo().unlink()
                return {'error': str(error)}
        
        # Empty INT stays draft; package-prefilled INT may be confirmed by move creation.
        return {
            'success': True, 
            'picking_id': picking_int.id, 
            'picking_name': picking_int.name, 
            'warehouse_code': picking_int.picking_type_id.warehouse_id.code or 'HLV',
            'location_id': source_loc.id,
            'location_name': source_loc.display_name or source_loc.name,
            'location_dest_name': picking_int.location_dest_id.display_name or picking_int.location_dest_id.name,
            'package_id': package.id if package else False,
            'package_name': package.name if package else False,
        }


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
    def move_location(self, product_id, source_barcode, qty, dest_warehouse_id=False, dest_location_id=False, source_warehouse_id=False):
        qty = float(qty)
        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'error': _('Không tìm thấy sản phẩm')}
            
        if not source_barcode:
            return {'error': _('Mã vạch nguồn không hợp lệ')}
        source_barcode = source_barcode.strip()
        # Tìm vị trí nguồn: ưu tiên barcode, fallback sang name
        source_loc = request.env['stock.location'].sudo().search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            source_loc = request.env['stock.location'].sudo().search([('name', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        # === 3a. Khóa row trên quants nguồn (chống 2 request đồng thời tranh quant) ===
        _lock_source_quants(product, source_loc)
            
        company_id = request.env.company.id
        
        # Get Transit Location
        transit_loc = request.env['stock.location'].sudo().search([
            ('usage', '=', 'transit'), 
            ('company_id', 'in', [False, company_id])
        ], limit=1)
        
        if not transit_loc:
            return {'error': _('Không tìm thấy kho trung chuyển (Transit Location)')}
            
        # Determine warehouse using parent_of logic if warehouse_id is missing
        warehouse = source_loc.warehouse_id
        if not warehouse:
            warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
            
        if warehouse and warehouse.int_type_id and warehouse.in_type_id:
            picking_type_int = warehouse.int_type_id
            picking_type_in = warehouse.in_type_id
        else:
            picking_type_int = request.env['stock.picking.type'].sudo().search([('code', '=', 'internal'), ('company_id', '=', company_id)], limit=1)
            picking_type_in = request.env['stock.picking.type'].sudo().search([('code', '=', 'incoming'), ('company_id', '=', company_id)], limit=1)
        
        if not picking_type_int or not picking_type_in:
            return {'error': _('Chưa cấu hình Operation Types (INT, IN)')}

        # 1. Create and Validate INT picking (Source -> Transit or Dest)
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

        try:
            # === 3b. Idempotency check ===
            marker_value = _build_mobile_dyn_move_marker(product, request.env['stock.location'].browse(target_location_dest_id), qty)
            existing = _find_recent_mobile_dyn_move_picking(source_loc, request.env['stock.location'].browse(target_location_dest_id), marker_value)
            if existing:
                in_picking_name = False
                step2_picking = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', existing.id)], limit=1)
                if step2_picking:
                    in_picking_name = step2_picking.name
                return {'success': True, 'in_picking_name': in_picking_name, 'duplicate_blocked': True}

            picking_vals = {
                'picking_type_id': picking_type_int.id,
                'location_id': source_loc.id,
                'location_dest_id': target_location_dest_id,
                'partner_id': partner_id,
                'note': '{}:{}\n'.format(MOBILE_DYN_MOVE_MARKER, marker_value),
            }
            
            if override_dest_loc_id:
                picking_vals['note'] += f"DEST_LOC_OVERRIDE:{override_dest_loc_id}\n"
                
            picking_int = request.env['stock.picking'].sudo().create(picking_vals)
            
            move_int = request.env['stock.move'].sudo().create({
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
            
            # --- FORCE EXACT SOURCE LOCATION ---
            # Xóa các dòng auto-reserve của Odoo để tự tạo thủ công chính xác
            auto_reserved_lines = picking_int.move_ids.mapped('move_line_ids')
            if auto_reserved_lines:
                auto_reserved_lines.sudo().unlink()
                
            # Thay vì gọi action_assign (có thể lấy nhầm từ vị trí con do logic child_of của Odoo), 
            # ta chủ động tạo move_line_ids từ các quant ĐÚNG TẠI source_loc
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', source_loc.id), # Không dùng child_of
                ('quantity', '>', 0)
            ], order='in_date ASC, id ASC')
            
            remaining_qty = qty
            for q in quants:
                if remaining_qty <= 0:
                    break
                take_qty = min(q.quantity, remaining_qty) 
                if take_qty <= 0:
                    continue
                    
                request.env['stock.move.line'].sudo().create({
                    'move_id': move_int.id,
                    'picking_id': picking_int.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': source_loc.id,
                    'location_dest_id': target_location_dest_id,
                    'quantity': take_qty,
                    'lot_id': q.lot_id.id if q.lot_id else False,
                    'package_id': q.package_id.id if q.package_id else False,
                    'owner_id': q.owner_id.id if q.owner_id else False,
                })
                remaining_qty -= take_qty
                
            if remaining_qty > 0:
                # Nếu thiếu quant (do âm kho hoặc lệch), tạo 1 dòng gộp
                request.env['stock.move.line'].sudo().create({
                    'move_id': move_int.id,
                    'picking_id': picking_int.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': source_loc.id,
                    'location_dest_id': target_location_dest_id,
                    'quantity': remaining_qty,
                })
            # -----------------------------------
            
            # Gọi button_validate và xử lý kết quả trả về
            res_validate = picking_int.button_validate()
            
            # Xử lý wizard xác nhận (backorder hoặc immediate transfer)
            if isinstance(res_validate, dict):
                if res_validate.get('res_model') == 'stock.backorder.confirmation':
                    # Tạo backorder cho phần chưa chuyển
                    wizard_context = res_validate.get('context', {})
                    if 'default_pick_ids' not in wizard_context:
                        wizard_context['default_pick_ids'] = [(4, picking_int.id)]
                    backorder_wizard = request.env['stock.backorder.confirmation'].sudo().with_context(wizard_context).create({
                        'pick_ids': [(4, picking_int.id)]
                    })
                    backorder_wizard.process()
                elif res_validate.get('res_model') == 'stock.immediate.transfer':
                    # Immediate transfer wizard: xác nhận chuyển ngay
                    wizard_context = res_validate.get('context', {})
                    if 'default_pick_ids' not in wizard_context:
                        wizard_context['default_pick_ids'] = [(4, picking_int.id)]
                    immediate_wizard = request.env['stock.immediate.transfer'].sudo().with_context(wizard_context).create({
                        'pick_ids': [(4, picking_int.id)]
                    })
                    immediate_wizard.process()
            
            # Kiểm tra phiếu đã thực sự chuyển sang trạng thái done
            picking_int.invalidate_recordset()
            if picking_int.state != 'done':
                return {'error': _('Không thể xác nhận phiếu chuyển kho. Trạng thái hiện tại: %s. Vui lòng kiểm tra tồn kho tại vị trí nguồn.', picking_int.state)}
            
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
                    
            picking_in = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', picking_int.id)], limit=1)
            in_picking_name = picking_in.name if picking_in else False
            
            return {'success': True, 'in_picking_name': in_picking_name}
        except Exception as e:
            _logger.error("move_location error: %s", str(e), exc_info=True)
            return {'error': str(e)}


    @http.route('/hlv_mobile_barcode/move_location_batch', type='json', auth='user')
    def move_location_batch(self, source_barcode, lines, pack=False):
        if not lines:
            return {'error': _('Không có sản phẩm nào để chuyển')}
            
        if not source_barcode:
            return {'error': _('Mã vạch nguồn không hợp lệ')}
        source_barcode = source_barcode.strip()
        # Tìm vị trí nguồn: ưu tiên barcode, fallback sang name
        source_loc = request.env['stock.location'].sudo().search([('barcode', '=', source_barcode)], limit=1)
        if not source_loc:
            source_loc = request.env['stock.location'].sudo().search([('name', '=', source_barcode)], limit=1)
        if not source_loc:
            return {'error': _('Không tìm thấy vị trí nguồn')}
            
        # === 3a. Khóa row trên quants nguồn ===
        product_ids = tuple(line['product_id'] for line in lines)
        if product_ids:
            request.env.cr.execute(
                "SELECT id FROM stock_quant "
                "WHERE product_id IN %s AND location_id = %s AND quantity > 0 "
                "ORDER BY id FOR UPDATE",
                (product_ids, source_loc.id),
            )
            
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

        try:
            # === 3b. Idempotency check ===
            lines_str = ','.join([f"{l['product_id']}-{l['qty']}" for l in sorted(lines, key=lambda x: x['product_id'])])
            marker_value = _build_mobile_dyn_move_marker(request.env['product.product'], transit_loc, 0, extra=lines_str)
            existing = _find_recent_mobile_dyn_move_picking(source_loc, transit_loc, marker_value)
            if existing:
                in_picking_name = False
                step2_picking = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', existing.id)], limit=1)
                if step2_picking:
                    in_picking_name = step2_picking.name
                return {'success': True, 'in_picking_name': in_picking_name, 'duplicate_blocked': True}

            # 1. Create INT picking (Source -> Transit)
            partner_id = False
            actual_warehouse = warehouse
            if not actual_warehouse:
                actual_warehouse = request.env['stock.warehouse'].sudo().search([('view_location_id', 'parent_of', source_loc.id)], limit=1)
            if actual_warehouse and actual_warehouse.partner_id:
                partner_id = actual_warehouse.partner_id.id

            picking_int = request.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type_int.id,
                'location_id': source_loc.id,
                'location_dest_id': transit_loc.id,
                'partner_id': partner_id,
                'note': '{}:{}\n'.format(MOBILE_DYN_MOVE_MARKER, marker_value),
            })
            
            for line in lines:
                product = request.env['product.product'].sudo().browse(line['product_id'])
                if not product.exists():
                    continue
                request.env['stock.move'].sudo().create({
                    'name': _('Mobile Batch Move OUT: %s', product.display_name),
                    'picking_id': picking_int.id,
                    'product_id': product.id,
                    'product_uom_qty': line['qty'],
                    'product_uom': product.uom_id.id,
                    'location_id': source_loc.id,
                    'location_dest_id': transit_loc.id,
                })
            
            picking_int.action_confirm()
            
            # --- FORCE EXACT SOURCE LOCATION ---
            # Xóa các dòng auto-reserve của Odoo để tự tạo thủ công chính xác
            auto_reserved_lines = picking_int.move_ids.mapped('move_line_ids')
            if auto_reserved_lines:
                auto_reserved_lines.sudo().unlink()

            for move in picking_int.move_ids:
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', source_loc.id), # Không dùng child_of
                    ('quantity', '>', 0)
                ], order='in_date ASC, id ASC')
                
                remaining_qty = move.product_uom_qty
                for q in quants:
                    if remaining_qty <= 0:
                        break
                    take_qty = min(q.quantity, remaining_qty)
                    if take_qty <= 0:
                        continue
                        
                    request.env['stock.move.line'].sudo().create({
                        'move_id': move.id,
                        'picking_id': picking_int.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': source_loc.id,
                        'location_dest_id': transit_loc.id,
                        'quantity': take_qty,
                        'lot_id': q.lot_id.id if q.lot_id else False,
                        'package_id': q.package_id.id if q.package_id else False,
                        'owner_id': q.owner_id.id if q.owner_id else False,
                    })
                    remaining_qty -= take_qty
                    
                if remaining_qty > 0:
                    request.env['stock.move.line'].sudo().create({
                        'move_id': move.id,
                        'picking_id': picking_int.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': source_loc.id,
                        'location_dest_id': transit_loc.id,
                        'quantity': remaining_qty,
                    })
            # -----------------------------------
            
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
            
            # Gọi button_validate và xử lý kết quả trả về
            res_validate = picking_int.button_validate()
            
            # Xử lý wizard xác nhận (backorder hoặc immediate transfer)
            if isinstance(res_validate, dict):
                if res_validate.get('res_model') == 'stock.backorder.confirmation':
                    wizard_context = res_validate.get('context', {})
                    if 'default_pick_ids' not in wizard_context:
                        wizard_context['default_pick_ids'] = [(4, picking_int.id)]
                    backorder_wizard = request.env['stock.backorder.confirmation'].sudo().with_context(wizard_context).create({
                        'pick_ids': [(4, picking_int.id)]
                    })
                    backorder_wizard.process()
                elif res_validate.get('res_model') == 'stock.immediate.transfer':
                    wizard_context = res_validate.get('context', {})
                    if 'default_pick_ids' not in wizard_context:
                        wizard_context['default_pick_ids'] = [(4, picking_int.id)]
                    immediate_wizard = request.env['stock.immediate.transfer'].sudo().with_context(wizard_context).create({
                        'pick_ids': [(4, picking_int.id)]
                    })
                    immediate_wizard.process()
            
            # Kiểm tra phiếu đã thực sự chuyển sang trạng thái done
            picking_int.invalidate_recordset()
            if picking_int.state != 'done':
                return {'error': _('Không thể xác nhận phiếu chuyển kho hàng loạt. Trạng thái: %s', picking_int.state)}
            
            picking_in = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', picking_int.id)], limit=1)
            in_picking_name = picking_in.name if picking_in else False
            
            return {'success': True, 'in_picking_name': in_picking_name, 'package_name': package_name}
        except Exception as e:
            _logger.error("move_location_batch error: %s", str(e), exc_info=True)
            return {'error': str(e)}
