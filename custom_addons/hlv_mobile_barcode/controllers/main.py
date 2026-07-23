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
            assignment_error = _pick_assignment_error(picking)
            if assignment_error:
                return assignment_error
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

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
        elif picking.source_transfer_id:
            is_putaway = True
        elif pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
            is_putaway = True

        is_pick_picking = _is_pick_picking(picking) and not is_return_picking
        uses_qty_scanned = _uses_qty_scanned_progress(picking)
        step2_entries, missing_step2_lines = _step2_canonical_line_entries(picking)
        if missing_step2_lines:
            return {'error': _step2_line_error(missing_step2_lines)}

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
        moves_to_render = picking.move_ids
        for move in moves_to_render:
            if move.move_line_ids:
                for ml in move.move_line_ids:
                    if is_putaway:
                        loc_name = ml.location_dest_id.display_name
                    else:
                        loc_name = ml.location_id.display_name

                    package_name = _line_package(ml).name or False
                    
                    # Calculate individual line demand for Step 2
                    line_demand = move.product_uom_qty
                    if is_pick_picking:
                        if ml.quantity <= 0:
                            continue
                        line_demand = ml.quantity
                    elif picking.source_transfer_id:
                        line_demand = ml.quantity
                    elif uses_qty_scanned and is_putaway and len(move.move_line_ids) > 1:
                        if ml.quantity <= 0 and ml.qty_scanned <= 0:
                            continue
                        line_demand = max(ml.quantity, ml.qty_scanned)
                    elif ml.quantity > 0 or len(move.move_line_ids) > 1:
                        line_demand = ml.quantity

                    is_package_transfer_line = bool(
                        _is_new_internal_transfer(picking)
                        and ml.package_transfer_qty_set
                        and (ml.package_id or ml.result_package_id)
                    )
                    if is_package_transfer_line:
                        line_demand = ml.quantity

                    lines.append({
                        'id': ml.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_name': move.product_id.display_name,
                        'product_barcode': move.product_id.barcode,
                        'product_uom_qty': line_demand,
                        # Use qty_scanned as mobile scan progress; quantity is finalized on validate.
                        'qty_done': (
                            ml.package_transfer_qty
                            if is_package_transfer_line
                            else (ml.qty_scanned if uses_qty_scanned else ml.quantity)
                        ),
                        'warehouse_qty': warehouse_qty_by_product.get(move.product_id.id, 0.0),
                        'uom_name': move.product_uom.name,
                        'state': move.state,
                        'location_name': loc_name,
                        'package_name': package_name,
                        'result_package_id': ml.result_package_id.id or False,
                        'package_id': ml.package_id.id or False,
                        'is_package_transfer_line': is_package_transfer_line,
                        'package_physical_qty': ml.quantity if is_package_transfer_line else False,
                    })
            else:
                if is_pick_picking or picking.source_transfer_id:
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
            exact_step2 = request.env['stock.picking'].sudo().search([
                ('source_transfer_id', '=', picking.id),
                ('state', 'not in', ['cancel']),
            ], order='id asc', limit=1)
            if exact_step2:
                linked_picking_id = exact_step2.id
                linked_picking_name = exact_step2.name

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
            ], order='id desc', limit=10) if not linked_picking_id else request.env['mail.message'].browse()
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

            if linked_picking_id:
                linked_picking = request.env['stock.picking'].sudo().browse(linked_picking_id)
                if linked_picking.source_transfer_id != picking:
                    linked_picking_id = False
                    linked_picking_name = False
            
            _logger.info(
                "[LINKED_PICKING_SEARCH] === END for picking %s: result linked_picking_id=%s, linked_picking_name=%s ===",
                picking.name, linked_picking_id, linked_picking_name
            )
            
        packages = []
        # Hỗ trợ cả result_package_id (khi đóng gói ở Bước 1) và package_id (kiện hàng đi kèm ở Bước 2)
        package_source_lines = picking.move_line_ids
        all_pkgs = request.env['stock.quant.package'].browse(list(dict.fromkeys(
            pkg.id for pkg in (_line_package(ml) for ml in package_source_lines) if pkg
        )))
        for pkg in all_pkgs:
            pkg_mls = package_source_lines.filtered(
                lambda ml: _line_package(ml) == pkg
            )
            total_done = sum(ml.quantity for ml in pkg_mls)
            package_lines = [{
                'move_line_id': ml.id,
                'product_name': ml.product_id.display_name,
                'product_barcode': ml.product_id.barcode or '',
                'qty_done': ml.quantity,
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
        qty_button_threshold_param = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_qty_button_threshold', '50.0')
        try:
            qty_button_threshold = float(qty_button_threshold_param)
        except ValueError:
            qty_button_threshold = 50.0

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
            'location_dest_name': picking.location_dest_id.display_name or picking.location_dest_id.name,
            'lines': lines,
            'packages': packages,
            'linked_picking_id': linked_picking_id,
            'linked_picking_name': linked_picking_name,
            'source_transfer_id': picking.source_transfer_id.id if picking.source_transfer_id else False,
            'source_transfer_name': picking.source_transfer_id.name if picking.source_transfer_id else False,
            'is_putaway': is_putaway,
            'can_edit_packages': (
                _can_edit_packages(picking)
                and not (
                    _is_new_internal_transfer(picking)
                    and picking.move_line_ids.filtered('package_transfer_qty_set')
                )
            ),
            'show_qty_buttons': show_qty_buttons,
            'qty_button_threshold': qty_button_threshold,
            'camera_default_on': camera_default_on,
            'is_pick': is_pick_picking,
            'is_return': is_return_picking,
            'return_of_id': picking.return_id.id if is_return_picking else False,
            'return_of_name': picking.return_id.name if is_return_picking else False,
            'has_scanned_data': has_scanned_data,
            'hlv_barcode_auto_cleared': getattr(picking, 'hlv_barcode_auto_cleared', False),
            'packer_name': picking._hlv_mobile_packer_display_name(picking.x_pack_packer_user_id) if picking.x_pack_packer_user_id else '',
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

    @http.route('/hlv_mobile_barcode/process_barcode', type='json', auth='user')
    def process_barcode(self, picking_id, barcode, destination_location_id=None, last_product_id=None, last_move_line_id=None, location_mode=None, is_multi_location=False, preferred_move_line_id=None, force_partial_package=False, create_loose_lines_only=False):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'confirmed', 'assigned']:
            return {'error': _('Phiếu này không thể xử lý thêm sản phẩm.')}

        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

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
        elif picking.source_transfer_id:
            is_putaway = True
        elif pt_type == 'incoming' or (pt_type == 'internal' and 'INT' not in pt_code and 'IN' in pt_code) or picking.location_id.usage == 'transit':
            is_putaway = True
        else:
            is_putaway = False

        if location_mode == 'dest':
            is_putaway = True
        elif location_mode == 'source' and (is_multi_location or is_pick_picking) and not picking.source_transfer_id:
            is_putaway = False

        # Cờ nhận diện phiếu nhập thuần (Incoming Receipt - IN)
        # Dùng cho logic ghi đè location_dest_id khi quét vị trí cụ thể
        is_incoming_receipt = (pt_type == 'incoming') and not is_return_picking and not picking.source_transfer_id
        uses_qty_scanned = _uses_qty_scanned_progress(picking)
        
        # 1. Try to find location first
        location = request.env['stock.location'].sudo().search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
        if location:
            res = {'type': 'location', 'location_id': location.id, 'location_name': location.display_name, 'is_putaway': is_putaway}
            if is_putaway and (preferred_move_line_id or last_move_line_id):
                target_ml_id = False
                is_explicit_selection = False
                try:
                    if preferred_move_line_id:
                        target_ml_id = int(preferred_move_line_id)
                        is_explicit_selection = True
                    elif last_move_line_id:
                        target_ml_id = int(last_move_line_id)
                except (TypeError, ValueError):
                    target_ml_id = False
                    
                updated_ml = request.env['stock.move.line'].browse(target_ml_id)
                if (
                    updated_ml.exists()
                    and updated_ml.picking_id == picking
                    and updated_ml.state not in ['done', 'cancel']
                ):
                    # Nếu là chọn thủ công (tap vào dòng), luôn cho phép đổi location.
                    # Nếu là tự động (từ last_move_line_id):
                    # Không kéo theo sản phẩm khi quét vị trí đối với phiếu nhập IN
                    # Tuy nhiên, nếu sản phẩm đang ở vị trí đích mặc định của phiếu (chưa gán kệ cụ thể), ta gán nó vào kệ vừa quét
                    allow_update = is_explicit_selection or (not is_incoming_receipt and updated_ml.location_dest_id.id == picking.location_dest_id.id)
                    
                    if allow_update:
                        updated_ml.location_dest_id = location.id
                        res['updated_product_id'] = updated_ml.product_id.id
                        res['updated_move_line_id'] = updated_ml.id
            return res

        # 1.5. Try to find package
        package = request.env['stock.quant.package'].sudo().search([('name', '=', barcode)], limit=1)
        if package:
            allow_package = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_package_scan', 'False') == 'True'
            if not allow_package and not _is_new_internal_transfer(picking):
                return {'error': _('Tính năng quét Kiện hàng hiện đang bị tắt trong cấu hình hệ thống!')}
            if _is_new_internal_transfer(picking):
                try:
                    with request.env.cr.savepoint():
                        created_lines = _add_exact_package_to_new_transfer(picking, package)
                except UserError as error:
                    return {'error': str(error)}
                first_line = created_lines[:1]
                return {
                    'success': True,
                    'type': 'package',
                    'product_name': _('Kiện hàng %s đã được thêm toàn bộ vào phiếu.', package.name),
                    'product_id': first_line.product_id.id if first_line else False,
                    'move_line_id': first_line.id if first_line else False,
                    'package_id': package.id,
                }
            if picking.source_transfer_id:
                step2_entries, missing_step2_lines = _step2_canonical_line_entries(picking)
                if missing_step2_lines:
                    return {'error': _step2_line_error(missing_step2_lines)}
                package_entries = [
                    entry for entry in step2_entries if entry['package'] == package
                ]
                if not package_entries:
                    return {'error': _('Kiện hàng "%s" không thuộc phiếu nguồn của phiếu Bước 2.', package.name)}

                processed_lines = []
                for entry in package_entries:
                    target_line = entry['target_line']
                    if destination_location_id and target_line.location_dest_id.id != destination_location_id:
                        target_line.location_dest_id = destination_location_id
                    target_line.qty_scanned = entry['demand']
                    processed_lines.append(f"{entry['demand']} x {target_line.product_id.display_name}")

                first_line = package_entries[0]['target_line']
                return {
                    'success': True,
                    'product_name': f"Kiện hàng {package.name} (Đã quét: {', '.join(processed_lines)})",
                    'product_id': first_line.product_id.id,
                    'move_line_id': first_line.id,
                }

            # We found a package! Let's process the package contents in the picking.
            # A. Check if the picking has a move line for this package_id
            move_lines = picking.move_line_ids.filtered(lambda ml: (ml.package_id == package or ml.result_package_id == package) and ml.state not in ['done', 'cancel'])
            if move_lines:
                processed_lines = []
                updated_move_line = request.env['stock.move.line'].browse()
                updated_product = request.env['product.product'].browse()
                for ml in move_lines:
                    if is_putaway and destination_location_id and ml.location_dest_id.id != destination_location_id:
                        ml.location_dest_id = destination_location_id
                    line_demand = ml.move_id.product_uom_qty or ml.quantity or ml.quantity_product_uom
                    if ml.package_id == package and not ml.result_package_id and not is_pick_picking:
                        ml.result_package_id = package.id
                    
                    if uses_qty_scanned:
                        ml.qty_scanned = line_demand
                        processed_qty = ml.qty_scanned
                    else:
                        ml.quantity = line_demand
                        processed_qty = ml.quantity
                    if not updated_move_line:
                        updated_move_line = ml
                        updated_product = ml.product_id
                    processed_lines.append(f"{processed_qty} x {ml.product_id.display_name}")
                return {
                    'success': True,
                    'product_name': f"Kiện hàng {package.name} (Đã quét: {', '.join(processed_lines)})",
                    'product_id': updated_product.id or False,
                    'move_line_id': updated_move_line.id or False,
                }
            
            # B. If no move lines for this package, search for the products inside the package (quants)
            quants = request.env['stock.quant'].sudo().search([('package_id', '=', package.id)])
            if quants:
                package_source_loc_ids = request.env['stock.location'].sudo().search([('id', 'child_of', picking.location_id.id)]).ids
                
                # --- PRE-CHECK FOR PARTIAL PACKAGE SCENARIOS (PICK) ---
                if is_pick_picking and not force_partial_package and not create_loose_lines_only:
                    for quant in quants:
                        product_in_pkg = quant.product_id
                        reserved_by_this_package = sum(
                            ml.product_uom_id._compute_quantity(ml.quantity_product_uom, product_in_pkg.uom_id)
                            for ml in picking.move_line_ids
                            if ml.product_id == product_in_pkg
                            and ml.location_id == quant.location_id
                            and ml.package_id == package
                        )
                        total_pkg_qty = quant.quantity - quant.reserved_quantity + reserved_by_this_package
                        
                        if total_pkg_qty <= 0 or quant.location_id.usage != 'internal' or quant.location_id.id not in package_source_loc_ids:
                            continue
                        
                        move = picking.move_ids.filtered(
                            lambda m: m.product_id == product_in_pkg and m.state not in ['done', 'cancel']
                        )
                        if not move:
                            return {
                                'action': 'ask_partial_package',
                                'package_id': package.id,
                                'package_name': package.name,
                                'reason': _('Phát hiện sản phẩm không thuộc phiếu!\nKiện %s chứa sản phẩm "%s" nhưng phiếu không yêu cầu lấy sản phẩm này.\nBạn muốn xử lý kiện hàng này như thế nào?', package.name, product_in_pkg.display_name)
                            }
                        
                        move = move[0]
                        current_qty_done = sum(ml.qty_scanned if uses_qty_scanned else ml.quantity for ml in move.move_line_ids)
                        target_qty = move.product_uom_qty
                        
                        if target_qty > 0.0 and current_qty_done + total_pkg_qty > target_qty:
                            needed_qty = max(0.0, target_qty - current_qty_done)
                            return {
                                'action': 'ask_partial_package',
                                'package_id': package.id,
                                'package_name': package.name,
                                'reason': _('Phát hiện dư thừa số lượng!\nKiện %s đang chứa %g %s (%s), nhưng phiếu chỉ yêu cầu lấy thêm %g %s.\nBạn muốn xử lý phần chênh lệch này như thế nào?', package.name, total_pkg_qty, product_in_pkg.uom_id.name, product_in_pkg.display_name, needed_qty, product_in_pkg.uom_id.name)
                            }
                # -----------------------------------------------
                
                processed_products = []
                updated_move_line = request.env['stock.move.line'].browse()
                updated_product = request.env['product.product'].browse()
                for quant in quants:
                    product_in_pkg = quant.product_id
                    reserved_by_this_package = sum(
                        ml.product_uom_id._compute_quantity(ml.quantity_product_uom, product_in_pkg.uom_id)
                        for ml in picking.move_line_ids
                        if ml.product_id == product_in_pkg
                        and ml.location_id == quant.location_id
                        and ml.package_id == package
                    )
                    qty_in_pkg = quant.quantity - quant.reserved_quantity + reserved_by_this_package
                    
                    if qty_in_pkg <= 0 or quant.location_id.usage != 'internal' or quant.location_id.id not in package_source_loc_ids:
                        continue
                    
                    # Find a move for this product in the picking
                    move = picking.move_ids.filtered(
                        lambda m: m.product_id == product_in_pkg and m.state not in ['done', 'cancel']
                    )
                    if not move and not is_pick_picking:
                        allow_add = request.env['ir.config_parameter'].sudo().get_param('hlv_mobile_barcode.hlv_barcode_allow_add_product', 'True') == 'True'
                        if not allow_add:
                            continue
                        move = request.env['stock.move'].create({
                            'name': product_in_pkg.display_name,
                            'picking_id': picking.id,
                            'product_id': product_in_pkg.id,
                            'product_uom_qty': 0.0,
                            'product_uom': product_in_pkg.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': picking.location_dest_id.id,
                        })
                        if picking.state == 'draft':
                            picking.action_confirm()
                            picking = picking.exists()
                        move = picking.move_ids.filtered(
                            lambda m: m.product_id == product_in_pkg and m.state not in ['done', 'cancel']
                        )
                    if move:
                        move = move[0]
                        # Check limit to prevent over-scanning
                        current_qty_done = sum(ml.qty_scanned if uses_qty_scanned else ml.quantity for ml in move.move_line_ids)
                        target_qty = move.product_uom_qty
                        acceptable_qty = qty_in_pkg
                        
                        # In case we can scan, determine how much of this package qty we can accept
                        if target_qty > 0.0 and current_qty_done + acceptable_qty > target_qty:
                            acceptable_qty = max(0.0, target_qty - current_qty_done)
                            
                        if acceptable_qty <= 0:
                            continue
                            
                        # Update or create move line
                        move_line = move.move_line_ids.filtered(
                            lambda ml: (
                                (ml.qty_scanned if uses_qty_scanned else ml.quantity) < ml.quantity_product_uom
                                and not ml.result_package_id
                                and ml.package_id == package
                                and ml.location_id == quant.location_id
                            )
                        )
                        actual_qty_scanned = acceptable_qty
                        if is_pick_picking:
                            loose_lines = move.move_line_ids.filtered(
                                lambda ml: not ml.package_id and not ml.result_package_id and _pick_line_remaining_qty(ml) > 0
                            ).sorted('id')
                            
                            qty_to_steal = acceptable_qty
                            for ll in loose_lines:
                                if qty_to_steal <= 0:
                                    break
                                ll_remaining = _pick_line_remaining_qty(ll)
                                steal_amount = min(qty_to_steal, ll_remaining)
                                ll.with_context(skip_qty_validation=True).write({'quantity': ll.quantity - steal_amount})
                                qty_to_steal -= steal_amount

                            # Xử lý cờ xé kiện
                            actual_qty_scanned = 0.0 if create_loose_lines_only else acceptable_qty
                            actual_result_package_id = False if (force_partial_package or create_loose_lines_only or acceptable_qty < qty_in_pkg) else package.id

                            if move_line:
                                target_move_line = move_line[0]
                                target_move_line.with_context(skip_qty_validation=True).write({
                                    'qty_scanned': target_move_line.qty_scanned + actual_qty_scanned,
                                    'quantity': target_move_line.quantity + (acceptable_qty - qty_to_steal),
                                    'result_package_id': actual_result_package_id
                                })
                            else:
                                new_ml_vals = {
                                    'move_id': move.id,
                                    'picking_id': picking.id,
                                    'product_id': product_in_pkg.id,
                                    'product_uom_id': move.product_uom.id,
                                    'location_id': quant.location_id.id,
                                    'location_dest_id': picking.location_dest_id.id,
                                    'package_id': package.id,
                                    'result_package_id': actual_result_package_id,
                                    'qty_scanned': actual_qty_scanned,
                                    'quantity': acceptable_qty - qty_to_steal,
                                }
                                target_move_line = request.env['stock.move.line'].sudo().with_context(skip_qty_validation=True).create(new_ml_vals)
                        else:
                            if move_line:
                                target_move_line = move_line[0]
                                if uses_qty_scanned:
                                    target_move_line.qty_scanned += acceptable_qty
                                else:
                                    target_move_line.quantity += acceptable_qty
                            else:
                                new_ml_vals = {
                                    'move_id': move.id,
                                    'picking_id': picking.id,
                                    'product_id': product_in_pkg.id,
                                    'product_uom_id': move.product_uom.id,
                                    'location_id': quant.location_id.id,
                                    'location_dest_id': picking.location_dest_id.id,
                                    'package_id': package.id,
                                    'result_package_id': package.id,
                                }
                                if uses_qty_scanned:
                                    new_ml_vals['qty_scanned'] = acceptable_qty
                                else:
                                    new_ml_vals['quantity'] = acceptable_qty
                                target_move_line = request.env['stock.move.line'].sudo().with_context(skip_qty_validation=True).create(new_ml_vals)
                        if not updated_move_line:
                            updated_move_line = target_move_line
                            updated_product = product_in_pkg
                        processed_products.append(f"{actual_qty_scanned} x {product_in_pkg.display_name}")
                
                if processed_products:
                    if create_loose_lines_only:
                        return {
                            'success': True,
                            'product_name': f"Đã chuẩn bị dòng, vui lòng quét lẻ từng sản phẩm trong kiện {package.name}!",
                            'product_id': updated_product.id or False,
                            'move_line_id': updated_move_line.id or False,
                        }
                    else:
                        return {
                            'success': True,
                            'product_name': f"Kiện hàng {package.name} (Đã xử lý: {', '.join(processed_products)})",
                            'product_id': updated_product.id or False,
                            'move_line_id': updated_move_line.id or False,
                        }
            
            return {'error': _('Kiện hàng "%s" không chứa sản phẩm nào phù hợp với phiếu này.', package.name)}

        if (is_pick_picking or (is_multi_location and not is_putaway)) and not destination_location_id:
            return {'error': _('Vui lòng quét mã Vị trí (Kệ hàng) trước khi quét sản phẩm!')}

        product = request.env['product.product'].sudo().search(['|', ('barcode', '=', barcode), ('default_code', '=', barcode)], limit=1)
        if not product:
            return {'error': _('Không tìm thấy mã vạch hợp lệ (Sản phẩm hoặc Vị trí).')}

        if picking.source_transfer_id:
            step2_entries, missing_step2_lines = _step2_canonical_line_entries(picking)
            if missing_step2_lines:
                return {'error': _step2_line_error(missing_step2_lines)}
            product_entries = [
                entry for entry in step2_entries
                if entry['target_line'].product_id == product
                and entry['target_line'].qty_scanned < entry['demand']
            ]
            product_entries.sort(key=lambda entry: (
                1 if entry['package'] else 0,
                entry['target_line'].id,
            ))
            if not product_entries:
                return {'error': _('Sản phẩm "%s" đã được quét đủ số lượng của phiếu Bước 2.', product.display_name)}

            target_entry = None
            if destination_location_id:
                matching_entries = [e for e in product_entries if e['target_line'].location_dest_id.id == destination_location_id]
                if matching_entries:
                    target_entry = matching_entries[0]
                    
            if not target_entry:
                target_entry = product_entries[0]
                target_line = target_entry['target_line']
                
                if destination_location_id and target_line.location_dest_id.id != destination_location_id:
                    if target_line.qty_scanned == 0:
                        target_line.location_dest_id = destination_location_id
                    else:
                        demand_field = 'quantity_product_uom' if hasattr(target_line, 'quantity_product_uom') and target_line.quantity_product_uom else 'quantity'
                        current_demand = getattr(target_line, demand_field)
                        scanned = target_line.qty_scanned
                        remaining = current_demand - scanned
                        
                        if remaining >= 1:
                            write_vals = {'quantity': scanned}
                            if hasattr(target_line, 'quantity_product_uom'):
                                write_vals['quantity_product_uom'] = scanned
                            target_line.with_context(skip_qty_validation=True).write(write_vals)
                            
                        new_line_vals = {
                            'move_id': target_line.move_id.id,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_id': target_line.product_uom_id.id,
                            'location_id': target_line.location_id.id,
                            'location_dest_id': destination_location_id,
                            'lot_id': target_line.lot_id.id or False,
                            'owner_id': target_line.owner_id.id or False,
                            'package_id': target_line.package_id.id or False,
                            'qty_scanned': 1.0,
                            'quantity': remaining if remaining >= 1 else 1.0,
                        }
                        if hasattr(target_line, 'quantity_product_uom'):
                            new_line_vals['quantity_product_uom'] = remaining if remaining >= 1 else 1.0
                            
                        new_line = request.env['stock.move.line'].sudo().with_context(skip_qty_validation=True).create(new_line_vals)
                        return {
                            'success': True,
                            'type': 'product',
                            'product_id': product.id,
                            'product_name': product.display_name,
                            'move_line_id': new_line.id,
                        }
            
            target_line = target_entry['target_line']
            target_line.qty_scanned = min(target_entry['demand'], target_line.qty_scanned + 1)
            return {
                'success': True,
                'type': 'product',
                'product_id': product.id,
                'product_name': product.display_name,
                'move_line_id': target_line.id,
            }

        # Find the move for this product
        move = picking.move_ids.filtered(lambda m: m.product_id == product and m.state not in ['done', 'cancel'])

        def _pick_available_lines(candidate_move):
            lines = candidate_move.move_line_ids.filtered(
                lambda ml: (
                    ml.state not in ['done', 'cancel']
                    and not ml.result_package_id
                    and not ml.package_id
                    and ml.quantity > 0
                    and ml.qty_scanned < ml.quantity
                )
            )
            if destination_location_id:
                lines = lines.filtered(lambda ml: ml.location_id.id == destination_location_id)
            return lines.sorted('id')

        product_moves = move
        preferred_move_line = request.env['stock.move.line'].browse()
        preferred_override_line = request.env['stock.move.line'].browse()
        if is_pick_picking and preferred_move_line_id:
            try:
                preferred_id = int(preferred_move_line_id)
            except (TypeError, ValueError):
                preferred_id = 0
            candidate_line = request.env['stock.move.line'].browse(preferred_id) if preferred_id else preferred_move_line
            if candidate_line.exists() and candidate_line.picking_id == picking and candidate_line.product_id == product:
                if destination_location_id and candidate_line.location_id.id != destination_location_id and _can_override_pick_line(candidate_line):
                    preferred_override_line = candidate_line
                    move = candidate_line.move_id
                if destination_location_id and candidate_line.location_id.id != destination_location_id and not preferred_override_line:
                    return {'error': _('Dòng ưu tiên của sản phẩm "%s" không thuộc vị trí đang quét. Vui lòng chọn đúng dòng tại vị trí này hoặc bỏ chọn ưu tiên!', product.display_name)}
                if _pick_available_lines(candidate_line.move_id).filtered(lambda ml: ml.id == candidate_line.id):
                    preferred_move_line = candidate_line
                    move = candidate_line.move_id
        
        # PRE-CHECK: Physical stock check BEFORE creating any new move
        temp_move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id) if move else []
        ml_src_id = destination_location_id if (destination_location_id and not is_putaway) else (temp_move_line[0].location_id.id if temp_move_line else picking.location_id.id)
        scan_quant = request.env['stock.quant'].sudo().browse()
        scan_package = request.env['stock.quant.package'].sudo().browse()
        
        if not is_putaway:
            source_loc = request.env['stock.location'].sudo().browse(ml_src_id)
            candidate_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', ml_src_id),
                ('company_id', '=', picking.company_id.id),
                ('package_id', '=', False),
            ]).sorted(key=lambda q: (1 if q.package_id else 0, -q.quantity))
            available_qty = 0.0
            processed_qty_from_loc_base = 0.0

            for candidate_quant in candidate_quants:
                candidate_package = candidate_quant.package_id
                reserved_by_this = sum(
                    ml.product_uom_id._compute_quantity(ml.quantity_product_uom, product.uom_id)
                    for ml in picking.move_line_ids
                    if ml.product_id == product
                    and ml.location_id == candidate_quant.location_id
                    and ml.package_id == candidate_package
                )
                candidate_available_qty = candidate_quant.quantity - candidate_quant.reserved_quantity + reserved_by_this
                candidate_processed_qty = sum(
                    ml.product_uom_id._compute_quantity(
                        ml.qty_scanned if is_pick_picking else ml.quantity,
                        product.uom_id
                    )
                    for ml in picking.move_line_ids
                    if ml.product_id == product
                    and ml.location_id == candidate_quant.location_id
                    and ml.package_id == candidate_package
                )
                if candidate_available_qty - candidate_processed_qty > 0:
                    scan_quant = candidate_quant
                    scan_package = candidate_package
                    available_qty = candidate_available_qty
                    processed_qty_from_loc_base = candidate_processed_qty
                    ml_src_id = candidate_quant.location_id.id
                    break
            
            if available_qty <= 0:
                packaged_quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', ml_src_id),
                    ('company_id', '=', picking.company_id.id),
                    ('package_id', '!=', False),
                    ('quantity', '>', 0),
                ], limit=1)
                if packaged_quants:
                    return {'error': _('Sản phẩm "%s" đang nằm trong kiện "%s". Vui lòng quét mã kiện để chuyển nguyên kiện, hoặc gỡ kiện trước khi chuyển lẻ sản phẩm.', product.display_name, packaged_quants.package_id.name)}
                return {'error': _('Sản phẩm "%s" không có tồn kho khả dụng tại vị trí "%s" (bao gồm các vị trí con). Không thể quét!', product.display_name, source_loc.display_name)}
                
            scan_qty_base = 1.0
            if move and move[0].product_uom:
                scan_qty_base = move[0].product_uom._compute_quantity(1.0, product.uom_id)
            
            if processed_qty_from_loc_base + scan_qty_base > available_qty:
                return {'error': _('Số lượng quét vượt quá tồn kho thực tế khả dụng tại vị trí "%s" (Tối đa: %g %s). Không thể quét thêm!', source_loc.display_name, available_qty, product.uom_id.name)}
        
        if not move:
            if picking.source_transfer_id:
                return {'error': _('Không được quét thêm sản phẩm mới vào phiếu Bước 2! Chỉ được quét các sản phẩm đã có trong phiếu.')}
            if is_pick_picking:
                return {'error': _('Sản phẩm "%s" chưa có dòng phân bổ để lấy hàng. Vui lòng chờ hệ thống assign trước khi quét!', product.display_name)}
            
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
        elif preferred_move_line:
            move = preferred_move_line.move_id
        else:
            # Select the most appropriate move if there are multiple
            if is_pick_picking:
                moves_with_available_line = move.filtered(lambda m: bool(_pick_available_lines(m)))
                if moves_with_available_line:
                    incomplete_moves = moves_with_available_line
                elif destination_location_id:
                    moves_with_loc = move.filtered(lambda m: destination_location_id in m.move_line_ids.mapped('location_id').ids)
                    incomplete_moves = moves_with_loc if moves_with_loc else move.filtered(lambda m: m.product_uom_qty > sum(m.move_line_ids.mapped('qty_scanned')))
                else:
                    incomplete_moves = move.filtered(lambda m: m.product_uom_qty > sum(m.move_line_ids.mapped('qty_scanned')))
            else:
                qty_field = 'qty_scanned' if uses_qty_scanned else 'quantity'
                incomplete_moves = move.filtered(lambda m: m.product_uom_qty > sum(m.move_line_ids.mapped(qty_field)))
            target_moves = incomplete_moves if incomplete_moves else move
            
            best_move = False
            if len(target_moves) > 1 and destination_location_id:
                if is_pick_picking:
                    moves_with_loc = target_moves.filtered(lambda m: bool(_pick_available_lines(m)))
                    if not moves_with_loc:
                        moves_with_loc = target_moves.filtered(lambda m: destination_location_id in m.move_line_ids.mapped('location_id').ids)
                    if moves_with_loc:
                        best_move = moves_with_loc[0]
                elif is_putaway and not is_return_picking:
                    moves_with_loc = target_moves.filtered(lambda m: destination_location_id in m.move_line_ids.mapped('location_dest_id').ids)
                    if moves_with_loc:
                        best_move = moves_with_loc[0]
            
            move = best_move if best_move else target_moves[0]

        # Check limit to prevent over-scanning (demand-based)
        if picking.source_transfer_id and is_putaway:
            line_demand = move.product_uom_qty
            step2_qty_done = sum(ml.qty_scanned if uses_qty_scanned else ml.quantity for ml in move.move_line_ids)
            if line_demand > 0.0 and step2_qty_done + 1 > line_demand:
                return {'error': _('Sản phẩm "%s" đã quét đủ số lượng yêu cầu của phiếu Bước 2 (%g/%g). Không thể quét thêm!', product.display_name, step2_qty_done, line_demand)}
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

            if total_assigned <= 0:
                return {'error': _('Sản phẩm "%s" chưa có số lượng phân bổ để lấy hàng. Vui lòng chờ hệ thống assign trước khi quét!', product.display_name)}

            max_allowed = min(move.product_uom_qty, total_assigned)
            
            if move.product_uom_qty > 0.0 and current_qty_scanned + 1 > max_allowed:
                return {'error': _('Sản phẩm "%s" đã quét đủ số lượng yêu cầu và thực tế (%g/%g). Không thể quét thêm!', product.display_name, current_qty_scanned, max_allowed)}
        elif not picking.source_transfer_id:
            current_qty_done = sum(ml.qty_scanned if uses_qty_scanned else ml.quantity for ml in move.move_line_ids)
            if move.product_uom_qty > 0.0 and current_qty_done + 1 > move.product_uom_qty:
                return {'error': _('Sản phẩm "%s" đã quét đủ tổng số lượng yêu cầu của dòng này (%g/%g). Không thể quét thêm!', product.display_name, current_qty_done, move.product_uom_qty)}

        # Step 2 putaway must update the existing Odoo-created move lines, including package lines.
        if picking.source_transfer_id and is_putaway:
            move_line = move.move_line_ids.filtered(lambda ml: ml.state not in ['done', 'cancel'])
            available_move_line = move_line.filtered(
                lambda ml: not ml.quantity_product_uom or (ml.qty_scanned if uses_qty_scanned else ml.quantity) < ml.quantity_product_uom
            )
            if available_move_line:
                move_line = available_move_line
            if not move_line:
                return {'error': _('Không tìm thấy dòng Bước 2 phù hợp cho sản phẩm "%s". Vui lòng kiểm tra phiếu sinh từ Bước 1.', product.display_name)}
        else:
            # Find an unpacked move line that is not in any package
            if scan_package:
                move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and ml.package_id == scan_package)
            else:
                move_line = move.move_line_ids.filtered(lambda ml: not ml.result_package_id and not ml.package_id)

        if is_pick_picking:
            override_location_used = False
            if destination_location_id:
                move_line = move_line.filtered(lambda ml: ml.location_id.id == destination_location_id)
                if preferred_override_line:
                    destination_location = request.env['stock.location'].sudo().browse(destination_location_id)
                    try:
                        with request.env.cr.savepoint():
                            move_line = _redistribute_pick_reservation_to_location(
                                preferred_override_line,
                                destination_location,
                            )
                            override_location_used = True
                    except UserError as error:
                        return {'error': str(error)}
                if not move_line:
                    override_candidates = product_moves.mapped('move_line_ids').filtered(
                        lambda ml: (
                            ml.product_id == product
                            and ml.location_id.id != destination_location_id
                            and _can_override_pick_line(ml)
                        )
                    ).sorted('id')
                    override_move_line = request.env['stock.move.line'].browse()
                    if len(override_candidates) == 1:
                        override_move_line = override_candidates[0]
                    elif len(override_candidates) > 1:
                        return {'error': _('Sản phẩm "%s" có nhiều dòng ở vị trí khác còn có thể lấy. Vui lòng chọn đúng dòng cần đổi kệ rồi quét lại sản phẩm.', product.display_name)}
                    if override_move_line:
                        destination_location = request.env['stock.location'].sudo().browse(destination_location_id)
                        try:
                            with request.env.cr.savepoint():
                                move_line = _redistribute_pick_reservation_to_location(
                                    override_move_line,
                                    destination_location,
                                )
                                override_location_used = True
                        except UserError as error:
                            return {'error': str(error)}
                if not move_line:
                    return {'error': _('Sản phẩm "%s" không có dòng lấy hàng tại vị trí đang quét.', product.display_name)}
            
            # Lọc các dòng chưa quét đủ số lượng assign (số lượng tại vị trí)
            available_move_line = preferred_move_line if preferred_move_line else _pick_available_lines(move)
            if destination_location_id and move_line:
                available_move_line = move_line.filtered(lambda ml: ml.qty_scanned < ml.quantity)
            if not available_move_line:
                # Nếu tất cả dòng đã quét đủ quantity
                loc_msg = _(' tại vị trí này') if destination_location_id else ''
                return {'error': _('Sản phẩm "%s"%s đã được quét đủ số lượng phân bổ (%g).', product.display_name, loc_msg, sum(move_line.mapped('qty_scanned')))}
            move_line = available_move_line
        elif uses_qty_scanned and destination_location_id:
            if is_incoming_receipt:
                # === PHIẾU NHẬP IN: Logic 3 tầng ưu tiên ===
                # 1. Ưu tiên dòng đã có đúng vị trí đích (quét tiếp cùng vị trí → tăng qty)
                matching_dest = move_line.filtered(lambda ml: ml.location_dest_id.id == destination_location_id)
                if matching_dest:
                    move_line = matching_dest
                else:
                    # 2. Tìm dòng chưa quét (qty_scanned==0, dòng mặc định WH/Stock) → sẽ ghi đè location
                    untouched = move_line.filtered(lambda ml: ml.qty_scanned == 0)
                    if untouched:
                        move_line = untouched[:1]  # Chỉ lấy 1 dòng để override
                    else:
                        # 3. Tất cả dòng đã quét ở vị trí khác → để trống → tạo dòng mới
                        move_line = request.env['stock.move.line'].browse()
            else:
                move_line = move_line.filtered(lambda ml: ml.location_dest_id.id == destination_location_id)
        if is_pick_picking:
            updated_move_line = move_line[0]
            updated_move_line.qty_scanned += 1
            res = {
                'success': True,
                'type': 'product',
                'product_id': product.id,
                'product_name': product.display_name,
                'move_line_id': updated_move_line.id or False,
            }
            if override_location_used:
                res['override_location'] = True
                res['location_name'] = updated_move_line.location_id.display_name
            return res

        ml_dest_id = destination_location_id if (destination_location_id and is_putaway) else (move_line[0].location_dest_id.id if move_line else picking.location_dest_id.id)

        if not is_putaway:
            # Resolve actual child location where stock exists
            actual_src_id = ml_src_id
            if scan_quant:
                actual_src_id = scan_quant.location_id.id
            else:
                actual_src_id = ml_src_id
            ml_src_id = actual_src_id

        updated_move_line = request.env['stock.move.line'].browse()
        if move_line:
            last_ml = move_line[-1]
            location_differs = (
                (is_putaway and destination_location_id and last_ml.location_dest_id.id != destination_location_id)
                or (not is_putaway and destination_location_id and last_ml.location_id.id != ml_src_id)
            )
            if location_differs and is_incoming_receipt:
                # === PHIẾU NHẬP IN ===
                existing_qty = last_ml.qty_scanned if uses_qty_scanned else last_ml.quantity
                if existing_qty == 0:
                    # Dòng chưa quét → override location_dest_id
                    last_ml.location_dest_id = destination_location_id
                    if uses_qty_scanned:
                        last_ml.qty_scanned += 1
                    else:
                        last_ml.quantity += 1
                    updated_move_line = last_ml
                else:
                    # Dòng đã quét ở vị trí khác → tạo dòng mới
                    new_ml_vals = {
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_id': product.uom_id.id,
                        'location_id': ml_src_id,
                        'location_dest_id': ml_dest_id,
                    }
                    if scan_package:
                        new_ml_vals['package_id'] = scan_package.id
                    if uses_qty_scanned:
                        new_ml_vals['qty_scanned'] = 1
                    else:
                        new_ml_vals['quantity'] = 1
                    updated_move_line = request.env['stock.move.line'].create(new_ml_vals)
            elif location_differs:
                # Các loại phiếu khác: tạo dòng mới khi vị trí khác nhau
                new_ml_vals = {
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': ml_src_id,
                    'location_dest_id': ml_dest_id,
                }
                if scan_package:
                    new_ml_vals['package_id'] = scan_package.id
                if uses_qty_scanned:
                    new_ml_vals['qty_scanned'] = 1
                else:
                    new_ml_vals['quantity'] = 1
                updated_move_line = request.env['stock.move.line'].create(new_ml_vals)
            else:
                if uses_qty_scanned:
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
            if scan_package:
                new_ml_vals['package_id'] = scan_package.id
            if uses_qty_scanned:
                new_ml_vals['qty_scanned'] = 1
            else:
                new_ml_vals['quantity'] = 1
            updated_move_line = request.env['stock.move.line'].create(new_ml_vals)

        # === DYNAMIC DEMAND RECALCULATION CỦA PHIẾU NHẬP IN ===
        if is_incoming_receipt and updated_move_line:
            existing_mls = move.move_line_ids.filtered(
                lambda ml: ml.state not in ['done', 'cancel'] and not ml.result_package_id
            )
            total_demand = move.product_uom_qty
            total_locked = 0
            for eml in existing_mls:
                if eml.id != updated_move_line.id:
                    scanned = eml.qty_scanned if uses_qty_scanned else eml.quantity
                    if scanned > 0 and eml.quantity != scanned:
                        eml.quantity = scanned
                    total_locked += scanned
            
            remaining_demand = max(0, total_demand - total_locked)
            if updated_move_line.quantity != remaining_demand:
                updated_move_line.quantity = remaining_demand



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
                if _is_pick_picking(move.picking_id) and not _is_return_picking(move.picking_id):
                    return {'error': _('Sản phẩm "%s" chưa có dòng phân bổ để lấy hàng. Vui lòng chờ hệ thống assign trước khi sửa số lượng!', move.product_id.display_name)}
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
        assignment_error = _pick_assignment_error(move.picking_id)
        if assignment_error:
            return assignment_error

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
        uses_qty_scanned = _uses_qty_scanned_progress(move.picking_id)
        is_package_transfer_line = bool(
            _is_new_internal_transfer(move.picking_id)
            and move_line.package_transfer_qty_set
            and (move_line.package_id or move_line.result_package_id)
        )
        if is_package_transfer_line:
            if new_qty is not None:
                selected_qty = float(new_qty)
            elif qty_change is not None:
                selected_qty = move_line.package_transfer_qty + float(qty_change)
            else:
                return {'error': _('Thiếu tham số số lượng')}
            selected_qty = max(0.0, min(selected_qty, move_line.quantity))
            move_line.package_transfer_qty = selected_qty
            return {
                'success': True,
                'new_qty': selected_qty,
                'package_physical_qty': move_line.quantity,
            }

        step2_entry = False
        if move.picking_id.source_transfer_id:
            step2_entries, missing_step2_lines = _step2_canonical_line_entries(move.picking_id)
            if missing_step2_lines:
                return {'error': _step2_line_error(missing_step2_lines)}
            step2_entry = next(
                (entry for entry in step2_entries if entry['target_line'].id == move_line.id),
                False,
            )
            if not step2_entry:
                return {'error': _('Không được cập nhật dòng phát sinh không thuộc dữ liệu chuẩn của phiếu Bước 2.')}

        if new_qty is not None:
            new_val = float(new_qty)
        elif qty_change is not None:
            current_val = move_line.qty_scanned if uses_qty_scanned else move_line.quantity
            new_val = current_val + float(qty_change)
        else:
            return {'error': _('Thiếu tham số số lượng')}

        if new_val < 0:
            new_val = 0

        # Check limit to prevent over-scanning/updating
        warning_msg = False
        if move.picking_id.source_transfer_id:
            # Step 2 specific limit check (strict per line)
            line_demand = step2_entry['demand']
                
            if line_demand > 0.0 and new_val > line_demand:
                capped_val = line_demand
                
                current_val_compare = move_line.qty_scanned if uses_qty_scanned else move_line.quantity
                if capped_val == current_val_compare:
                    return {'error': _('Số lượng vượt quá yêu cầu cho phép của dòng này (%g/%g).', new_val, line_demand)}
                
                new_val = capped_val
                warning_msg = _('Số lượng đã tự lùi về mức tối đa theo yêu cầu (%g).', capped_val)
        
        if is_pick:
            if move_line.quantity <= 0 and new_val > 0:
                return {'error': _('Dòng sản phẩm "%s" chưa có số lượng phân bổ để lấy hàng. Không thể cập nhật số lượng quét!', move.product_id.display_name)}

            # PICK: so sánh tổng qty_scanned thay vì quantity
            other_lines_scanned = sum(ml.qty_scanned for ml in move.move_line_ids if ml.id != move_line.id)
            total_assigned = sum(ml.quantity for ml in move.move_line_ids)

            if total_assigned <= 0 and new_val > 0:
                return {'error': _('Sản phẩm "%s" chưa có số lượng phân bổ để lấy hàng. Vui lòng chờ hệ thống assign trước khi sửa số lượng!', move.product_id.display_name)}

            # Số lượng tối đa của tổng các move line
            max_allowed_total = min(move.product_uom_qty, total_assigned)
            
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
            other_lines_qty = sum((ml.qty_scanned if uses_qty_scanned else ml.quantity) for ml in move.move_line_ids if ml.id != move_line.id)
            if move.product_uom_qty > 0.0 and (new_val + other_lines_qty) > move.product_uom_qty:
                capped_val = max(0.0, move.product_uom_qty - other_lines_qty)
                current_val_compare = move_line.qty_scanned if uses_qty_scanned else move_line.quantity
                if capped_val == current_val_compare:
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
            child_loc_ids = [ml_src_id]
            
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', ml_src_id),
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

        # Write scan progress to qty_scanned for PICK/IN; quantity is finalized on validate.
        if uses_qty_scanned:
            move_line.qty_scanned = new_val
        else:
            move_line.quantity = new_val
        
        new_qty_result = move_line.qty_scanned if uses_qty_scanned else move_line.quantity
        res = {'success': True, 'new_qty': new_qty_result}
        if warning_msg:
            res['warning'] = warning_msg
            
        return res

    @http.route('/hlv_mobile_barcode/clear_quantities', type='json', auth='user')
    def clear_quantities(self, picking_id):
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists() or picking.state not in ['draft', 'waiting', 'confirmed', 'assigned']:
            return {'error': _('Không thể xoá số lượng của phiếu này')}
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
            
        try:
            uses_qty_scanned = _uses_qty_scanned_progress(picking)
            
            changed = False
            
            # 1. Handle stock move lines - dùng sudo() để đảm bảo quyền ghi
            move_lines = picking.move_line_ids.sudo()
            
            if uses_qty_scanned:
                # PICK/IN: reset mobile progress; Odoo quantity is finalized on validate.
                lines_to_reset = move_lines.filtered(lambda l: l.qty_scanned != 0.0)
                if lines_to_reset:
                    lines_to_reset.write({'qty_scanned': 0.0})
                    changed = True
            else:
                package_selection_lines = (
                    move_lines.filtered('package_transfer_qty_set')
                    if _is_new_internal_transfer(picking)
                    else request.env['stock.move.line']
                )
                package_selection_moves = package_selection_lines.mapped('move_id')
                if package_selection_lines:
                    package_selection_lines.unlink()
                    changed = True
                removable_package_moves = package_selection_moves.filtered(
                    lambda move: not move.move_line_ids and not move.move_orig_ids
                )
                if removable_package_moves:
                    removable_package_moves._action_cancel()
                    removable_package_moves.unlink()
                    changed = True
                move_lines = picking.move_line_ids.sudo()

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
            if not uses_qty_scanned:
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return {'has_conflicts': False, 'conflicts': [], 'has_saved_data': False, **assignment_error}

        conflicts = []
        has_saved_data = False

        for ml in picking.move_line_ids:
            if ml.qty_scanned <= 0:
                continue
            has_saved_data = True

            # Tính available qty tại vị trí lấy hàng của move line này
            child_loc_ids = [ml.location_id.id]
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', ml.product_id.id),
                ('location_id', '=', ml.location_id.id),
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

        for ml in picking.move_line_ids:
            if ml.qty_scanned <= 0:
                continue
            child_loc_ids = [ml.location_id.id]
            quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', ml.product_id.id),
                ('location_id', '=', ml.location_id.id),
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
            
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

        if picking.source_transfer_id:
            return {'error': _('Không được phép xóa dòng sản phẩm trong phiếu Bước 2 được tự động sinh ra.')}

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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
            
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
        assignment_error = _pick_assignment_error(ml.picking_id)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(ml.picking_id):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}
            
        # Clear packages
        ml.write(_loose_package_vals())
        return {'success': True}

    @http.route('/hlv_mobile_barcode/unpack_package', type='json', auth='user')
    def unpack_package(self, picking_id, package_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists() or picking.state in ['done', 'cancel']:
            return {'error': _('Phiếu không tồn tại hoặc đã hoàn thành/hủy.')}
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(picking):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}
            
        move_lines = picking.move_line_ids.filtered(lambda ml: _line_in_package(ml, package_id))
        
        if not move_lines:
            return {'error': _('Không tìm thấy sản phẩm nào trong kiện này.')}
            
        package = request.env['stock.quant.package'].browse(package_id)
        package_quants = _package_positive_quants(package)
        
        try:
            with request.env.cr.savepoint():
                move_lines.write(_loose_package_vals())
                if package_quants:
                    _move_package_quants_to_loose(package)
        except UserError as e:
            return {'error': str(e)}
            
        return {'success': True}

    @http.route('/hlv_mobile_barcode/validate_picking', type='json', auth='user')
    def validate_picking(self, picking_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

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
        savepoint = None
        try:
            is_pick_picking = _is_pick_picking(picking) and not _is_return_picking(picking)
            uses_qty_scanned = _uses_qty_scanned_progress(picking)
            savepoint = request.env.cr.savepoint()
            savepoint.__enter__()

            # Finalize mobile scan progress before Odoo validation.
            demand_by_line_id = {}
            if picking.source_transfer_id:
                step2_entries, missing_step2_lines = _step2_canonical_line_entries(picking)
                if missing_step2_lines:
                    raise UserError(_step2_line_error(missing_step2_lines))

                canonical_line_ids = {entry['target_line'].id for entry in step2_entries}
                demand_by_move_id = {}
                for entry in step2_entries:
                    target_line = entry['target_line']
                    demand_by_line_id[target_line.id] = entry['demand']
                    demand_by_move_id[target_line.move_id.id] = (
                        demand_by_move_id.get(target_line.move_id.id, 0.0) + entry['demand']
                    )
                    scanned_qty = target_line.qty_scanned
                    target_line.write({
                        'quantity': scanned_qty,
                        'picked': float_compare(
                            scanned_qty,
                            0.0,
                            precision_rounding=target_line.product_uom_id.rounding,
                        ) > 0,
                    })

                duplicate_lines = picking.sudo().move_line_ids.filtered(
                    lambda ml: ml.id not in canonical_line_ids and ml.state not in ['done', 'cancel']
                )
                if duplicate_lines:
                    duplicate_lines.write({
                        'quantity': 0.0,
                        'qty_scanned': 0.0,
                        'picked': False,
                    })

                for move in picking.sudo().move_ids:
                    canonical_demand = demand_by_move_id.get(move.id, 0.0)
                    if move.product_uom_qty != canonical_demand:
                        move.product_uom_qty = canonical_demand
            elif is_pick_picking:
                for ml in picking.sudo().move_line_ids:
                    if ml.quantity > 0:
                        scanned_qty = ml.qty_scanned
                        ml.write({
                            'quantity': scanned_qty,
                            'picked': float_compare(
                                scanned_qty,
                                0.0,
                                precision_rounding=ml.product_uom_id.rounding,
                            ) > 0,
                        })
                    elif ml.qty_scanned:
                        ml.write({'qty_scanned': 0.0, 'picked': False})
                    elif ml.picked:
                        ml.picked = False
            elif uses_qty_scanned:
                for ml in picking.sudo().move_line_ids:
                    scanned_qty = ml.qty_scanned
                    is_picked = float_compare(
                        scanned_qty,
                        0.0,
                        precision_rounding=ml.product_uom_id.rounding,
                    ) > 0
                    if ml.package_id or ml.result_package_id:
                        values = {'picked': is_picked}
                        if is_picked:
                            values['quantity'] = scanned_qty
                        ml.write(values)
                    else:
                        ml.write({
                            'quantity': scanned_qty,
                            'picked': is_picked,
                        })

            if _is_new_internal_transfer(picking):
                _prepare_partial_packages_for_validation(picking)

            # STRICT PRE-VALIDATION STOCK CHECK
            # To completely prevent negative stock due to concurrent transactions
            is_putaway = _is_putaway_picking(picking)

            
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
                        raise UserError(_(
                            'LỖI TỒN KHO: Không thể xác nhận!\n'
                            'Số lượng ghi nhận của sản phẩm "%s" tại vị trí "%s" không chính xác '
                            '(đang xác nhận %g nhưng kho chỉ còn tối đa %g khả dụng). '
                            'Vui lòng kiểm tra lại tồn kho thực tế hoặc nhấn "Làm lại" để đồng bộ dữ liệu!',
                            product.display_name,
                            location.display_name,
                            qty_to_consume,
                            available_qty
                        ))

            note = picking.note or ''
            dest_loc_id = None
            if 'DEST_LOC_OVERRIDE:' in note:
                import re
                match = re.search(r'DEST_LOC_OVERRIDE:(\d+)', note)
                if match:
                    dest_loc_id = int(match.group(1))

            # Mobile multi-location transfers create dynamic Step 1 moves with
            # zero demand and record the scanned quantity on move lines. Set
            # the final demand before validation so the generated Step 2
            # picking has the same structure as a transfer created in Odoo.
            is_dynamic_int_step1 = (
                picking.picking_type_id.code == 'internal'
                and not picking.source_transfer_id
                and not _is_return_picking(picking)
                and picking.location_dest_id.usage == 'transit'
            )
            if is_dynamic_int_step1:
                for move in picking.sudo().move_ids.filtered(
                    lambda m: (
                        m.state not in ['done', 'cancel']
                        and m.product_uom_qty == 0
                        and not m.move_orig_ids
                    )
                ):
                    actual_demand = sum(
                        ml.product_uom_id._compute_quantity(ml.quantity, move.product_uom)
                        for ml in move.move_line_ids
                        if ml.state != 'cancel' and ml.quantity > 0
                    )
                    if actual_demand > 0:
                        move.product_uom_qty = actual_demand

            # --- FIX: Prevent "split package" error & auto-repacking ---
            # Odoo does not allow partially moving a package while keeping the same result_package_id.
            # Also, if package_level_ids exists, Odoo will FORCE the package to move, causing errors.
            package_totals = {}
            for ml in picking.sudo().move_line_ids:
                if (
                    ml.result_package_id
                    and not (
                        _is_new_internal_transfer(picking)
                        and ml.package_transfer_qty_set
                    )
                ):
                    pkg_id = ml.result_package_id.id
                    if pkg_id not in package_totals:
                        package_totals[pkg_id] = {'qty': 0.0, 'qty_uom': 0.0, 'mls': []}
                    package_totals[pkg_id]['qty'] += ml.quantity
                    package_totals[pkg_id]['qty_uom'] += demand_by_line_id.get(
                        ml.id,
                        ml.quantity_product_uom,
                    )
                    package_totals[pkg_id]['mls'].append(ml)
            
            deleted_packages_info = []
            for pkg_id, data in package_totals.items():
                if 0 < data['qty'] < data['qty_uom']:
                    # Package is partially scanned.
                    # 1. Remove package_level so Odoo doesn't force the package to move.
                    pkg_levels = picking.sudo().package_level_ids.filtered(lambda pl: pl.package_id.id == pkg_id)
                    if pkg_levels:
                        pkg_levels.unlink()
                        
                    # 2. Tách dòng đã quét thành dòng lẻ (result_package_id = False) 
                    # và XÓA dòng chưa quét khỏi move_line để tránh lỗi validate của Odoo.
                    for ml in data['mls']:
                        line_demand = demand_by_line_id.get(ml.id, ml.quantity_product_uom)
                        qty_remaining = max(0.0, line_demand - ml.quantity)
                        if float_compare(
                            qty_remaining,
                            0.0,
                            precision_rounding=ml.product_uom_id.rounding,
                        ) > 0:
                            deleted_packages_info.append({
                                'product_id': ml.product_id.id,
                                'location_id': ml.location_id.id,
                                'location_dest_id': ml.location_dest_id.id,
                                'package_id': ml.package_id.id or pkg_id,
                                'product_uom_id': ml.product_uom_id.id,
                                'lot_id': ml.lot_id.id or False,
                                'owner_id': ml.owner_id.id or False,
                                'qty_remaining': qty_remaining,
                            })
                        if ml.quantity > 0:
                            # Keep package_id as the source package to consume stock correctly;
                            # clearing result_package_id makes the received quantity loose.
                            ml.result_package_id = False
                        else:
                            ml.unlink()
            # ------------------------------------------

            res_dict = picking.button_validate()
            
            # Xử lý tự động tạo backorder nếu quét không đủ số lượng
            backorder_info = {}
            new_backorders = request.env['stock.picking']
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
                    # Kế thừa source_transfer_id cho backorder.
                    for bo in new_backorders:
                        if picking.source_transfer_id and not bo.source_transfer_id:
                            bo.sudo().source_transfer_id = picking.source_transfer_id.id

                    # Reserve trực tiếp đúng kiện nguồn, không chạy action_assign() chung.
                    _reserve_exact_packages(new_backorders[0], deleted_packages_info)

                    backorder_info = {
                        'backorder_created': True,
                        'backorder_id': new_backorders[0].id,
                        'backorder_name': new_backorders[0].name
                    }
            if deleted_packages_info and not new_backorders:
                raise UserError(_(
                    'Odoo không tạo phiếu tách để nhận lại kiện còn dư. '
                    'Giao dịch đã được hoàn tác để tránh mất reservation của kiện.'
                ))
            if deleted_packages_info:
                deleted_package_ids = list({
                    info['package_id'] for info in deleted_packages_info if info['package_id']
                })
                old_package_lines = picking.move_line_ids.filtered(
                    lambda ml: (
                        ml.state != 'cancel'
                        and ml.quantity > 0
                        and ml.result_package_id.id in deleted_package_ids
                    )
                )
                if old_package_lines:
                    raise UserError(_(
                        'Phiếu cũ vẫn còn giữ dòng của kiện đã chuyển sang phiếu tách. '
                        'Giao dịch đã được hoàn tác.'
                    ))
            
            # Override destination location for Step 2 if requested
            step2_picking = request.env['stock.picking'].sudo().search([('source_transfer_id', '=', picking.id)], limit=1)
            if dest_loc_id and step2_picking:
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
            if step2_picking:
                result['linked_picking_id'] = step2_picking.id
                result['linked_picking_name'] = step2_picking.name
            result.update(backorder_info)
            savepoint.__exit__(None, None, None)
            savepoint = None
            return result
        except Exception as e:
            if savepoint:
                savepoint.__exit__(type(e), e, e.__traceback__)
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
            if not package.exists():
                return {'error': _('Không tìm thấy kiện hàng')}
            title = package.name
            warehouse_code = 'HLV'
            location = package.location_id
            # Use sudo() to bypass company constraints on packages
            quants = quants.sudo().search([('package_id', '=', package.id), ('quantity', '>', 0.0)])
            quant_locations = quants.mapped('location_id')
            if not location and len(quant_locations) == 1:
                location = quant_locations[0]
            for q in quants:
                results.append({
                    'product_id': q.product_id.id,
                    'product_name': q.product_id.display_name,
                    'quantity': q.quantity,
                    'location_name': q.location_id.display_name,
                    'quant_id': q.id,
                })
                if not location and q.location_id:
                    location = q.location_id
            if location:
                warehouse_code = location.warehouse_id.code or 'HLV'
            can_process_whole_package = bool(quants and location and len(quant_locations) == 1)
            return {
                'title': title,
                'results': results,
                'reservations': reservations,
                'warehouse_code': warehouse_code,
                'package_id': package.id,
                'location_id': location.id if location else False,
                'location_barcode': (location.barcode or location.name) if location else '',
                'location_name': location.display_name if location else '',
                'can_unpack_package': bool(quants),
                'can_move_package': can_process_whole_package,
            }
                
        return {'title': title, 'results': results, 'reservations': reservations}

    @http.route('/hlv_mobile_barcode/unpack_inventory_package', type='json', auth='user')
    def unpack_inventory_package(self, package_id):
        package = request.env['stock.quant.package'].sudo().browse(int(package_id or 0))
        if not package.exists():
            return {'error': _('Không tìm thấy kiện hàng')}
        try:
            source_location = _single_package_location(package)
        except UserError:
            source_location = package.location_id

        warehouse = source_location.warehouse_id if source_location else False
        if source_location and not warehouse:
            warehouse = request.env['stock.warehouse'].sudo().search([
                ('view_location_id', 'parent_of', source_location.id),
            ], limit=1)
        permission_error = _barcode_operation_error(warehouse, 'INT', 'can_edit')
        if permission_error:
            return permission_error

        try:
            with request.env.cr.savepoint():
                _move_package_quants_to_loose(package)
        except UserError as error:
            return {'error': str(error)}
        except Exception as error:
            _logger.error("unpack_inventory_package error: %s", str(error), exc_info=True)
            return {'error': str(error)}

        return {
            'success': True,
            'message': _('Đã gỡ kiện "%s" thành hàng lẻ.', package.name),
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

    @http.route('/hlv_mobile_barcode/get_package_details', type='json', auth='user')
    def get_package_details(self, picking_id, package_id):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error

        Package = request.env['stock.quant.package']
        package = Package.sudo().browse(package_id)

        if not package.exists():
            return {'error': _('Gói hàng không tồn tại!')}

        # Lấy TẤT CẢ move_lines của picking
        all_move_lines = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id)
        ])
        move_lines = all_move_lines.filtered(lambda ml: _line_in_package(ml, package.id))
        if not move_lines:
            return {'error': _('Kiện hàng không còn thuộc phiếu này.'), 'package_missing': True}

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
        all_packages_in_picking = request.env['stock.quant.package'].browse(list(dict.fromkeys(
            pkg.id for pkg in (_line_package(ml) for ml in all_move_lines) if pkg
        )))

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
            
            if not _line_package(ml) and qty > 0:
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(picking):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if not _line_in_package(move_line, package_id):
            return {'error': _('Sản phẩm này không còn thuộc gói này!'), 'package_stale': True}

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
                move_line.with_context(skip_qty_validation=True).write(_loose_package_vals())
            else:
                move_line.with_context(skip_qty_validation=True).write({'quantity': new_qty})
                
                # 2. Tạo hoặc cộng dồn vào dòng hàng lẻ có sẵn
                existing_loose_line = request.env['stock.move.line'].sudo().search([
                    ('picking_id', '=', picking.id),
                    ('product_id', '=', move_line.product_id.id),
                    ('result_package_id', '=', False),
                    ('package_id', '=', False),
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
                        **_loose_package_vals(),
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(picking):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if not _line_in_package(move_line, package_id):
            return {'error': _('Sản phẩm này không còn thuộc gói này!'), 'package_stale': True}

        move_line.with_context(skip_qty_validation=True).write(_loose_package_vals())
        
        return {
            'success': True,
            'message': _('Đã bỏ sản phẩm khỏi kiện (vẫn giữ trạng thái đã quét)')
        }

    @http.route('/hlv_mobile_barcode/add_item_to_package', type='json', auth='user')
    def add_item_to_package(self, picking_id, package_id, move_line_id, qty):
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'error': _('Picking not found')}
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(picking):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if qty <= 0:
            return {'error': _('Số lượng thêm phải lớn hơn 0!')}

        if not picking.move_line_ids.filtered(lambda ml: _line_in_package(ml, package_id)):
            return {'error': _('Kiện hàng không còn thuộc phiếu này.'), 'package_stale': True}

        product = move_line.product_id

        # Lấy thông tin tổng quan
        all_product_lines = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('product_id', '=', product.id),
        ])

        # Tính unassigned scanned
        unassigned_lines = all_product_lines.filtered(lambda ml: not _line_package(ml) and ml.quantity > 0)
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
                dest_line = all_product_lines.filtered(lambda l: _line_in_package(l, package_id) and l.id != ml.id)
                
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
                        ml.with_context(skip_qty_validation=True).write(_package_write_vals(picking, package_id))
                    else:
                        ml.with_context(skip_qty_validation=True).write({'quantity': ml.quantity - take})
                        ml.with_context(skip_qty_validation=True).copy({
                            'quantity': take,
                            **_package_write_vals(picking, package_id),
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
        assignment_error = _pick_assignment_error(picking)
        if assignment_error:
            return assignment_error
        if not _can_edit_packages(picking):
            return {'error': _('Phiếu này không cho phép chỉnh sửa kiện hàng.')}

        if from_package_id == to_package_id:
            return {'error': _('Gói nguồn và gói đích phải khác nhau!')}

        move_line = request.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != picking.id:
            return {'error': _('Dòng điều chuyển không tồn tại!')}

        if not _line_in_package(move_line, from_package_id):
            return {'error': _('Sản phẩm này không còn thuộc gói nguồn!'), 'package_stale': True}

        if qty <= 0 or qty > move_line.quantity:
            return {'error': _('Số lượng chuyển không hợp lệ!')}

        to_package = request.env['stock.quant.package'].sudo().browse(to_package_id)
        if not to_package.exists():
            return {'error': _('Gói đích không tồn tại!')}

        # Kiểm tra xem gói đích có trong phiếu này không
        picking_lines = picking.sudo().move_line_ids
        to_ml_exists = picking_lines.filtered(lambda ml: _line_in_package(ml, to_package_id))[:1]
        if not to_ml_exists:
            return {'error': _('Gói đích không tồn tại hoặc không hợp lệ trong phiếu này!')}

        # Cập nhật package nguồn
        ctx = dict(request.env.context, skip_qty_validation=True)
        new_qty = move_line.quantity - qty
        
        # Tìm xem sản phẩm có trong package đích không
        existing_in_target = picking_lines.filtered(
            lambda ml: (
                ml.product_id == move_line.product_id
                and ml.move_id == move_line.move_id
                and _line_in_package(ml, to_package_id)
            )
        )[:1]

        # Giảm số lượng ở nguồn trước
        if new_qty == 0:
            if existing_in_target:
                existing_in_target.with_context(ctx).write({
                    'quantity': existing_in_target.quantity + qty
                })
                move_line.with_context(ctx).unlink()
            else:
                move_line.with_context(ctx).write(_package_write_vals(picking, to_package_id))
        else:
            move_line.with_context(ctx).write({'quantity': new_qty})
            if existing_in_target:
                existing_in_target.with_context(ctx).write({
                    'quantity': existing_in_target.quantity + qty
                })
            else:
                move_line.with_context(ctx).copy({
                    'quantity': qty,
                    **_package_write_vals(picking, to_package_id),
                })

        return {
            'success': True,
            'message': _('Đã chuyển %s sản phẩm sang gói đích thành công.', qty)
        }
