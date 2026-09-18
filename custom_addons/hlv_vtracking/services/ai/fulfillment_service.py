"""Đơn bán đang ở đâu trong chuỗi xuất kho 3 bước: lấy hàng (pick) → đóng gói (pack) → xuất
(out).

Kho xuất theo ba bước, nên "đơn đã sẵn sàng giao chưa" không đọc được từ trạng thái đơn
bán — phải soi từng phiếu. AI lập kế hoạch cần đúng một câu trả lời gọn cho mỗi đơn: đang
kẹt ở bước nào, và đã có phiếu OUT sẵn sàng để xếp lên xe chưa.
"""

from ...tools.vtracking_stage import STEP_ORDER, stage_from_steps
from .serialize import iso_datetime

STEP_LABELS = {'pick': 'Lấy hàng', 'pack': 'Đóng gói', 'out': 'Xuất kho', 'other': 'Khác'}

# Giai đoạn của đơn, xếp từ xa tới gần lúc giao. `can_load` = đã xếp lên xe được ngay chưa.
STAGES = {
    'no_picking':    ('Chưa có phiếu kho nào', False),
    'waiting_stock': ('Chờ hàng — kho chưa đủ hàng để lấy', False),
    'picking':       ('Đang lấy hàng', False),
    'packing':       ('Đang đóng gói', False),
    'ready_to_ship': ('Đã đóng gói xong, phiếu xuất SẴN SÀNG', True),
    'shipped':       ('Đã xuất kho hết', False),
    'cancelled':     ('Mọi phiếu đã huỷ', False),
}


def picking_step(picking):
    """Phiếu này là bước nào của chuỗi 3 bước: ``pick`` / ``pack`` / ``out`` / ``other``.

    So với loại phiếu khai trên KHO chứ không đoán theo tên ("KBC/PICK/..."): tiền tố tên
    là cấu hình sửa được, còn ba loại phiếu của kho là định nghĩa của chính chuỗi 3 bước.
    """
    warehouse = picking.picking_type_id.warehouse_id
    picking_type = picking.picking_type_id
    if picking_type == warehouse.out_type_id or picking_type.code == 'outgoing':
        return 'out'
    if picking_type == warehouse.pick_type_id:
        return 'pick'
    if picking_type == warehouse.pack_type_id:
        return 'pack'
    return 'other'


def step_block(picking):
    """Một phiếu kho ở dạng dict."""
    step = picking_step(picking)
    return {
        'picking_id': picking.id,
        'name': picking.name,
        'step': step,
        'step_label': STEP_LABELS[step],
        'state': picking.state,
        'scheduled_date': iso_datetime(picking.scheduled_date),
        'date_done': iso_datetime(picking.date_done),
        'is_backorder': bool(picking.backorder_id),
        'plan_id': picking.plan_id.id or None,
    }


def order_stage(pickings):
    """Giai đoạn của một đơn (khoá trong ``STAGES``). Luật nằm ở ``tools/vtracking_stage``."""
    return stage_from_steps([(picking_step(p), p.state) for p in pickings])


def delivery_chain(order):
    """Toàn cảnh xuất kho của một đơn bán.

    Trả về dict::

        {'stage', 'stage_label', 'can_load',
         'ready_out_picking_ids': [...],   # phiếu OUT đang sẵn sàng và CHƯA xếp xe
         'steps': [...]}                   # mọi phiếu kho, theo thứ tự pick → pack → out
    """
    pickings = order.picking_ids
    stage = order_stage(pickings)
    label, can_load = STAGES[stage]
    ready_out = pickings.filtered(
        lambda p: picking_step(p) == 'out' and p.state == 'assigned' and not p.plan_id
    )
    ordered = pickings.sorted(
        lambda p: (STEP_ORDER.index(picking_step(p)) if picking_step(p) in STEP_ORDER else 9, p.id)
    )
    return {
        'stage': stage,
        'stage_label': label,
        'can_load': can_load,
        'ready_out_picking_ids': ready_out.ids,
        'steps': [step_block(picking) for picking in ordered],
    }


def load_estimate(order):
    """Ước lượng khối lượng hàng của một đơn, để AI đoán xe có chở nổi không.

    CẢNH BÁO dữ liệu: phần lớn sản phẩm của công ty chưa khai cân nặng/thể tích, nên
    ``total_weight_kg`` thường THẤP hơn thật rất nhiều. ``weight_coverage`` cho biết bao
    nhiêu phần số lượng có cân nặng — dưới 1.0 thì coi cân nặng là cận dưới, và dựa vào số
    dòng hàng, số lượng, số kiện đã đóng để đoán.
    """
    lines = order.order_line.filtered(lambda l: l.product_id and not l.display_type)
    total_qty = sum(lines.mapped('product_uom_qty'))
    weighed_qty = sum(l.product_uom_qty for l in lines if l.product_id.weight)
    packages = order.picking_ids.filtered(lambda p: p.state != 'cancel').mapped(
        'move_line_ids.result_package_id'
    )
    return {
        'line_count': len(lines),
        'total_qty': total_qty,
        'total_weight_kg': round(sum(l.product_id.weight * l.product_uom_qty for l in lines), 2),
        'total_volume_m3': round(sum(l.product_id.volume * l.product_uom_qty for l in lines), 3),
        'weight_coverage': round(weighed_qty / total_qty, 2) if total_qty else 0.0,
        'package_count': len(packages),
    }
