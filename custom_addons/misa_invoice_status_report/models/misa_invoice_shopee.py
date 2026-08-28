from odoo import api, fields, models

from .stock_picking import MISA_INVOICE_UNASSIGNED_SALER, MISA_SHOPEE_INVOICE_STATE_LABELS

# Tab "Đơn Shopee" (hóa đơn điện tử meInvoice riêng của amis_callback, khác luồng MISA thường)
# tách khỏi stock_picking.py (đã quá lớn) — tự đọc dữ liệu từ model meinvoice.invoice, không
# đụng gì tới logic đối soát/khớp dòng hàng MISA (an toàn để tách riêng).


class StockPickingMisaInvoiceShopee(models.Model):
    _inherit = 'stock.picking'

    def _misa_invoice_shopee_domain(self, date_from=False, date_to=False):
        return self._misa_invoice_dashboard_base_domain(date_from, date_to, shopee=True)

    def _misa_invoice_shopee_representative_invoice(self, order):
        """1 đơn Shopee có thể có nhiều bản ghi meinvoice.invoice theo thời gian (nháp, hủy rồi
        tạo lại...) — lấy bản ĐÃ PHÁT HÀNH (accepted) mới nhất nếu có (đúng nghĩa hóa đơn hợp
        lệ cuối cùng đại diện cho đơn), không thì lấy bản chưa hủy mới nhất để biết đang ở
        bước nào. Bỏ qua hẳn các bản đã hủy (cancelled) — không phản ánh thực trạng hiện tại."""
        invoices = order.amis_draft_invoice_ids.filtered(lambda inv: inv.state != 'cancelled')
        if not invoices:
            return self.env['meinvoice.invoice'].browse()
        accepted = invoices.filtered(lambda inv: inv.state == 'accepted')
        if accepted:
            return accepted.sorted('write_date', reverse=True)[0]
        return invoices.sorted('write_date', reverse=True)[0]

    def _misa_invoice_shopee_picking_to_row(self, picking, today):
        orders = picking.misa_invoice_sale_order_ids
        invoice = self.env['meinvoice.invoice'].browse()
        for order in orders:
            candidate = self._misa_invoice_shopee_representative_invoice(order)
            if not candidate:
                continue
            if not invoice or candidate.state == 'accepted':
                invoice = candidate
            if invoice.state == 'accepted':
                break
        state = invoice.state if invoice else 'missing'
        done_date = picking.date_done.date() if picking.date_done else False
        # Có trả hàng — HĐĐT Shopee đã "accepted" từ TRƯỚC lúc trả hàng nên total_amount_oc vẫn
        # giữ nguyên tiền gốc, không tự trừ theo hàng trả (khác gì MISA, chỉ là chưa từng vá
        # cho luồng Shopee). Coi như đã điều chỉnh xuống đúng bằng tiền thực xuất ròng, y hệt
        # nguyên tắc misa_invoice_effective_amount đã áp dụng cho phiếu MISA thường.
        has_return = (picking.misa_invoice_returned_amount or 0.0) > 0
        original_invoice_amount = (invoice.total_amount_oc or 0.0) if state == 'accepted' else 0.0
        invoice_amount = (
            (picking.misa_invoice_net_actual_amount or 0.0) if (state == 'accepted' and has_return)
            else original_invoice_amount
        )
        return {
            'id': picking.id,
            'name': picking.name,
            'partner_name': picking.misa_invoice_root_partner_id.display_name or picking.partner_id.display_name or '',
            'sale_order_name': ', '.join(orders.mapped('name')),
            'saler_code': picking.misa_invoice_saler_code or '',
            'date_done': fields.Date.to_string(done_date) if done_date else '',
            'days_pending': (today - done_date).days if done_date else 0,
            'actual_amount': picking.misa_invoice_net_actual_amount or 0.0,
            'state': state,
            'state_label': MISA_SHOPEE_INVOICE_STATE_LABELS.get(state, state),
            'invoice_no': invoice.inv_no or False,
            'invoice_date': fields.Date.to_string(invoice.inv_date_result) if invoice and invoice.inv_date_result else False,
            'invoice_amount': invoice_amount,
            'has_return': has_return,
            'original_invoice_amount': original_invoice_amount,
            'returned_amount': picking.misa_invoice_returned_amount or 0.0,
        }

    def _misa_invoice_shopee_summary(self, domain):
        """Tổng hợp toàn bộ phiếu Shopee khớp domain — dùng cho cả tile tổng quan lẫn số liệu
        nền cho tab Đơn Shopee. Phải build từng dòng bằng Python (không read_group được) vì
        trạng thái/tiền HĐĐT nằm ở model meinvoice.invoice, không phải field trực tiếp trên
        stock.picking — chấp nhận được vì tập Shopee luôn là 1 phần nhỏ của tổng phiếu."""
        Picking = self.sudo()
        pickings = Picking.search(domain)
        today = fields.Date.context_today(self)
        rows = [Picking._misa_invoice_shopee_picking_to_row(p, today) for p in pickings]
        by_state = {key: {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0} for key in MISA_SHOPEE_INVOICE_STATE_LABELS}
        for row in rows:
            bucket = by_state[row['state']]
            bucket['count'] += 1
            bucket['actual_amount'] += row['actual_amount']
            bucket['invoice_amount'] += row['invoice_amount']
        return {
            'rows': rows,
            'by_state': by_state,
            'total_count': len(rows),
            'total_actual_amount': sum(r['actual_amount'] for r in rows),
            'total_invoice_amount': sum(r['invoice_amount'] for r in rows),
        }

    @api.model
    def get_misa_invoice_shopee_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False,
        date_from=False, date_to=False,
    ):
        """Tab 'Đơn Shopee' trên dashboard nội bộ — danh sách phiếu Shopee + tình trạng hóa
        đơn điện tử (meInvoice), lọc/phân trang bằng Python vì trạng thái tính từ model khác
        (xem _misa_invoice_shopee_summary)."""
        Picking = self.sudo()
        domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        if search:
            domain += ['|', ('name', 'ilike', search), ('misa_invoice_sale_order_ids.name', 'ilike', search)]

        summary = Picking._misa_invoice_shopee_summary(domain)
        rows = summary['rows']
        if state:
            rows = [row for row in rows if row['state'] == state]
        rows.sort(key=lambda row: row['date_done'], reverse=True)
        total = len(rows)
        return {
            'rows': rows[offset:offset + limit],
            'total': total,
            'counts': {key: bucket['count'] for key, bucket in summary['by_state'].items()},
        }

    @api.model
    def get_misa_invoice_public_shopee_list(
        self, saler_code, search=False, state=False, date_from=False, date_to=False,
        limit=50, offset=0,
    ):
        """Tab 'Đơn Shopee' trên trang public, scope theo đúng 1 mã sale — tái dùng
        get_misa_invoice_shopee_list (nội bộ) sau khi xác thực mã sale."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_invoice_shopee_list(
            limit=limit, offset=offset, search=search, state=state, saler_code=code,
            date_from=date_from, date_to=date_to,
        )
