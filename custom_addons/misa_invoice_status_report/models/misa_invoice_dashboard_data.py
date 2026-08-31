from collections import defaultdict
from datetime import date, timedelta

from odoo import api, fields, models

from .stock_picking import (
    MISA_INVOICE_AMOUNT_TOLERANCE, MISA_INVOICE_RECONCILE_GROUP, MISA_INVOICE_STATE_LABELS,
    MISA_INVOICE_UNASSIGNED_SALER,
)

# Số liệu tổng hợp cho dashboard OWL nội bộ (KPI tiles, bảng theo kho/sale/khách hàng, bảng
# "Tình trạng xuất hóa đơn", biểu đồ theo ngày) — tách khỏi stock_picking.py (đã quá lớn).
# Toàn bộ CHỈ ĐỌC (search_count/read_group), không tự tính toán/khớp dòng hàng gì — an toàn để
# tách riêng, không đụng tới logic đối soát cốt lõi.


class StockPickingMisaInvoiceDashboardData(models.Model):
    _inherit = 'stock.picking'

    def _misa_invoice_state_breakdown(self, domain):
        Picking = self.sudo()
        return {
            'missing': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'missing'), ('misa_invoice_exception', '=', False)]
            ),
            'requested': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'requested'), ('misa_invoice_exception', '=', False)]
            ),
            'invoiced': Picking.search_count(domain + [('misa_invoice_state', '=', 'invoiced')]),
            'exception': Picking.search_count(domain + [('misa_invoice_exception', '=', True)]),
        }

    def _misa_invoice_amount_sums(self, pickings):
        invoiced = pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced')
        not_invoiced = pickings - invoiced
        return {
            'actual_amount_total': sum(pickings.mapped('misa_invoice_net_actual_amount')),
            'invoice_amount_total': sum(invoiced.mapped('misa_invoice_effective_amount')),
            'outstanding_amount_total': sum(not_invoiced.mapped('misa_invoice_net_actual_amount')),
        }

    def _misa_invoice_grouped_breakdown(self, domain, groupby_field):
        """Như _misa_invoice_amount_sums() + _misa_invoice_state_breakdown() nhưng cho TẤT
        CẢ các nhóm của 1 field (VD từng nhân viên sale, từng khách hàng) cùng lúc, bằng ĐÚNG
        1 lệnh read_group (SQL GROUP BY) — thay vì lặp N truy vấn (search + 4 search_count +
        vài mapped) cho từng nhóm. Bắt buộc phải làm vậy vì số nhóm (đặc biệt là khách hàng)
        có thể lên tới hàng trăm/nghìn khi phạm vi lọc có hàng nghìn phiếu, N+1 query ở đây
        mới chính là nguyên nhân dashboard lag chứ không phải do thiếu phân trang.

        Trả về dict {group_key: {total, missing, requested, invoiced, exception,
        actual_amount_total, invoice_amount_total, outstanding_amount_total}} — group_key là
        id (Many2one), giá trị field (Char), hoặc False cho nhóm rỗng."""
        Picking = self.sudo()
        groups = defaultdict(lambda: {
            'total': 0, 'missing': 0, 'requested': 0, 'invoiced': 0, 'exception': 0,
            'actual_amount_total': 0.0, 'invoice_amount_total': 0.0, 'outstanding_amount_total': 0.0,
        })
        rows = Picking.read_group(
            domain,
            ['misa_invoice_net_actual_amount:sum', 'misa_invoice_effective_amount:sum'],
            [groupby_field, 'misa_invoice_state', 'misa_invoice_exception'],
            lazy=False,
        )
        for row in rows:
            key = row[groupby_field]
            key = key[0] if isinstance(key, tuple) else key
            count = row['__count']
            state = row['misa_invoice_state']
            exception = row['misa_invoice_exception']
            actual_sum = row['misa_invoice_net_actual_amount'] or 0.0
            invoice_sum = row['misa_invoice_effective_amount'] or 0.0

            bucket = groups[key]
            bucket['total'] += count
            bucket['actual_amount_total'] += actual_sum
            if state == 'invoiced':
                bucket['invoiced'] += count
                bucket['invoice_amount_total'] += invoice_sum
            else:
                bucket['outstanding_amount_total'] += actual_sum
                if not exception:
                    if state == 'missing':
                        bucket['missing'] += count
                    elif state == 'requested':
                        bucket['requested'] += count
            if exception:
                bucket['exception'] += count
        return groups

    @api.model
    def get_misa_invoice_dashboard_data(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Số liệu tổng quan cho dashboard OWL (KPI tiles + bảng theo kho/sale/khách hàng)."""
        Picking = self.sudo()
        base_domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )

        counts = {}
        for state in MISA_INVOICE_STATE_LABELS:
            counts[state] = Picking.search_count(
                base_domain + [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
            )
        exception_count = Picking.search_count(base_domain + [('misa_invoice_exception', '=', True)])
        # Loại các nhóm ĐÃ xác minh xong (misa_invoice_gap_resolved) khỏi số KPI — số này phải
        # phản ánh đúng "còn bao nhiêu cần xử lý", không đếm luôn cả case đã hiểu rõ lý do lệch
        # nhưng không cần ai làm gì thêm (case thật KBC/OUT/10826).
        mismatch_count = Picking.search_count(
            base_domain + [('misa_invoice_amount_mismatch', '=', True), ('misa_invoice_gap_resolved', '=', False)]
        )
        # Đếm riêng "xuất HĐ 1 phần theo ĐƠN HÀNG" (misa_invoice_order_coverage='partial') —
        # KHÁC với mismatch_count ở trên: 1 phiếu có thể misa_invoice_state='missing' (chưa tự
        # có đề nghị riêng) nhưng đơn hàng của nó đã được xuất HĐ 1 phần qua phiếu/đề nghị khác
        # (case thật KBC/OUT/06650) — con số này mới phản ánh đúng "đơn nào thật sự còn dở
        # dang", không lẫn với "chưa kiểm tra" hay "chưa có gì cả".
        partial_coverage_count = Picking.search_count(
            base_domain + [('misa_invoice_order_coverage', '=', 'partial')]
        )
        total = sum(counts.values()) + exception_count

        invoiced_sum = Picking.read_group(
            base_domain + [('misa_invoice_state', '=', 'invoiced')], ['misa_invoice_effective_amount:sum'], [],
        )
        invoiced_amount = (invoiced_sum[0]['misa_invoice_effective_amount'] or 0.0) if invoiced_sum else 0.0

        by_warehouse = []
        warehouses = self.env['stock.warehouse'].sudo().search([])
        for wh in warehouses:
            wh_domain = base_domain + [('picking_type_id.warehouse_id', '=', wh.id)]
            wh_pickings = Picking.search(wh_domain)
            if not wh_pickings:
                continue
            row = self._misa_invoice_state_breakdown(wh_domain)
            row.update({
                'warehouse_id': wh.id, 'warehouse_name': wh.name, 'total': len(wh_pickings),
                'pending': row['missing'] + row['requested'],
            })
            row.update(self._misa_invoice_amount_sums(wh_pickings))
            by_warehouse.append(row)
        by_warehouse.sort(key=lambda row: row['missing'], reverse=True)

        by_saler = []
        saler_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_saler_code'])
        saler_stats = self._misa_invoice_grouped_breakdown(base_domain, 'misa_invoice_saler_code')
        for grp in saler_groups:
            stats = saler_stats[grp['misa_invoice_saler_code']]
            row = {
                'missing': stats['missing'],
                'requested': stats['requested'],
                'invoiced': stats['invoiced'],
                'exception': stats['exception'],
                'saler_code': grp['misa_invoice_saler_code'] or MISA_INVOICE_UNASSIGNED_SALER,
                'total': grp['misa_invoice_saler_code_count'],
                'pending': stats['missing'] + stats['requested'],
                'actual_amount_total': stats['actual_amount_total'],
                'invoice_amount_total': stats['invoice_amount_total'],
                'outstanding_amount_total': stats['outstanding_amount_total'],
            }
            # % hoàn thành = SỐ LƯỢNG phiếu đã xuất HĐ / tổng số phiếu (không so theo tiền —
            # 2 số tiền đến từ 2 hệ thống khác nhau, tổng có thể lệch nên tỷ lệ theo tiền
            # từng cho ra > 100%, không phản ánh đúng "hoàn thành bao nhiêu %").
            row['completion_pct'] = round(row['invoiced'] / row['total'] * 100, 1) if row['total'] else 0.0
            by_saler.append(row)
        by_saler.sort(key=lambda row: row['completion_pct'], reverse=True)
        for idx, row in enumerate(by_saler, start=1):
            row['rank'] = idx

        # Nhóm theo công ty gốc (misa_invoice_root_partner_id), không theo địa chỉ/chi
        # nhánh cụ thể trên từng phiếu — tránh 1 khách hàng bị tách thành nhiều dòng.
        by_customer = []
        customer_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_root_partner_id'])
        customer_stats = self._misa_invoice_grouped_breakdown(base_domain, 'misa_invoice_root_partner_id')
        for grp in customer_groups:
            partner = grp['misa_invoice_root_partner_id']  # False, hoặc (id, display_name)
            partner_id = partner[0] if partner else False
            stats = customer_stats[partner_id]
            by_customer.append({
                'missing': stats['missing'],
                'requested': stats['requested'],
                'invoiced': stats['invoiced'],
                'exception': stats['exception'],
                'partner_id': partner_id,
                'partner_name': partner[1] if partner else 'Chưa có khách hàng',
                'total': grp['misa_invoice_root_partner_id_count'],
                'pending': stats['missing'] + stats['requested'],
                'actual_amount_total': stats['actual_amount_total'],
                'invoice_amount_total': stats['invoice_amount_total'],
                'outstanding_amount_total': stats['outstanding_amount_total'],
            })
        by_customer.sort(key=lambda row: row['pending'], reverse=True)

        cron = self.env.ref('misa_invoice_status_report.ir_cron_misa_invoice_status_scan', raise_if_not_found=False)
        last_scan_at = False
        if cron and cron.sudo().lastcall:
            last_scan_at = fields.Datetime.to_string(cron.sudo().lastcall)

        return {
            'counts': counts,
            'exception_count': exception_count,
            'mismatch_count': mismatch_count,
            'partial_coverage_count': partial_coverage_count,
            'total': total,
            'invoiced_amount': invoiced_amount,
            'by_warehouse': by_warehouse,
            'by_saler': by_saler,
            'by_customer': by_customer,
            'last_scan_at': last_scan_at,
            'cutoff_date': fields.Date.to_string(self._get_misa_invoice_cutoff_date()),
            'can_configure': self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP),
            'show_admin_tools': self._get_misa_invoice_show_admin_tools(),
        }

    @api.model
    def get_misa_invoice_status_summary(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Bảng 'Tình trạng xuất hóa đơn': đúng 4 trạng thái đối soát đã dùng xuyên suốt
        dashboard (Chưa kiểm tra / Chưa có đề nghị / Đã đề nghị chờ HĐ / Đã xuất HĐ) + Ngoại lệ
        + Đơn Shopee (luồng hóa đơn điện tử meInvoice riêng), kèm số phiếu / tổng tiền XK /
        tổng tiền đã xuất HĐ / tỷ lệ phiếu. Dòng Shopee được CỘNG VÀO dòng TỔNG CỘNG để tổng
        tiền xuất kho/đã xuất HĐ phản ánh đúng TOÀN BỘ hệ thống (MISA + Shopee), không chỉ
        riêng phần MISA — đây là điểm mấu chốt để 2 số cộng lại luôn khớp với tổng."""
        # Gộp bằng 1 lệnh read_group (SQL GROUP BY) thay vì search() cả nghìn phiếu rồi
        # filtered()/mapped() nhiều lần trong Python — tránh tải cả recordset lớn vào bộ nhớ.
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        rows = {state: {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0} for state in MISA_INVOICE_STATE_LABELS}
        rows['exception'] = {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0}
        rows['total'] = {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0}

        grouped = Picking.read_group(
            domain,
            ['misa_invoice_net_actual_amount:sum', 'misa_invoice_effective_amount:sum'],
            ['misa_invoice_state', 'misa_invoice_exception'],
            lazy=False,
        )
        for grp in grouped:
            count = grp['__count']
            state = grp['misa_invoice_state']
            exception = grp['misa_invoice_exception']
            actual_sum = grp['misa_invoice_net_actual_amount'] or 0.0
            invoice_sum = grp['misa_invoice_effective_amount'] or 0.0

            rows['total']['count'] += count
            rows['total']['actual_amount'] += actual_sum
            if state == 'invoiced':
                rows['total']['invoice_amount'] += invoice_sum

            if exception:
                rows['exception']['count'] += count
                rows['exception']['actual_amount'] += actual_sum
                if state == 'invoiced':
                    rows['exception']['invoice_amount'] += invoice_sum
            elif state in rows:
                rows[state]['count'] += count
                rows[state]['actual_amount'] += actual_sum
                if state == 'invoiced':
                    rows[state]['invoice_amount'] += invoice_sum

        shopee_domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        shopee_summary = Picking._misa_invoice_shopee_summary(shopee_domain)
        rows['shopee'] = {
            'count': shopee_summary['total_count'],
            'actual_amount': shopee_summary['total_actual_amount'],
            'invoice_amount': shopee_summary['total_invoice_amount'],
        }
        rows['total']['count'] += rows['shopee']['count']
        rows['total']['actual_amount'] += rows['shopee']['actual_amount']
        rows['total']['invoice_amount'] += rows['shopee']['invoice_amount']

        # Hải quan: đơn vị tính là DÒNG HÓA ĐƠN (misa.invoice.customs.line), không phải PHIẾU
        # XUẤT KHO như các dòng khác — không cộng count vào total (khác đơn vị, sẽ làm sai tỷ
        # lệ phiếu). actual_amount ở đây = matched_amount (phần ĐÃ thực xuất kho ứng với các
        # lượt khớp match_ids) — số này CHỈ để tham khảo, KHÔNG cộng vào total.actual_amount vì
        # giá trị đó đã nằm sẵn trong tiền thực xuất của chính phiếu ở dòng 'invoiced' rồi (cộng
        # thêm sẽ đếm trùng 2 lần). Chỉ cộng invoice_amount (= phần CHƯA khớp phiếu nào, xem
        # _misa_invoice_customs_summary) vào tổng đã xuất HĐ.
        customs_summary = Picking._misa_invoice_customs_summary(date_from, date_to)
        rows['customs'] = {
            'count': customs_summary['total_count'],
            'actual_amount': customs_summary['matched_amount'],
            'invoice_amount': customs_summary['pending_amount'],
        }
        rows['total']['invoice_amount'] += rows['customs']['invoice_amount']

        total_count = rows['total']['count'] or 1
        for row in rows.values():
            row['percentage'] = round(row['count'] / total_count * 100, 1)
        return rows

    @api.model
    def get_misa_invoice_daily_stats(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
        saler_code=False, weekly=False,
    ):
        """Bảng 'Theo ngày': tổng tiền xuất kho vs tổng tiền đã xuất HĐ, theo từng ngày (hoặc
        từng tuần nếu weekly=True) trong phạm vi lọc, lọc thêm được theo 1 nhân viên sale.
        Gộp bằng Python (không dùng read_group theo granularity ngày/tuần) để tránh phụ
        thuộc định dạng nhãn ngày theo locale của Odoo, đảm bảo sort/hiển thị ổn định."""
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))

        pickings = Picking.search(domain)
        buckets = {}
        for picking in pickings:
            if not picking.date_done:
                continue
            day = picking.date_done.date()
            if weekly:
                iso_year, iso_week, _iso_weekday = day.isocalendar()
                key = (iso_year, iso_week)
                label = "Tuần %s/%s" % (iso_week, iso_year)
                week_start = date.fromisocalendar(iso_year, iso_week, 1)
                bucket_date_from = fields.Date.to_string(week_start)
                bucket_date_to = fields.Date.to_string(week_start + timedelta(days=6))
            else:
                key = day
                label = fields.Date.to_string(day)
                bucket_date_from = bucket_date_to = label
            bucket = buckets.setdefault(key, {
                'label': label, 'actual_amount': 0.0, 'invoice_amount': 0.0,
                'date_from': bucket_date_from, 'date_to': bucket_date_to,
            })
            bucket['actual_amount'] += picking.misa_invoice_net_actual_amount or 0.0
            if picking.misa_invoice_state == 'invoiced':
                bucket['invoice_amount'] += picking.misa_invoice_effective_amount or 0.0

        return [buckets[key] for key in sorted(buckets.keys())]

    @api.model
    def get_misa_invoice_reconciliation_gap_explain(self, date_from=False, date_to=False, saler_code=False):
        """Giải thích CỤ THỂ (phiếu nào, bao nhiêu tiền) vì sao "Còn lại chưa xuất HĐ"
        (get_misa_invoice_reconciliation_totals, tính ở mức phiếu) có thể khác tổng
        outstanding_amount cộng dồn qua từng phiếu/đơn hiển thị trên list/Excel — thay vì 1 câu
        cảnh báo chung chung. 2 nguồn lệch đã biết:

        1. "Đơn hải quan chưa khớp PXK" — hóa đơn KHÔNG gắn với phiếu xuất kho nào, nên không
           thể hiện ở bất kỳ dòng phiếu/đơn nào (đã có count/amount sẵn, chỉ liệt kê lại).
        2. "Nhóm bắc cầu qua ranh giới ngày lọc" — 1 đề nghị gộp chung (đại diện + phiếu ăn
           theo) có phiếu NẰM NGOÀI khoảng date_from/date_to đang lọc, nhưng phiếu đó vẫn góp
           actual_amount vào NHÓM (misa_invoice_amount_diff tính trên TOÀN NHÓM, không cắt theo
           ngày — xem _misa_invoice_order_row/_misa_invoice_picking_to_row) — khiến phiếu ĐANG
           hiển thị trong khoảng lọc "gánh" 1 phần tiền của phiếu không hiển thị. Chỉ xảy ra khi
           CÓ lọc ngày; không lọc ngày thì không nhóm nào bị cắt ngang.
        3. "Nhóm dùng chung nhiều mã sale" — 1 đề nghị gộp chung cho khách hàng của NHIỀU nhân
           viên bán khác nhau. get_misa_invoice_reconciliation_totals lọc theo saler_code bằng
           read_group NÊN CHỈ đếm actual_amount của ĐÚNG các phiếu thuộc saler đang xem, nhưng
           tiền hóa đơn (misa_invoice_effective_amount) của CẢ NHÓM lại được tính TRỌN VẸN cho
           saler của phiếu ĐẠI DIỆN — khiến 1 saler bị "nhận thừa" tín dụng hóa đơn tương ứng
           với phần actual của saler KHÁC trong nhóm. Chỉ xảy ra khi CÓ lọc saler_code."""
        Picking = self.sudo()
        boundary_groups = []
        if date_from or date_to:
            parsed_from = fields.Date.from_string(date_from) if date_from else None
            parsed_to = fields.Date.from_string(date_to) if date_to else None

            def in_range(picking):
                d = picking.date_done.date() if picking.date_done else None
                if not d:
                    return False
                if parsed_from and d < parsed_from:
                    return False
                if parsed_to and d > parsed_to:
                    return False
                return True

            rep_domain = [
                ('picking_type_id.code', '=', 'outgoing'),
                ('misa_invoice_master_picking_id', '=', False),
                ('misa_invoice_covered_picking_ids', '!=', False),
            ]
            if saler_code:
                value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
                rep_domain.append(('misa_invoice_saler_code', '=', value))
            for rep in Picking.search(rep_domain):
                group = rep | rep.misa_invoice_covered_picking_ids
                visible = group.filtered(in_range)
                hidden = group - visible
                # Nhóm toàn bộ TRONG hoặc toàn bộ NGOÀI khoảng lọc — không bị cắt ngang, bỏ qua.
                if not visible or not hidden:
                    continue
                # QUAN TRỌNG: có phiếu ngoài khoảng KHÔNG có nghĩa là nhóm đang THIẾU tiền — phải
                # tính đúng group_outstanding (group_actual - group_invoice, y hệt
                # _misa_invoice_picking_to_row) rồi CHỈ báo phần thật sự ảnh hưởng tới các phiếu
                # đang hiển thị (chia theo tỷ lệ actual_amount) — KHÔNG phải toàn bộ actual_amount
                # của phiếu ngoài khoảng (số đó có thể lớn hơn nhiều so với phần thiếu thật, nếu
                # nhóm đã đủ/gần đủ tiền — case gây hiểu lầm "cộng lại lớn hơn nhiều" đã gặp).
                group_actual = sum(group.mapped('misa_invoice_net_actual_amount')) or 0.0
                group_invoice = rep.misa_invoice_effective_amount or 0.0
                group_outstanding = max(group_actual - group_invoice, 0.0)
                if group_outstanding <= MISA_INVOICE_AMOUNT_TOLERANCE or group_actual <= 0:
                    continue
                visible_actual = sum(visible.mapped('misa_invoice_net_actual_amount')) or 0.0
                attributed_amount = group_outstanding * visible_actual / group_actual
                if attributed_amount <= MISA_INVOICE_AMOUNT_TOLERANCE:
                    continue
                boundary_groups.append({
                    'visible_picking_names': visible.mapped('name'),
                    'hidden_picking_names': hidden.mapped('name'),
                    'hidden_dates': sorted(set(
                        fields.Date.to_string(p.date_done.date()) for p in hidden if p.date_done
                    )),
                    # Phần CỤ THỂ của khoản thiếu chung của nhóm mà các phiếu ĐANG HIỂN THỊ phải
                    # gánh — đây là số cộng dồn được vào tổng "Tiền chưa xuất HĐ" trên list/Excel,
                    # KHÔNG phải toàn bộ actual_amount của phiếu ngoài khoảng.
                    'attributed_amount': attributed_amount,
                })
            boundary_groups.sort(key=lambda r: -r['attributed_amount'])

        cross_saler_groups = []
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            # KHÔNG lọc theo saler_code ở domain — phải quét CẢ nhóm mà đại diện thuộc saler
            # KHÁC nhưng có phiếu ăn theo thuộc đúng saler đang xem (2 chiều), nên chỉ giới hạn
            # theo loại phiếu + đã invoiced + có phiếu ăn theo.
            rep_domain_all = [
                ('picking_type_id.code', '=', 'outgoing'),
                ('misa_invoice_master_picking_id', '=', False),
                ('misa_invoice_covered_picking_ids', '!=', False),
                ('misa_invoice_state', '=', 'invoiced'),
            ]
            for rep in Picking.search(rep_domain_all):
                group = rep | rep.misa_invoice_covered_picking_ids
                salers_in_group = set(group.mapped('misa_invoice_saler_code'))
                if value not in salers_in_group or len(salers_in_group) <= 1:
                    continue
                group_actual = sum(group.mapped('misa_invoice_net_actual_amount')) or 0.0
                if group_actual <= 0:
                    continue
                group_invoice = rep.misa_invoice_effective_amount or 0.0
                group_outstanding = max(group_actual - group_invoice, 0.0)
                this_saler_members = group.filtered(lambda m: m.misa_invoice_saler_code == value)
                other_saler_members = group - this_saler_members
                this_saler_actual = sum(this_saler_members.mapped('misa_invoice_net_actual_amount')) or 0.0
                # Số CỦA TÔI (đúng, y hệt _misa_invoice_picking_to_row) — chia group_outstanding
                # theo tỷ lệ actual_amount, không quan tâm saler.
                my_contribution = group_outstanding * this_saler_actual / group_actual
                # Số của "Đối chiếu tổng" khi lọc theo saler này — chỉ đếm actual của saler này,
                # và CHỈ trừ group_invoice nếu chính ĐẠI DIỆN thuộc saler này (nếu không, saler
                # này không được ghi nhận ĐỒNG NÀO tiền hóa đơn của nhóm, dù có phiếu ăn theo).
                ground_truth_contribution = this_saler_actual - (
                    group_invoice if rep.misa_invoice_saler_code == value else 0.0
                )
                gap = my_contribution - ground_truth_contribution
                if abs(gap) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                    continue
                cross_saler_groups.append({
                    'representative_name': rep.name,
                    'representative_saler_code': rep.misa_invoice_saler_code or '',
                    'this_saler_picking_names': this_saler_members.mapped('name'),
                    'other_saler_picking_names': other_saler_members.mapped('name'),
                    'other_saler_codes': sorted(salers_in_group - {value}),
                    # Dương: số của tôi CAO hơn Đối chiếu tổng (Excel > số thật vì nhóm này).
                    # Âm: ngược lại (số thật cao hơn Excel vì nhóm này).
                    'gap_amount': gap,
                })
            cross_saler_groups.sort(key=lambda r: -abs(r['gap_amount']))

        customs_summary = Picking._misa_invoice_customs_summary(date_from, date_to, saler_code)
        return {
            'boundary_groups': boundary_groups,
            'cross_saler_groups': cross_saler_groups,
            'cross_saler_total_amount': sum(g['gap_amount'] for g in cross_saler_groups),
            'boundary_total_amount': sum(g['attributed_amount'] for g in boundary_groups),
            'customs_pending_amount': customs_summary['pending_amount'],
            'customs_pending_count': customs_summary['pending_count'],
        }
