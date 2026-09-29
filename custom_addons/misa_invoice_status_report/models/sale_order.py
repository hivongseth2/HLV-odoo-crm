import logging

from odoo import fields, models

from .misa_invoice_amount_utils import allocate_fifo

_logger = logging.getLogger(__name__)


class SaleOrderMisaInvoiceStatus(models.Model):
    _inherit = 'sale.order'

    # Chiều ngược của stock.picking.misa_invoice_sale_order_ids — dùng cùng bảng quan hệ
    # để tra "đơn hàng này gắn với những phiếu xuất kho nào" cho tab Đơn hàng trên dashboard.
    misa_invoice_picking_ids = fields.Many2many(
        'stock.picking', 'misa_invoice_picking_sale_order_rel', 'order_id', 'picking_id',
        string='Phiếu xuất kho liên quan',
    )

    # Đánh dấu "đã nhắc sale xuất hóa đơn" — dùng để HIGHLIGHT đơn này trên tab Đơn hàng (cả
    # dashboard nội bộ lẫn /misa_sale_status) cho tới khi đơn được xuất HĐ đủ (xem
    # _misa_invoice_order_row: chỉ highlight khi state != 'invoiced', KHÔNG tự xóa field này để
    # còn giữ lịch sử "đã từng nhắc lúc nào, ai nhắc" — xem action_send_misa_invoice_reminder.
    misa_invoice_reminder_at = fields.Datetime(string='Lần nhắc xuất HĐ gần nhất', copy=False)
    misa_invoice_reminder_by_id = fields.Many2one('res.users', string='Người nhắc xuất HĐ', copy=False)

    # Đối soát THEO ĐƠN HÀNG: tiền đã xuất HĐ = mọi dòng hàng ghi đúng mã đơn này trong MỌI đề
    # nghị ĐÃ phát hành HĐ trên MISA, ai lập, tên đề nghị là gì cũng được. Cách gắn 1 đề nghị
    # cho mỗi phiếu (misa_invoice_request_refid) bỏ sót đơn xuất HĐ qua nhiều đề nghị — case
    # thật KBC/OUT/09332 (đề nghị chính + KBC/OUT/09359), KBC/OUT/10278 (10278 + 10278_1).
    # HĐ hải quan KHÔNG lưu ở đây — lấy theo lượt khớp vào TỪNG PHIẾU lúc chia (không theo mã
    # đơn trên dòng hải quan: phiếu có thể được khớp tay với dòng ghi nhầm mã đơn khác, case
    # KBC/OUT/11284), và đọc lại tiền VAT của dòng hải quan không phải hỏi lại MISA cho đơn.
    misa_invoice_order_checked_at = fields.Datetime(string='Lần soát đơn với MISA gần nhất', copy=False)
    # Lần THỬ gần nhất, kể cả lỗi — cron chọn đơn theo field này, để đơn MISA đang lỗi không
    # đứng mãi đầu hàng chiếm suất của các đơn khác mỗi lượt.
    misa_invoice_order_attempted_at = fields.Datetime(string='Lần thử soát đơn với MISA gần nhất', copy=False)
    misa_invoice_order_invoiced_amount = fields.Float(
        string='Đã xuất HĐ theo MISA (mọi đề nghị)', copy=False,
    )
    misa_invoice_order_pending_amount = fields.Float(
        string='Đề nghị chưa phát hành HĐ (MISA)', copy=False,
    )
    misa_invoice_order_sources = fields.Text(string='Đề nghị xuất HĐ của đơn (MISA)', copy=False)

    def _misa_invoice_refresh_order_truth(self):
        """Hỏi MISA mọi đề nghị nhắc tới từng đơn, lưu tiền đã phát hành / chưa phát hành, rồi
        chia lại về phiếu. Đơn gọi MISA lỗi thì giữ nguyên, không đánh dấu đã soát (lượt sau thử
        lại). Trả số đơn soát xong."""
        misa = self.env['misa.api.utils']
        Picking = self.env['stock.picking'].sudo()
        lines_cache = {}
        done = self.browse()
        for order in self:
            order.misa_invoice_order_attempted_at = fields.Datetime.now()
            try:
                requests = misa.get_invoice_requests_for_order(order.name)
                issued = pending = 0.0
                sources = []
                for req in requests:
                    if req['refid'] not in lines_cache:
                        lines_cache[req['refid']] = misa.get_invoice_request_lines(req['refid'])
                    own = [
                        line for line in lines_cache[req['refid']]
                        if (line.get('order_code') or '').strip() == order.name
                    ]
                    amount = Picking._misa_invoice_request_line_amount(own)
                    if not amount:
                        continue
                    if req['inv_no']:
                        issued += amount
                    else:
                        pending += amount
                    sources.append("%s — %s: %s đ" % (
                        req['refno'], "HĐ %s" % req['inv_no'] if req['inv_no'] else "chưa phát hành",
                        f"{amount:,.0f}".replace(",", "."),
                    ))
            except Exception:
                _logger.exception("❌ [MISA ORDER] Lỗi soát đơn %s với MISA", order.name)
                continue
            order.write({
                'misa_invoice_order_checked_at': fields.Datetime.now(),
                'misa_invoice_order_invoiced_amount': issued,
                'misa_invoice_order_pending_amount': pending,
                'misa_invoice_order_sources': "\n".join(sources),
            })
            done |= order
        done._misa_invoice_apply_order_allocation()
        return len(done)

    def _misa_invoice_apply_order_allocation(self):
        """Tiền HĐ của phiếu = HĐ hải quan đã khớp vào chính phiếu + phần tiền đề nghị đã phát
        hành của đơn, rót vào phần còn lại của các phiếu, phiếu xuất trước nhận trước
        (allocate_fifo). Thuần DB — gọi lại được bất cứ lúc nào dữ liệu phiếu đổi (hàng trả,
        phiếu mới xuất, dòng hải quan đọc lại VAT).

        Phiếu gộp nhiều đơn chỉ dùng số theo đơn khi MỌI đơn của nó đã soát — thiếu 1 đơn là
        thiếu 1 phần tiền, thà để phiếu đó tính theo cách cũ còn hơn báo thiếu sai."""
        pickings = self.mapped('misa_invoice_picking_ids').filtered(
            lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing'
        )
        per_order = {}
        for order in pickings.mapped('misa_invoice_sale_order_ids').filtered('misa_invoice_order_checked_at'):
            order_pickings = order.misa_invoice_picking_ids.filtered(
                lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing'
            ).sorted(lambda p: (p.date_done or p.create_date, p.id))
            # HĐ hải quan đã nằm sẵn trên phiếu qua lượt khớp — đề nghị chỉ rót vào phần CÒN LẠI.
            per_order[order.id] = allocate_fifo(
                order.misa_invoice_order_invoiced_amount,
                [(p.id, p._misa_invoice_request_capacity_for_order(order)) for p in order_pickings],
            )
        for picking in pickings:
            orders = picking.misa_invoice_sale_order_ids
            ready = bool(orders) and all(order.id in per_order for order in orders)
            picking.write({
                'misa_invoice_order_allocation_ok': ready,
                'misa_invoice_order_allocated_amount': (
                    picking._misa_invoice_customs_matched_amount()
                    + sum(per_order[order.id].get(picking.id, 0.0) for order in orders)
                ) if ready else 0.0,
            })
