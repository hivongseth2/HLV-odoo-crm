"""Suy giai đoạn xuất kho của một đơn từ trạng thái các phiếu — hàm thuần, vào gì ra nấy.

Kho xuất theo 3 bước: lấy hàng (pick) → đóng gói (pack) → xuất (out). Không đụng
``self.env``; nhận vào list cặp ``(bước, trạng thái phiếu)`` để test được bằng python trần.
"""

STEP_ORDER = ('pick', 'pack', 'out')

_STAGE_WHEN_READY = {'pick': 'picking', 'pack': 'packing', 'out': 'ready_to_ship'}


def stage_from_steps(step_states):
    """Giai đoạn của đơn, suy từ các phiếu kho của nó.

    step_states: list tuple ``(step, state)`` — ``step`` ∈ pick/pack/out/other, ``state``
        là trạng thái ``stock.picking`` (draft/waiting/confirmed/assigned/done/cancel).

    Trả về một trong: ``no_picking``, ``cancelled``, ``waiting_stock``, ``picking``,
    ``packing``, ``ready_to_ship``, ``shipped``.

    Luật: bỏ phiếu huỷ, rồi tìm BƯỚC ĐẦU TIÊN (pick → pack → out) còn phiếu chưa ``done``.
    Bước đó có phiếu ``assigned`` thì đơn đang ở bước đó; không có thì đơn đang chờ hàng.
    Phiếu bổ sung (backorder) tính như mọi phiếu khác, nên đơn giao một phần ra "chưa
    xong" chứ không ra "đã xuất hết". Phiếu loại ``other`` (không thuộc chuỗi) bị bỏ qua.
    """
    if not step_states:
        return 'no_picking'
    live = [(step, state) for step, state in step_states if state != 'cancel']
    if not live:
        return 'cancelled'
    for step in STEP_ORDER:
        pending = [state for live_step, state in live if live_step == step and state != 'done']
        if not pending:
            continue
        return _STAGE_WHEN_READY[step] if 'assigned' in pending else 'waiting_stock'
    return 'shipped'
