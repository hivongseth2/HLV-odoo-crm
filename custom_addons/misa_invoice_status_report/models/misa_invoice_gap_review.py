import logging
from collections import defaultdict

from odoo import api, fields, models

from .misa_invoice_gap_review_utils import compare_items, duplicate_requests, opposite_pairs, tax_rate
from .misa_invoice_reassign_utils import item_key, owned_qty
from .stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

_logger = logging.getLogger(__name__)

# Trần mỗi lượt gọi — mỗi đơn soát tốn 1–3 lệnh gọi MISA, worker gọi nhiều lượt nhỏ thay vì 1
# lượt lớn để không vượt thời gian 1 request của Odoo.
REVIEW_BATCH_LIMIT = 20
REFRESH_BATCH_LIMIT = 30


class MisaInvoiceGapReview(models.AbstractModel):
    """Soát lý do lệch "tiền xuất kho − tiền HĐ" theo ĐƠN cho báo cáo đối soát hằng ngày (Claude
    trên máy worker đọc qua controllers/misa_invoice_ai_controller.py) và cho
    bin/check_misa_invoice_gap_reasons.py — 1 chỗ tính, 2 nơi dùng.

    Chia 2 bước vì chi phí khác hẳn: gap_orders chỉ đọc DB (mọi đơn lệch, nhanh); review_orders
    gọi MISA từng đơn (đề nghị, dòng hàng) — dùng đúng _misa_invoice_line_moves của soát theo
    đơn, nên lý do in ra khớp với số module thật sự tính."""
    _name = 'misa.invoice.gap.review'
    _description = 'Soát lý do lệch đối soát MISA'

    # ------------------------------------------------------------------
    # Bước 1 — chỉ DB
    # ------------------------------------------------------------------
    @api.model
    def _picking_gap(self, picking):
        return (picking.misa_invoice_net_actual_amount or 0.0) - (picking.misa_invoice_allocated_amount or 0.0)

    @api.model
    def gap_orders(self, month=False, saler_code=False, limit=300):
        """Đơn có phiếu lệch quá dung sai trong phạm vi đối soát, lệch lớn trước.

        month 'YYYY-MM' lọc theo tháng xuất kho của PHIẾU lệch; saler_code lọc theo mã sale của
        phiếu. Trả {orders: [...], pairs: [(đơn thiếu, đơn thừa, tiền)], total_gap, order_count}
        — total_gap/order_count tính trên MỌI đơn khớp lọc, orders cắt ở limit."""
        Picking = self.env['stock.picking'].sudo()
        domain = Picking._misa_invoice_dashboard_base_domain()
        if saler_code:
            domain += [('misa_invoice_saler_code', '=', saler_code)]
        by_order = defaultdict(lambda: Picking.browse())
        for picking in Picking.search(domain):
            if abs(self._picking_gap(picking)) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                continue
            if month and (not picking.date_done or picking.date_done.strftime('%Y-%m') != month):
                continue
            for order in picking.misa_invoice_sale_order_ids:
                by_order[order.id] |= picking
        today = fields.Date.context_today(self)
        rows = []
        for order_id, gap_pickings in by_order.items():
            order = self.env['sale.order'].sudo().browse(order_id)
            order_gap = sum(self._picking_gap(p) for p in order._misa_invoice_done_out_pickings())
            oldest = min((p.date_done.date() for p in gap_pickings if p.date_done), default=today)
            rows.append({
                'id': order.id, 'name': order.name,
                'partner': order.partner_id.commercial_partner_id.name or '',
                'partner_id': order.partner_id.commercial_partner_id.id,
                'saler_codes': sorted(set(gap_pickings.mapped('misa_invoice_saler_code')) - {False}),
                'gap': order_gap, 'age_days': (today - oldest).days,
                'gap_pickings': [{
                    'name': p.name, 'date_done': fields.Date.to_string(p.date_done.date()) if p.date_done else '',
                    'net_actual': p.misa_invoice_net_actual_amount or 0.0,
                    'allocated': p.misa_invoice_allocated_amount or 0.0, 'gap': self._picking_gap(p),
                    'state': p.misa_invoice_state, 'request_refno': p.misa_invoice_request_refno or '',
                    'invoice_no': p.misa_invoice_no or '',
                } for p in gap_pickings],
            })
        rows.sort(key=lambda r: -abs(r['gap']))
        return {
            'order_count': len(rows), 'total_gap': sum(r['gap'] for r in rows),
            'orders': rows[:limit],
            'pairs': opposite_pairs(
                [(r['partner_id'], r['name'], r['gap']) for r in rows], MISA_INVOICE_AMOUNT_TOLERANCE,
            ),
        }

    # ------------------------------------------------------------------
    # Bước 2 — gọi MISA
    # ------------------------------------------------------------------
    @api.model
    def _shipped_by_item(self, order):
        """{mã hàng: {qty, amount trước thuế, rates}} theo dòng đơn bán (qty_delivered, đã trừ trả)."""
        result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set()})
        for line in order.order_line.filtered(lambda l: not l.display_type and l.qty_delivered):
            item = result[item_key(line.product_id.default_code)]
            unit = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0
            item['qty'] += line.qty_delivered
            item['amount'] += unit * line.qty_delivered
            item['rates'].add(tax_rate(line.price_subtotal, line.price_total))
        return result

    @api.model
    def _invoiced_by_item(self, order, moves, lines, customs):
        """{mã hàng: {qty, amount trước thuế, rates}} đã phát hành HĐ (đề nghị sau khi chuyển dòng
        ghi nhầm + HĐ hải quan)."""
        result = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'rates': set()})
        for key, (req, raw) in lines.items():
            if not req['inv_no']:
                continue
            line_qty = raw.get('quantity') or 0.0
            qty = owned_qty(order.name, (raw.get('order_code') or '').strip(), line_qty, moves.get(key, []))
            if qty <= 0:
                continue
            item = result[item_key(raw.get('inventory_item_code'))]
            before = raw.get('amount_oc') or 0.0
            item['qty'] += qty
            item['amount'] += before * qty / line_qty if line_qty else before
            item['rates'].add(tax_rate(before, before + (raw.get('vat_amount_oc') or 0.0)))
        for line in customs:
            item = result[item_key(line.inventory_item_code)]
            item['qty'] += line.quantity or 0.0
            item['amount'] += line.amount_before_vat or 0.0
            item['rates'].add(tax_rate(line.amount_before_vat or 0.0, line.amount or 0.0))
        return result

    @api.model
    def review_orders(self, order_ids):
        """Lý do lệch từng đơn (tối đa REVIEW_BATCH_LIMIT đơn/lượt). Mỗi đơn trả số liệu + `reasons`
        = list mã lý do máy đọc được:
          no_invoice, pending_request   chưa có HĐ / đề nghị chưa phát hành
          missing_items, extra_items    HĐ thiếu / thừa mã hàng so với đã giao
          tax_diff, price_diff          % thuế / đơn giá trên đơn bán khác HĐ
          duplicate_request             >= 2 đề nghị cùng số tiền cho đơn
          customs_unmatched             dòng HĐ hải quan chưa khớp phiếu
          mislabeled                    dòng ghi nhầm / bỏ trống mã đơn CHƯA được chuyển
          stale, not_checked            số theo đơn cũ / chưa soát theo đơn
        `refresh_fixes` = True khi soát lại theo đơn là tự sửa (mislabeled / stale / not_checked).
        Đơn gọi MISA lỗi trả `error`, không làm hỏng cả lượt."""
        orders = self.env['sale.order'].sudo().browse(list(order_ids)[:REVIEW_BATCH_LIMIT]).exists()
        CustomsLine = self.env['misa.invoice.customs.line'].sudo()
        requests_cache, lines_cache = {}, {}
        result = []
        for order in orders:
            row = {'id': order.id, 'name': order.name}
            try:
                moves, lines = order._misa_invoice_line_moves(requests_cache, lines_cache)
                owned = order._misa_invoice_owned_request_amounts(moves, lines)
            except Exception as e:
                _logger.exception("❌ [MISA GAP REVIEW] Lỗi soát đơn %s", order.name)
                row['error'] = str(e)
                result.append(row)
                continue
            customs = CustomsLine.search([
                '|', '|', ('order_code', '=', order.name), ('sale_order_id', '=', order.id),
                ('match_ids.picking_id', 'in', order._misa_invoice_done_out_pickings().ids),
            ])
            items = compare_items(
                self._shipped_by_item(order), self._invoiced_by_item(order, moves, lines, customs),
                MISA_INVOICE_AMOUNT_TOLERANCE,
            )
            issued_now = sum(amount for req, amount, _n in owned if req['inv_no'])
            checked = bool(order.misa_invoice_order_checked_at)
            stale = checked and abs(order.misa_invoice_order_invoiced_amount - issued_now) > MISA_INVOICE_AMOUNT_TOLERANCE
            has_moves = any(
                order.name in {(lines[k][1].get('order_code') or '').strip()} | {t for t, _p, _q in v}
                for k, v in moves.items()
            )
            unmatched = customs.filtered(lambda l: l.match_state != 'matched')
            duplicates = duplicate_requests([(req['refno'], req['inv_no'], amount) for req, amount, _n in owned])
            reasons = []
            if not issued_now and not customs:
                reasons.append('pending_request' if owned else 'no_invoice')
            for key in ('missing', 'extra'):
                if items[key] and (issued_now or customs):
                    reasons.append(key + '_items')
            for key in ('tax_diff', 'price_diff'):
                if items[key]:
                    reasons.append(key)
            if duplicates:
                reasons.append('duplicate_request')
            if unmatched:
                reasons.append('customs_unmatched')
            if has_moves and (stale or not checked):
                reasons.append('mislabeled')
            if stale:
                reasons.append('stale')
            if not checked and issued_now:
                reasons.append('not_checked')
            row.update({
                'reasons': reasons,
                'refresh_fixes': bool({'mislabeled', 'stale', 'not_checked'} & set(reasons)),
                'issued_now': issued_now, 'stored_invoiced': order.misa_invoice_order_invoiced_amount,
                'requests': [{
                    'refno': req['refno'], 'inv_no': req['inv_no'], 'amount': amount, 'notes': notes,
                } for req, amount, notes in owned],
                'duplicates': [{'amount': amount, 'requests': reqs} for amount, reqs in duplicates],
                'customs': [{
                    'invoice_no': l.invoice_no, 'item': l.inventory_item_code, 'qty': l.quantity,
                    'amount': l.amount, 'state': l.match_state, 'remaining': l.remaining_qty(),
                } for l in customs],
                **items,
            })
            result.append(row)
        return result

    @api.model
    def refresh_orders(self, order_ids):
        """Soát lại theo đơn với MISA (tối đa REFRESH_BATCH_LIMIT đơn/lượt) — cùng việc nút "Kiểm
        tra MISA ngay". Trả [{name, gap_before, gap_after}] để báo cáo ghi được đã sửa gì."""
        orders = self.env['sale.order'].sudo().browse(list(order_ids)[:REFRESH_BATCH_LIMIT]).exists()
        before = {o.id: sum(self._picking_gap(p) for p in o._misa_invoice_done_out_pickings()) for o in orders}
        orders._misa_invoice_refresh_order_truth()
        self.env.invalidate_all()
        return [{
            'id': o.id, 'name': o.name, 'gap_before': before[o.id],
            'gap_after': sum(self._picking_gap(p) for p in o._misa_invoice_done_out_pickings()),
        } for o in orders]
