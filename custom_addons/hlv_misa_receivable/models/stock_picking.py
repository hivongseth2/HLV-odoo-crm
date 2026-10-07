# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

from .misa_receivable_utils import allocate_entries, plan_upsert, reusable_voucher_states, voucher_payment_entries

_logger = logging.getLogger(__name__)

# Số hóa đơn tra MISA mỗi lượt cron. Mỗi hóa đơn tốn 1 lệnh tìm chứng từ + 1 lệnh/chứng từ để
# đọc dòng hàng. Lần đầu cài, hóa đơn chưa tra bao giờ được ưu tiên nên vài lượt là phủ hết;
# sau đó chỉ còn xoay vòng các hóa đơn chưa thu.
MISA_PAYMENT_SCAN_BATCH = 100

LAST_SCAN_PARAM = 'hlv_misa_receivable.last_scan_at'

# Danh tính 1 dòng đã lưu khi tra lại: cùng chứng từ, cùng dòng đơn bán, cùng mã hàng MISA là
# cùng 1 dòng — để cập nhật tại chỗ thay vì xóa hết tạo lại mỗi lượt tra.
PAYMENT_LINE_KEY_FIELDS = ('voucher_refid', 'sale_line_id', 'item_code')


class StockPickingMisaPayment(models.Model):
    _inherit = 'stock.picking'

    # Chỉ là lịch tra, không phải kết quả — kết quả nằm trên dòng đơn bán (misa.sale.payment.line).
    # Đặt trên phiếu vì hóa đơn cần tra lấy từ misa_invoice_no của phiếu.
    misa_payment_checked_at = fields.Datetime(string='Tra thu tiền MISA lúc', copy=False, index=True)
    misa_payment_done = fields.Boolean(
        string='Hóa đơn đã thu đủ', copy=False, index=True,
        help='Mọi chứng từ bán hàng của hóa đơn này đã thu tiền — cron không tra lại nữa.',
    )

    @api.model
    def _cron_scan_misa_sale_payment(self):
        scope = self._misa_invoice_dashboard_base_domain() + [
            ('misa_invoice_state', '=', 'invoiced'),
            ('misa_invoice_no', '!=', False),
            ('misa_payment_done', '=', False),
        ]
        # Hóa đơn chưa tra bao giờ trước, rồi tới hóa đơn tra lâu nhất.
        pickings = self.sudo().search(scope, order='misa_payment_checked_at asc nulls first, date_done desc')
        invoice_nos = list(dict.fromkeys(pickings.mapped('misa_invoice_no')))[:MISA_PAYMENT_SCAN_BATCH]
        for invoice_no in invoice_nos:
            self._misa_payment_scan_invoice(invoice_no)
        self.env['ir.config_parameter'].sudo().set_param(LAST_SCAN_PARAM, fields.Datetime.to_string(fields.Datetime.now()))
        _logger.info('[MISA thu tiền] Đã tra %s hóa đơn', len(invoice_nos))

    def _misa_payment_scan_invoice(self, invoice_no):
        """Tra MISA tình trạng thu tiền của 1 hóa đơn và ghi lại theo từng dòng đơn bán.

        Hóa đơn đã gắn dòng từ trước mà bộ chứng từ không đổi thì chỉ cập nhật đã thu / chưa thu
        từ kết quả tìm chứng từ (1 lệnh gọi), không đọc lại chi tiết dòng — xem
        reusable_voucher_states. Lỗi gọi MISA thì giữ nguyên dữ liệu cũ (chỉ ghi giờ tra để lượt
        sau xếp hóa đơn này về cuối hàng, không kẹt mãi ở đầu). Trả dict tóm tắt: {'invoice_no',
        'vouchers', 'lines', 'unmatched', 'done', 'reused', 'error'}.
        """
        now = fields.Datetime.now()
        pickings = self.sudo().search([('misa_invoice_no', '=', invoice_no)])
        misa_utils = self.env['misa.api.utils'].sudo()
        try:
            vouchers = misa_utils._misa_invoice_vouchers_for_inv_no(invoice_no)
            stored = self.env['misa.sale.payment.line'].sudo().search([('invoice_no', '=', invoice_no)])
            states = reusable_voucher_states(
                vouchers, {line.voucher_refid: line.voucher_total for line in stored}, MISA_INVOICE_AMOUNT_TOLERANCE,
            )
            if states:
                return self._misa_payment_update_states(invoice_no, pickings, stored, states, now)
            entries = []
            for voucher in vouchers:
                lines = misa_utils.get_voucher_lines(voucher['refid']) if voucher.get('refid') else []
                entries += voucher_payment_entries(voucher, lines)
        except Exception as e:
            _logger.exception('[MISA thu tiền] Lỗi tra hóa đơn %s', invoice_no)
            pickings.write({'misa_payment_checked_at': now})
            return {'invoice_no': invoice_no, 'error': str(e)}

        allocations, unmatched = allocate_entries(
            entries, self._misa_payment_candidates(entries), self._misa_payment_invoice_candidates(pickings),
        )
        if unmatched:
            _logger.info(
                '[MISA thu tiền] HĐ %s: %s dòng chứng từ không gắn được dòng đơn bán nào (%s)', invoice_no,
                len(unmatched), ', '.join('%s/%s' % (e['order_code'] or '?', e['item_code']) for e in unmatched[:10]),
            )
        self._misa_payment_store(invoice_no, allocations)

        done = bool(entries) and all(entry['paid_state'] == 'paid' for entry in entries)
        pickings.write({'misa_payment_checked_at': now, 'misa_payment_done': done})
        return {
            'invoice_no': invoice_no, 'vouchers': len(vouchers), 'lines': len(allocations),
            'unmatched': len(unmatched), 'done': done, 'reused': False, 'error': False,
        }

    def _misa_payment_update_states(self, invoice_no, pickings, stored, states, checked_at):
        """Đường tắt khi tra lại: chỉ ghi đã thu / chưa thu mới lên các dòng đã lưu, theo chứng từ."""
        for refid, state in states.items():
            stored.filtered(lambda line: line.voucher_refid == refid and line.paid_state != state).write({'paid_state': state})
        done = all(state == 'paid' for state in states.values())
        pickings.write({'misa_payment_checked_at': checked_at, 'misa_payment_done': done})
        return {
            'invoice_no': invoice_no, 'vouchers': len(states), 'lines': len(stored),
            'unmatched': 0, 'done': done, 'reused': True, 'error': False,
        }

    def _misa_payment_candidates(self, entries):
        """{mã đơn: [mô tả dòng đơn bán]} cho mọi đơn được nhắc tới trên các dòng chứng từ."""
        order_codes = list({entry['order_code'] for entry in entries if entry['order_code']})
        orders = self.env['sale.order'].sudo().search([('name', 'in', order_codes)]) if order_codes else []
        return {
            order.name: [
                line._misa_payment_candidate()
                for line in order.order_line if line.product_id and not line.display_type
            ]
            for order in orders
        }

    def _misa_payment_invoice_candidates(self, pickings):
        """Các dòng đơn bán đã xuất qua những phiếu mang số hóa đơn này (kể cả phiếu ăn theo
        đề nghị gộp của chúng) — Odoo đã biết chắc phiếu nào thuộc hóa đơn nào, nên đây là chỗ gắn
        cho dòng chứng từ MISA bỏ trống hoặc ghi sai mã đơn."""
        group = pickings | pickings.misa_invoice_covered_picking_ids
        sale_lines = group.move_ids.sale_line_id.filtered(lambda l: l.product_id and not l.display_type)
        return [line._misa_payment_candidate() for line in sale_lines]

    def _misa_payment_store(self, invoice_no, allocations):
        """Ghi kết quả tra mới của 1 hóa đơn: dòng không đổi thì để nguyên, dòng đổi thì chỉ sửa
        field đổi, chỉ tạo dòng mới phát sinh và chỉ xóa dòng không còn trên MISA. Hóa đơn chưa
        thu được tra lại mỗi lượt cron — xóa hết tạo lại thì mỗi lượt lại tính lại mọi dòng đơn
        bán liên quan dù MISA không đổi gì."""
        PaymentLine = self.env['misa.sale.payment.line'].sudo()
        fresh = self._misa_payment_values(invoice_no, allocations)
        stored = PaymentLine.search([('invoice_no', '=', invoice_no)])
        fields_read = list(fresh[0]) if fresh else ['id']
        existing = [(row.pop('id'), row) for row in stored.read(fields_read, load=False)] if stored else []
        updates, creates, delete_ids = plan_upsert(existing, fresh, PAYMENT_LINE_KEY_FIELDS)
        for rec_id, changed in updates.items():
            PaymentLine.browse(rec_id).write(changed)
        if delete_ids:
            PaymentLine.browse(delete_ids).unlink()
        if creates:
            PaymentLine.create(creates)

    def _misa_payment_values(self, invoice_no, allocations):
        """Giá trị cần lưu cho từng phần dòng chứng từ đã gắn vào dòng đơn bán."""
        SaleLine = self.env['sale.order.line'].sudo()
        vals_list = []
        for alloc in allocations:
            sale_line = SaleLine.browse(alloc['sale_line_id'])
            due_date, due_source = self._misa_payment_due_date(sale_line.order_id, alloc['invoice_date'])
            vals_list.append({
                'sale_line_id': sale_line.id,
                'invoice_no': invoice_no,
                'invoice_date': alloc['invoice_date'],
                'invoice_series': alloc['invoice_series'],
                'invoice_key': alloc['invoice_key'],
                'due_date': due_date,
                'due_source': due_source,
                'voucher_refid': alloc['voucher_refid'],
                'voucher_refno': alloc['voucher_refno'],
                'voucher_total': alloc['voucher_total'],
                'partner_code': alloc['partner_code'],
                'partner_name': alloc['partner_name'] or sale_line.order_id.partner_id.commercial_partner_id.name,
                # Field Studio (không khai trong code) — đọc bằng getattr như mọi module khác trong repo.
                'saler_code': getattr(sale_line.order_id, 'x_studio_misa_saler_code', False) or False,
                'item_code': alloc['item_code'],
                'description': alloc['description'],
                'quantity': alloc['quantity'],
                'unit_name': alloc['unit_name'],
                'amount': alloc['amount'],
                'match_scope': alloc['match_scope'],
                'match_by': alloc['match_by'],
                'paid_state': alloc['paid_state'],
            })
        return vals_list

    @staticmethod
    def _misa_payment_due_date(order, invoice_date):
        """Hạn thu = hạn đợt thanh toán CUỐI theo điều khoản của đơn (không có thì của khách),
        tính từ ngày hóa đơn — dùng _get_due_date của Odoo để ra đúng mọi kiểu điều khoản. Không
        có điều khoản thì đến hạn ngay ngày hóa đơn (bán thu tiền ngay). Trả (date|False, nguồn)."""
        term = order.payment_term_id or order.partner_id.property_payment_term_id
        if invoice_date and term.line_ids:
            return max(line._get_due_date(invoice_date) for line in term.line_ids), 'payment_term'
        return invoice_date or False, 'invoice_date'
