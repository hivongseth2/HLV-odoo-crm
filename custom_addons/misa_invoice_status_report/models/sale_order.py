import logging
from datetime import timedelta

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

    def _misa_invoice_refresh_order_truth(self, with_related=True, lines_cache=None, requests_cache=None):
        """Hỏi MISA mọi đề nghị nhắc tới từng đơn, lưu tiền đã phát hành / chưa phát hành, rồi
        chia lại về phiếu. Đơn gọi MISA lỗi thì giữ nguyên, không đánh dấu đã soát (lượt sau thử
        lại). Trả số đơn soát xong (chỉ tính các đơn trong self).

        Tiền của đơn = dòng ghi mã đơn này, sau khi chuyển dòng ghi nhầm / bỏ trống mã đơn về
        đúng đơn có phiếu gắn vào đề nghị (_misa_invoice_line_moves) — không thì 1 dòng bị đếm cho
        cả đơn ghi trên dòng lẫn đơn thật.

        with_related: soát luôn các đơn KHÁC có mặt trong cùng đề nghị và các đơn vừa được chuyển
        dòng qua lại (1 tầng, dùng lại dòng đã đọc) — xem _misa_invoice_related_orders."""
        lines_cache = {} if lines_cache is None else lines_cache
        requests_cache = {} if requests_cache is None else requests_cache
        done = self.browse()
        moved_names = set()
        for order in self:
            order.misa_invoice_order_attempted_at = fields.Datetime.now()
            try:
                moves, lines = order._misa_invoice_line_moves(requests_cache, lines_cache)
                issued = pending = 0.0
                sources = []
                for req, amount, notes in order._misa_invoice_owned_request_amounts(moves, lines):
                    if req['inv_no']:
                        issued += amount
                    else:
                        pending += amount
                    sources.append("%s — %s: %s đ%s" % (
                        req['refno'], "HĐ %s" % req['inv_no'] if req['inv_no'] else "chưa phát hành",
                        f"{amount:,.0f}".replace(",", "."), " (%s)" % "; ".join(notes) if notes else "",
                    ))
                for key, targets in moves.items():
                    line_order = (lines[key][1].get('order_code') or '').strip()
                    if order.name in {line_order} | {target for target, _p, _q in targets}:
                        moved_names |= {line_order} | {target for target, _p, _q in targets}
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
        if with_related:
            self._misa_invoice_related_orders(lines_cache, moved_names)._misa_invoice_refresh_order_truth(
                with_related=False, lines_cache=lines_cache, requests_cache=requests_cache,
            )
        return len(done)

    def _misa_invoice_related_orders(self, lines_cache, moved_names=(), limit=50):
        """Đơn KHÁC có dòng hàng trong các đề nghị vừa đọc, chưa thử soát trong 1 ngày qua — cộng
        các đơn vừa được chuyển dòng qua lại (moved_names), soát lại bất kể lần thử gần nhất: đơn
        nhận dòng mà không soát lại thì vẫn giữ số cũ thiếu đúng khoản vừa chuyển sang.

        Vì sao cần: chỉ đơn ĐANG LỆCH mới được chọn soát theo đơn, đơn không lệch vẫn tính tiền
        theo đề nghị gắn vào phiếu. Khi sale ghi nhầm mã đơn, 1 dòng hàng bị đếm 2 lần: đơn ghi
        trên dòng (soát theo đơn) và đơn thật (theo đề nghị gắn vào phiếu) — case thật đề nghị
        KBC/OUT/09323 ghi 4.984.200 đ hàng của DH…235474 (phiếu KBC/OUT/12296) vào DH…232207.
        Soát luôn các đơn cùng đề nghị thì đơn thật cũng chuyển sang tính theo mã đơn, dòng đó
        chỉ còn nằm ở 1 đơn và cặp thừa/thiếu hiện ra thay vì bị cộng trùng."""
        codes = {
            (line.get('order_code') or '').strip()
            for lines in lines_cache.values() for line in lines
        } - {''} - set(self.mapped('name'))
        forced = set(moved_names) - {''} - set(self.mapped('name'))
        related = self.browse()
        if forced:
            related = self.sudo().search([('name', 'in', list(forced))])
        if codes - forced:
            related |= self.sudo().search([
                ('name', 'in', list(codes - forced)),
                '|', ('misa_invoice_order_attempted_at', '=', False),
                ('misa_invoice_order_attempted_at', '<', fields.Datetime.now() - timedelta(days=1)),
            ], limit=limit)
        return related

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
