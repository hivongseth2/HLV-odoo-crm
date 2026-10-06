# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression

from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_RECONCILE_GROUP

from .misa_receivable_utils import (
    aging_bucket_of,
    in_bucket,
    overdue_days,
    status_label,
    summarize_receivables,
)
from .stock_picking import LAST_SCAN_PARAM

# API cho tab "Công nợ phải thu" trên trang /misa_sale_status. Công nợ = các phần dòng đơn bán đã
# lên chứng từ MISA mà chứng từ đó chưa thu, gộp lại theo HÓA ĐƠN (giống sheet công nợ: mỗi dòng
# 1 chứng từ). Quyền theo mã sale dùng lại ĐÚNG hàm xác thực của trang
# (stock.picking._misa_invoice_validate_public_saler_code).


class MisaSalePaymentLinePublicApi(models.Model):
    _inherit = 'misa.sale.payment.line'

    def _public_saler_domain(self, saler_code):
        code = self.env['stock.picking']._misa_invoice_validate_public_saler_code(saler_code)
        return [('saler_code', '=', code)] if code else []

    def _public_invoice_lines(self, saler_code, invoice_no):
        """Mọi dòng (đã thu lẫn chưa) của 1 hóa đơn trong phạm vi mã sale. Không có = không được xem."""
        lines = self.sudo().search(expression.AND([
            self._public_saler_domain(saler_code), [('invoice_no', '=', invoice_no)],
        ]))
        if not lines:
            raise UserError('Không tìm thấy hóa đơn %s trong mã sale đang xem.' % invoice_no)
        return lines

    @staticmethod
    def _public_search_domain(search):
        term = (search or '').strip()
        if not term:
            return []
        return expression.OR([
            [('partner_name', 'ilike', term)], [('partner_code', 'ilike', term)],
            [('invoice_no', 'ilike', term)], [('voucher_refno', 'ilike', term)],
            [('order_id.name', 'ilike', term)], [('item_code', 'ilike', term)],
        ])

    def _public_invoice_rows(self, followups, today):
        """Gộp các dòng chưa thu theo hóa đơn → 1 hàng công nợ/hóa đơn."""
        due_labels = dict(self._fields['due_source'].selection)
        groups = {}
        for line in self:
            groups.setdefault(line.invoice_no, self.browse())
            groups[line.invoice_no] |= line
        rows = []
        for invoice_no, lines in groups.items():
            # Hạn sớm nhất của hóa đơn quyết định quá hạn; dòng thiếu hạn xếp sau cùng.
            first = lines.sorted(lambda l: (l.due_date or date.max, l.id))[0]
            days = overdue_days(first.due_date, today)
            followup = followups.get(invoice_no)
            rows.append({
                'invoice_no': invoice_no,
                'voucher_refnos': list(dict.fromkeys(r for r in lines.mapped('voucher_refno') if r)),
                'partner_code': first.partner_code or '',
                'partner_name': first.partner_name or '',
                'invoice_date': fields.Date.to_string(first.invoice_date) or '',
                'due_date': fields.Date.to_string(first.due_date) or '',
                'due_source': due_labels.get(first.due_source, ''),
                'amount': sum(lines.mapped('amount')),
                'line_count': len(lines),
                'orders': list(dict.fromkeys(lines.mapped('order_id.name'))),
                'saler_codes': list(dict.fromkeys(c for c in lines.mapped('saler_code') if c)),
                'has_unknown': any(state == 'unknown' for state in lines.mapped('paid_state')),
                'overdue_days': days,
                'status_label': status_label(days),
                'bucket': aging_bucket_of(days),
                'promise_date': fields.Date.to_string(followup.promise_date) if followup else '',
                'collect_rate': followup.collect_rate if followup else 0,
                'followup_note': (followup.note or '') if followup else '',
            })
        return rows

    def _public_last_scan_label(self):
        value = self.env['ir.config_parameter'].sudo().get_param(LAST_SCAN_PARAM)
        if not value:
            return ''
        local = fields.Datetime.context_timestamp(self, fields.Datetime.from_string(value))
        return local.strftime('%H:%M %d/%m/%Y')

    @api.model
    def get_public_receivable_list(self, saler_code, search=False, bucket=False, limit=50, offset=0):
        """Danh sách công nợ theo hóa đơn cho tab trên trang public.

        Ô số liệu (summary) tính trên phạm vi mã sale + ô tìm kiếm, KHÔNG theo nhóm tuổi nợ đang
        chọn — để bấm qua lại giữa các nhóm mà vẫn thấy đủ số của mọi nhóm. Gộp/lọc nhóm tuổi nợ
        làm bằng Python vì số ngày quá hạn đổi theo ngày, không lưu được.
        """
        today = fields.Date.context_today(self)
        domain = expression.AND([
            [('paid_state', '!=', 'paid')], self._public_saler_domain(saler_code), self._public_search_domain(search),
        ])
        lines = self.sudo().search(domain)
        Followup = self.env['misa.receivable.followup'].sudo()
        followups = {f.invoice_no: f for f in Followup.search([('invoice_no', 'in', list(set(lines.mapped('invoice_no'))))])}
        rows = lines._public_invoice_rows(followups, today)
        filtered = sorted(
            (row for row in rows if in_bucket(row['overdue_days'], bucket)),
            key=lambda row: (-row['overdue_days'], row['invoice_no']),
        )
        return {
            'rows': filtered[int(offset):int(offset) + int(limit)],
            'total': len(filtered),
            'summary': summarize_receivables(rows),
            'last_scan_at': self._public_last_scan_label(),
        }

    @api.model
    def get_public_receivable_lines(self, saler_code, invoice_no):
        """Chi tiết theo dòng đơn bán của 1 hóa đơn: hàng gì, đơn nào, bao nhiêu tiền, đã thu chưa."""
        paid_labels = dict(self._fields['paid_state'].selection)
        scope_labels = dict(self._fields['match_scope'].selection)
        by_labels = dict(self._fields['match_by'].selection)
        return [{
            'order': line.order_id.name,
            'product': line.product_id.display_name,
            'item_code': line.item_code or '',
            'description': line.description or '',
            'quantity': line.quantity,
            'unit_name': line.unit_name or '',
            'amount': line.amount,
            'match_by': line.match_by or '',
            'match_note': '' if (line.match_scope, line.match_by) == ('order', 'code') else '%s — %s' % (
                scope_labels.get(line.match_scope, ''), by_labels.get(line.match_by, ''),
            ),
            'voucher_refno': line.voucher_refno or '',
            'paid_state': line.paid_state,
            'paid_label': paid_labels.get(line.paid_state, ''),
        } for line in self._public_invoice_lines(saler_code, invoice_no)]

    @api.model
    def update_public_receivable_followup(self, saler_code, invoice_no, promise_date=False, collect_rate=None, note=''):
        """Sale ghi lịch hẹn thu / xác suất thu / ghi chú cho 1 hóa đơn thuộc mã của mình."""
        self._public_invoice_lines(saler_code, invoice_no)
        rate = 0 if collect_rate in (None, '') else int(collect_rate)
        if not 0 <= rate <= 100:
            raise UserError('Xác suất thu phải từ 0 đến 100.')
        vals = {
            'promise_date': promise_date or False,
            'collect_rate': rate,
            'note': (note or '').strip() or False,
        }
        Followup = self.env['misa.receivable.followup'].sudo()
        followup = Followup.search([('invoice_no', '=', invoice_no)], limit=1)
        if followup:
            followup.write(vals)
        else:
            Followup.create(dict(vals, invoice_no=invoice_no))
        return True

    @api.model
    def recheck_public_invoice(self, saler_code, invoice_no):
        """Tra lại MISA ngay cho 1 hóa đơn (vài lệnh gọi, chạy luôn trong request) — dùng khi
        khách vừa trả mà chưa tới lượt cron."""
        self._public_invoice_lines(saler_code, invoice_no)
        result = self.env['stock.picking'].sudo()._misa_payment_scan_invoice(invoice_no)
        if result.get('error'):
            raise UserError('Lỗi tra MISA: %s' % result['error'])
        return result

    @api.model
    def request_public_receivable_sync(self):
        """Xếp lịch cron tra thu tiền chạy ngay (1 lượt tra 100 hóa đơn mất vài phút, quá thời
        gian chờ của trình duyệt nên không chạy trong request). Chỉ nhóm Đối soát XHD."""
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError('Chỉ quản lý (nhóm Đối soát XHD) được chạy tra thu tiền.')
        self.env.ref('hlv_misa_receivable.ir_cron_misa_sale_payment_scan').sudo()._trigger()
        return True
