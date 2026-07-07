import logging
from odoo import _
from odoo.http import request
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


def _step2_canonical_line_entries(picking):
    """Use current Step 2 lines while validating totals against the source transfer."""
    # Lazy import to avoid circular dependency
    from .package_helpers import _line_package
    
    if not picking or not picking.exists() or not picking.source_transfer_id:
        return [], []

    source_lines = picking.source_transfer_id.move_line_ids.filtered(
        lambda ml: ml.quantity > 0 and ml.state not in ['cancel']
    ).sorted('id')
    
    target_lines = picking.move_line_ids.filtered(
        lambda ml: (ml.quantity > 0 or ml.quantity_product_uom > 0) and ml.state != 'cancel'
    ).sorted('id')
    
    entries = []
    missing_source_lines = []
    if not target_lines and source_lines:
        missing_source_lines.extend(source_lines)
        return entries, missing_source_lines

    for product in target_lines.mapped('product_id'):
        product_source_lines = source_lines.filtered(lambda ml: ml.product_id == product)
        product_target_lines = target_lines.filtered(lambda ml: ml.product_id == product)
        
        source_qty = sum(product_source_lines.mapped('quantity'))
        target_qty = sum(product_target_lines.mapped(lambda ml: ml.quantity_product_uom or ml.quantity))
        
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