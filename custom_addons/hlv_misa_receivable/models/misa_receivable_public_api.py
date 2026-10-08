# -*- coding: utf-8 -*-
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
        picking_invoice_nos = [no for (no,) in self.env['stock.picking'].sudo()._read_group(
            [('misa_invoice_saler_code', '=ilike', code), ('misa_invoice_no', '!=', False)], ['misa_invoice_no'],
        )]
        keys = self._public_invoice_keys([('saler_code', '=ilike', code)])
        keys |= self._public_invoice_keys([('invoice_no', 'in', picking_invoice_nos), ('saler_code', '=', False)])
        return [('invoice_key', 'in', list(keys))]

    def _public_invoice_keys(self, domain):
        """Tập khóa hóa đơn có ít nhất 1 dòng khớp domain — GROUP BY ở Postgres, không nạp bản ghi."""
        return {key for (key,) in self.sudo()._read_group(domain, ['invoice_key'])}

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

    def _public_invoice_rows(self, domain, today, code=False):
        """1 hàng nhẹ/hóa đơn trong domain: tổng tiền, chưa thu, hạn, quá hạn — đủ để tính ô số
        liệu, lọc, sắp xếp, phân trang mà không nạp bản ghi nào (vài câu GROUP BY ở Postgres).
        Phần tốn kém (đơn, chứng từ, sale, hẹn thu) chỉ đọc cho trang đang xem, xem
        _public_enrich_rows.

        Quá hạn tính theo hạn sớm nhất của phần CHƯA thu; hóa đơn đã thu hết không có quá hạn. Có
        code thì kèm phần chưa thu của riêng mã đó (hóa đơn chung nhiều sale)."""
        Line = self.sudo()
        unpaid_domain = expression.AND([domain, [('paid_state', '!=', 'paid')]])
        unpaid = {key: (amount, due) for key, amount, due in Line._read_group(
            unpaid_domain, ['invoice_key'], ['amount:sum', 'due_date:min'],
        )}
        unknown = self._public_invoice_keys(expression.AND([domain, [('paid_state', '=', 'unknown')]]))
        own = {key: amount for key, amount in Line._read_group(
            expression.AND([unpaid_domain, [('saler_code', '=ilike', code)]]), ['invoice_key'], ['amount:sum'],
        )} if code else {}
        rows = []
        for key, total, invoice_no, series, invoice_date, due_any, partner_name, partner_code in Line._read_group(
            domain, ['invoice_key'], [
                'amount:sum', 'invoice_no:min', 'invoice_series:min', 'invoice_date:min', 'due_date:min',
                'partner_name:min', 'partner_code:min',
            ],
        ):
            amount_unpaid, due_unpaid = unpaid.get(key, (0.0, None))
            is_paid = amount_unpaid <= MISA_INVOICE_AMOUNT_TOLERANCE
            due_date = due_any if is_paid else due_unpaid
            days = 0 if is_paid else overdue_days(due_date, today)
            rows.append({
                'invoice_key': key,
                'invoice_no': invoice_no or '',
                'invoice_series': series or '',
                'partner_code': partner_code or '',
                'partner_name': partner_name or '',
                'invoice_date': fields.Date.to_string(invoice_date) or '',
                'invoice_month': invoice_date.strftime('%Y-%m') if invoice_date else '',
                'due_date': fields.Date.to_string(due_date) or '',
                'amount_total': total or 0.0,
                'amount_unpaid': amount_unpaid,
                'amount_paid': (total or 0.0) - amount_unpaid,
                'own_amount_unpaid': own.get(key, 0.0) if code else amount_unpaid,
                'is_paid': is_paid,
                'has_unknown': key in unknown,
                'overdue_days': days,
                'status_label': 'Đã thu' if is_paid else status_label(days),
                'bucket': '' if is_paid else aging_bucket_of(days),
            })
        return rows

    def _public_enrich_rows(self, rows):
        """Bổ sung cho các hàng của TRANG đang xem: chứng từ, đơn, sale, cách tính hạn, hẹn thu."""
        if not rows:
            return rows
        Line = self.sudo()
        keys = [row['invoice_key'] for row in rows]
        due_labels = dict(self._fields['due_source'].selection)
        details = {key: (refnos, order_ids, salers, sources) for key, refnos, order_ids, salers, sources in Line._read_group(
            [('invoice_key', 'in', keys)], ['invoice_key'],
            ['voucher_refno:array_agg', 'order_id:array_agg', 'saler_code:array_agg', 'due_source:array_agg'],
        )}
        all_order_ids = {oid for _r, order_ids, _s, _d in details.values() for oid in order_ids if oid}
        order_names = {order.id: order.name for order in self.env['sale.order'].sudo().browse(list(all_order_ids))}
        followups = {f.invoice_key: f for f in self.env['misa.receivable.followup'].sudo().search([('invoice_key', 'in', keys)])}
        for row in rows:
            refnos, order_ids, salers, sources = details.get(row['invoice_key'], ([], [], [], []))
            followup = followups.get(row['invoice_key'])
            row.update({
                'voucher_refnos': list(dict.fromkeys(r for r in refnos if r)),
                'orders': list(dict.fromkeys(order_names[oid] for oid in order_ids if oid in order_names)),
                'saler_codes': list(dict.fromkeys(c for c in salers if c)),
                'due_source': ', '.join(due_labels.get(src, '') for src in dict.fromkeys(s for s in sources if s)),
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
        lọc/sắp xếp làm bằng Python, trên hàng nhẹ đã gộp sẵn ở Postgres.
        """
        today = fields.Date.context_today(self)
        code = self._public_code(saler_code)
        domain = self._public_scope_domain(code)
        if search:
            keys = self._public_invoice_keys(expression.AND([domain, self._public_search_domain(search)]))
            domain = expression.AND([domain, [('invoice_key', 'in', list(keys))]])
        rows = self._public_invoice_rows(domain, today, code)
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
            'rows': self._public_enrich_rows(visible[int(offset):int(offset) + int(limit)]),
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
