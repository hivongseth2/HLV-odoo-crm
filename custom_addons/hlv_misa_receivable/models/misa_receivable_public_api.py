# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression

from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_RECONCILE_GROUP

from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

from .misa_receivable_utils import (
    aging_bucket_of,
    in_bucket,
    month_options,
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

    def _public_code(self, saler_code):
        """Mã sale đã xác thực quyền; False = "Tất cả" (chỉ nhóm Đối soát XHD)."""
        return self.env['stock.picking']._misa_invoice_validate_public_saler_code(saler_code)

    def _public_scope_domain(self, code):
        """Phạm vi theo HÓA ĐƠN, không theo từng dòng: 1 hóa đơn có thể gộp đơn của 2-3 sale, lọc
        theo dòng thì mỗi sale chỉ thấy mẩu của mình — tiền, tình trạng thu, chi tiết đều bị cắt.
        Hóa đơn thuộc mã này khi có dòng đơn bán của mã này. Dòng không có mã sale (đơn không ghi
        mã) thì xét theo phiếu xuất kho của mã này (misa_invoice_saler_code) — chỉ bù cho các dòng
        đó, vì phiếu chỉ biết SỐ hóa đơn, mà 1 số có thể là 2 hóa đơn khác ký hiệu của 2 khách.
        So không phân biệt hoa/thường."""
        if not code:
            return []
        Line = self.sudo()
        keys = set(Line.search([('saler_code', '=ilike', code)]).mapped('invoice_key'))
        picking_invoice_nos = self.env['stock.picking'].sudo().search([
            ('misa_invoice_saler_code', '=ilike', code), ('misa_invoice_no', '!=', False),
        ]).mapped('misa_invoice_no')
        keys |= set(Line.search([
            ('invoice_no', 'in', picking_invoice_nos), ('saler_code', '=', False),
        ]).mapped('invoice_key'))
        return [('invoice_key', 'in', list(keys))]

    def _public_invoice_lines(self, saler_code, invoice_key):
        """Mọi dòng (đã thu lẫn chưa) của 1 hóa đơn trong phạm vi mã sale. Không có = không được xem."""
        lines = self.sudo().search(expression.AND([
            self._public_scope_domain(self._public_code(saler_code)), [('invoice_key', '=', invoice_key)],
        ]))
        if not lines:
            raise UserError('Không tìm thấy hóa đơn này trong mã sale đang xem.')
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

    def _public_invoice_rows(self, followups, today, code=False):
        """Gộp dòng theo hóa đơn → 1 hàng/hóa đơn, kèm tổng tiền, đã thu, chưa thu. Quá hạn tính
        theo hạn sớm nhất của phần CHƯA thu; hóa đơn đã thu hết không có quá hạn. Có code thì kèm
        phần chưa thu của riêng mã đó (hóa đơn chung nhiều sale)."""
        due_labels = dict(self._fields['due_source'].selection)
        groups = {}
        for line in self:
            groups.setdefault(line.invoice_key, []).append(line)
        rows = []
        for invoice_key, line_list in groups.items():
            lines = self.browse([line.id for line in line_list])
            unpaid = lines.filtered(lambda l: l.paid_state != 'paid')
            amount_unpaid = sum(unpaid.mapped('amount'))
            is_paid = amount_unpaid <= MISA_INVOICE_AMOUNT_TOLERANCE
            # Hạn sớm nhất quyết định quá hạn; dòng thiếu hạn xếp sau cùng.
            first = (unpaid or lines).sorted(lambda l: (l.due_date or date.max, l.id))[0]
            days = 0 if is_paid else overdue_days(first.due_date, today)
            followup = followups.get(invoice_key)
            rows.append({
                'invoice_key': invoice_key,
                'invoice_no': first.invoice_no,
                'invoice_series': first.invoice_series or '',
                'voucher_refnos': list(dict.fromkeys(r for r in lines.mapped('voucher_refno') if r)),
                'partner_code': first.partner_code or '',
                'partner_name': first.partner_name or '',
                'invoice_date': fields.Date.to_string(first.invoice_date) or '',
                'invoice_month': first.invoice_date.strftime('%Y-%m') if first.invoice_date else '',
                'due_date': fields.Date.to_string(first.due_date) or '',
                'due_source': due_labels.get(first.due_source, ''),
                'amount_total': sum(lines.mapped('amount')),
                'amount_unpaid': amount_unpaid,
                'amount_paid': sum(lines.mapped('amount')) - amount_unpaid,
                'own_amount_unpaid': sum(
                    line.amount for line in unpaid if (line.saler_code or '').upper() == code.upper()
                ) if code else amount_unpaid,
                'is_paid': is_paid,
                'line_count': len(lines),
                'orders': list(dict.fromkeys(lines.mapped('order_id.name'))),
                'saler_codes': list(dict.fromkeys(c for c in lines.mapped('saler_code') if c)),
                'has_unknown': any(state == 'unknown' for state in lines.mapped('paid_state')),
                'overdue_days': days,
                'status_label': 'Đã thu' if is_paid else status_label(days),
                'bucket': '' if is_paid else aging_bucket_of(days),
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

    @staticmethod
    def _public_row_visible(row, paid_filter, month, bucket):
        """Hàng hóa đơn có qua các bộ lọc không. paid_filter: 'unpaid' (mặc định) | 'paid' | 'all';
        bucket chỉ áp cho hóa đơn còn phần chưa thu."""
        if month and row['invoice_month'] != month:
            return False
        if paid_filter == 'paid' and not row['is_paid']:
            return False
        if paid_filter not in ('paid', 'all') and row['is_paid']:
            return False
        if bucket:
            return not row['is_paid'] and in_bucket(row['overdue_days'], bucket)
        return True

    @api.model
    def get_public_receivable_list(
        self, saler_code, search=False, paid_filter='unpaid', month=False, bucket=False, limit=50, offset=0,
    ):
        """Danh sách hóa đơn cho tab trên trang public.

        Ô tìm kiếm chọn ra HÓA ĐƠN (khớp 1 dòng là lấy cả hóa đơn, để tổng tiền không bị cắt). Ô số
        liệu và danh sách tháng tính trên phạm vi mã sale + tìm kiếm (+ tháng cho ô số liệu), KHÔNG
        theo bộ lọc đã thu/nhóm tuổi nợ — để bấm qua lại vẫn thấy đủ số. Quá hạn đổi theo ngày nên
        gộp/lọc làm bằng Python.
        """
        today = fields.Date.context_today(self)
        code = self._public_code(saler_code)
        saler_domain = self._public_scope_domain(code)
        Line = self.sudo()
        domain = saler_domain
        if search:
            invoice_keys = list(set(Line.search(expression.AND([saler_domain, self._public_search_domain(search)])).mapped('invoice_key')))
            domain = expression.AND([saler_domain, [('invoice_key', 'in', invoice_keys)]])
        lines = Line.search(domain)
        Followup = self.env['misa.receivable.followup'].sudo()
        followups = {f.invoice_key: f for f in Followup.search([('invoice_key', 'in', list(set(lines.mapped('invoice_key'))))])}
        rows = lines._public_invoice_rows(followups, today, code)
        in_month = [row for row in rows if not month or row['invoice_month'] == month]
        visible = [row for row in rows if self._public_row_visible(row, paid_filter, month, bucket)]
        # Còn nợ trước (quá hạn lâu nhất lên đầu), đã thu sau (hóa đơn mới nhất lên đầu).
        owing = sorted((r for r in visible if not r['is_paid']), key=lambda r: (-r['overdue_days'], r['invoice_no']))
        paid = sorted((r for r in visible if r['is_paid']), key=lambda r: (r['invoice_date'], r['invoice_no']), reverse=True)
        visible = owing + paid
        summary = summarize_receivables([
            {'amount': row['amount_unpaid'], 'overdue_days': row['overdue_days']} for row in in_month if not row['is_paid']
        ])
        summary['paid_amount'] = sum(row['amount_paid'] for row in in_month)
        summary['paid_count'] = sum(1 for row in in_month if row['is_paid'])
        return {
            'rows': visible[int(offset):int(offset) + int(limit)],
            'total': len(visible),
            'summary': summary,
            'months': month_options([fields.Date.from_string(row['invoice_date']) for row in rows if row['invoice_date']]),
            'last_scan_at': self._public_last_scan_label(),
        }

    @api.model
    def get_public_receivable_lines(self, saler_code, invoice_key):
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
            'saler_code': line.saler_code or '',
            'match_by': line.match_by or '',
            'match_note': '' if (line.match_scope, line.match_by) == ('order', 'code') else '%s — %s' % (
                scope_labels.get(line.match_scope, ''), by_labels.get(line.match_by, ''),
            ),
            'voucher_refno': line.voucher_refno or '',
            'paid_state': line.paid_state,
            'paid_label': paid_labels.get(line.paid_state, ''),
        } for line in self._public_invoice_lines(saler_code, invoice_key)]

    @api.model
    def update_public_receivable_followup(self, saler_code, invoice_key, promise_date=False, collect_rate=None, note=''):
        """Sale ghi lịch hẹn thu / xác suất thu / ghi chú cho 1 hóa đơn thuộc mã của mình."""
        lines = self._public_invoice_lines(saler_code, invoice_key)
        rate = 0 if collect_rate in (None, '') else int(collect_rate)
        if not 0 <= rate <= 100:
            raise UserError('Xác suất thu phải từ 0 đến 100.')
        vals = {
            'promise_date': promise_date or False,
            'collect_rate': rate,
            'note': (note or '').strip() or False,
        }
        Followup = self.env['misa.receivable.followup'].sudo()
        followup = Followup.search([('invoice_key', '=', invoice_key)], limit=1)
        if followup:
            followup.write(vals)
        else:
            Followup.create(dict(vals, invoice_key=invoice_key, invoice_no=lines[0].invoice_no))
        return True

    @api.model
    def recheck_public_invoice(self, saler_code, invoice_key):
        """Tra lại MISA ngay cho 1 hóa đơn (vài lệnh gọi, chạy luôn trong request) — dùng khi
        khách vừa trả mà chưa tới lượt cron. Tra theo số hóa đơn (MISA chỉ tìm được theo số)."""
        lines = self._public_invoice_lines(saler_code, invoice_key)
        result = self.env['stock.picking'].sudo()._misa_payment_scan_invoice(lines[0].invoice_no)
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
