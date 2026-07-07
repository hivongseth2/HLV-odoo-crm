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


class HLVMobileBarcodePackage(http.Controller):


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
