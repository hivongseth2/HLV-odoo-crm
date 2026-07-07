import logging
from odoo import _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


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


def _lock_packages(package_ids):
    package_ids = sorted(set(package_ids))
    if not package_ids:
        return
    request.env.cr.execute(
        'SELECT id FROM stock_quant_package WHERE id IN %s ORDER BY id FOR UPDATE',
        [tuple(package_ids)],
    )
    _lock_package_reservations(package_ids)


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
    from .picking_helpers import _is_new_internal_transfer

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