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
        2. "Phiếu thuộc nhóm bị cắt bởi bộ lọc ngày" — 1 đề nghị gộp chung (đại diện + phiếu ăn
           theo) có đại diện KHÔNG THỎA bộ lọc ngày đang xem (nằm ngoài date_from/date_to). Mục
           này giờ ĐÃ ĐƯỢC TỰ ĐỘNG SỬA thẳng trong get_misa_invoice_reconciliation_totals (xem
           _misa_invoice_date_cut_auto_credit) — thẻ tự cộng tín dụng cho trường hợp này, không
           cần người dùng tự tra soát nữa. cut_groups ở đây thường sẽ RỖNG (chỉ còn khác 0 nếu
           có sai số làm tròn/dữ liệu vừa thay đổi giữa 2 lần tính) — giữ lại mục này làm lưới an
           toàn (safety net), không xóa hẳn.
        3. "Dùng chung mã sale khác" (cross_saler_notes) — 1 đề nghị gộp chung cho khách hàng
           của NHIỀU nhân viên bán khác nhau — get_misa_invoice_reconciliation_totals tính riêng
           theo từng saler (read_group ở MỨC PHIẾU) nên actual của saler khác không được cộng
           nhưng invoice của đại diện vẫn tính đủ (hoặc ngược lại), gây lệch. KHÔNG tự động sửa
           (khác mục 2) — hóa đơn dùng chung nhiều saler không có cách chia rạch ròi đáng tin
           (đã thử 3 công thức, ra 3 kết quả mâu thuẫn nhau), chỉ liệt kê để tự tra tay trên MISA.

        gap_amount cho CẢ 2 mục 2 và 3: ĐÃ THỬ NHIỀU CÁCH tự suy diễn công thức theo từng nhóm
        (dựa vào group_actual/group_invoice, hoặc dữ liệu exact theo đơn hàng) — luôn có nguy cơ
        sai khi nhóm phiếu lồng nhau qua nhiều cấp master/covered mà code tự viết dễ bỏ sót (case
        thật KBC/OUT/12139+12052+12192+12299: tưởng là 2 nhóm riêng, thực ra là 1 nhóm 4 phiếu
        cân bằng hoàn hảo, tính tách ra sẽ ra 2 con số "ma" cộng lại bằng 0 nhưng riêng lẻ trông
        như 2 lỗi thật ~10 triệu mỗi bên). Cách ĐÁNG TIN, đang dùng: KHÔNG suy diễn công thức nào
        cả — gọi LẠI đúng get_misa_invoice_reconciliation_totals (qua
        _misa_invoice_group_gap_contribution) với domain LOẠI TRỪ các phiếu của nhóm, đo mức
        TĂNG/GIẢM thật, nên không thể sai theo kiểu trên nữa (chỉ dùng read_group/hàm gốc, không
        tự viết lại logic nhóm).

        Một nhóm có thể vừa "dùng chung mã sale khác" vừa có phiếu bị "cắt bởi bộ lọc ngày" cùng
        lúc (case thật KBC/OUT/11810) — không tách gap_amount riêng cho từng lý do được (chỉ 1 đề
        nghị xuất HĐ dùng chung), nên xếp CẢ NHÓM vào mục "dùng chung mã sale khác" (ưu tiên hơn),
        KHÔNG lặp lại ở mục "cắt bởi bộ lọc ngày" — tránh đếm gap_amount 2 lần cho cùng 1 nhóm."""
        Picking = self.sudo()
        today = fields.Date.context_today(self)
        parsed_from = fields.Date.from_string(date_from) if date_from else None
        parsed_to = fields.Date.from_string(date_to) if date_to else None
        saler_value = False
        if saler_code:
            saler_value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code

        def in_date_range(picking):
            if not (parsed_from or parsed_to):
                return True
            d = picking.date_done.date() if picking.date_done else None
            if not d:
                return False
            if parsed_from and d < parsed_from:
                return False
            if parsed_to and d > parsed_to:
                return False
            return True

        def matches_saler(picking):
            return (not saler_code) or picking.misa_invoice_saler_code == saler_value

        def qualifies(picking):
            return in_date_range(picking) and matches_saler(picking)

        # Bước 1: tìm CÁC PHIẾU ĐANG HIỂN THỊ (thỏa filter) thuộc 1 nhóm gộp chung có phiếu
        # KHÁC không thỏa filter — đây là các phiếu có nguy cơ số hiển thị bị xấp xỉ sai.
        rep_domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('misa_invoice_master_picking_id', '=', False),
            ('misa_invoice_covered_picking_ids', '!=', False),
            ('misa_invoice_state', '=', 'invoiced'),
        ]
        cut_context_by_group = []
        # "Dùng chung mã sale khác" — ĐÃ THỬ 3 CÁCH tự suy diễn công thức cho gap_amount (không
        # tính, ~20,5tr, rồi 0đ) — 3 kết quả MÂU THUẪN nhau, không đủ tin. Cách ĐÁNG TIN cuối
        # cùng (đang dùng): KHÔNG suy diễn công thức nữa, đo THẲNG mức tăng/giảm của CHÍNH
        # get_misa_invoice_reconciliation_totals khi loại các phiếu của nhóm này ra khỏi domain
        # thật, so với outstanding_amount đang hiển thị của các phiếu đó — xem
        # _misa_invoice_group_gap_contribution. Đã kiểm chứng thực tế: tổng gap_amount qua TẤT
        # CẢ nhóm khớp CHÍNH XÁC 100% với chênh lệch thật đo được giữa thẻ và Excel/list (case
        # thật: 11810+12033+11323+08748 cộng đúng ra tổng lệch, không còn dư/thiếu).
        #
        # Một nhóm có THỂ vừa "dùng chung mã sale khác" VỪA có phiếu bị "cắt" bởi bộ lọc ngày
        # cùng lúc (case thật KBC/OUT/11810: có cả 11375/11518 ngoài ngày lẫn 11667 khác mã sale)
        # — không tách được gap_amount riêng cho từng lý do trong TRƯỜNG HỢP ĐÓ (chỉ 1 đề nghị
        # xuất HĐ dùng chung, không có "phần của lý do A" tách bạch khỏi "phần của lý do B") nên
        # xếp CẢ NHÓM vào ĐÚNG 1 mục "dùng chung mã sale khác" (ưu tiên hơn) và KHÔNG lặp lại ở
        # mục "cắt bởi bộ lọc ngày" nữa — tránh đếm gap_amount 2 lần cho cùng 1 nhóm.
        cross_saler_notes = []
        for rep in Picking.search(rep_domain):
            group = rep | rep.misa_invoice_covered_picking_ids
            qualifying = group.filtered(qualifies)
            cut_off = group - qualifying
            if not qualifying:
                continue
            other_saler_members_any = group.filtered(lambda m: not matches_saler(m))
            if other_saler_members_any:
                excel_contribution = sum(
                    self._misa_invoice_picking_to_row(m, today)['outstanding_amount'] for m in qualifying
                )
                gap_amount = self._misa_invoice_group_gap_contribution(
                    date_from, date_to, saler_code, qualifying.ids, excel_contribution,
                )
                cross_saler_notes.append({
                    'picking_names': qualifying.mapped('name'),
                    'order_names': sorted(set(qualifying.mapped('misa_invoice_sale_order_ids').mapped('name'))),
                    'representative_name': rep.name,
                    'other_saler_picking_names': other_saler_members_any.mapped('name'),
                    # Kèm tên đơn hàng của TỪNG phiếu mã sale khác (VD "KBC/OUT/11667
                    # (DH125524949234807)") — người quản lý cần biết ngay đơn nào để tự tra MISA,
                    # không phải tự đi tìm lại đơn hàng theo tên phiếu.
                    'other_saler_picking_labels': [
                        '%s (%s)' % (m.name, ', '.join(m.misa_invoice_sale_order_ids.mapped('name')) or '?')
                        for m in other_saler_members_any
                    ],
                    'other_saler_codes': sorted(set(other_saler_members_any.mapped('misa_invoice_saler_code'))),
                    # Dương: nhóm này làm Excel/list CAO hơn thẻ "Đối chiếu tổng". Âm: ngược lại.
                    'gap_amount': gap_amount,
                })
                continue
            if not cut_off:
                continue
            # cut_off ở đây CHẮC CHẮN toàn bộ ngoài khoảng ngày (không còn phiếu sale khác — nếu
            # có, nhóm đã bị bắt bởi nhánh cross-saler ở trên và continue rồi, không tới được
            # đây), nên out_of_date_members == cut_off luôn.
            ctx = {
                'out_of_date_picking_names': cut_off.mapped('name'),
                'out_of_date_dates': sorted(set(
                    fields.Date.to_string(m.date_done.date()) for m in cut_off if m.date_done
                )),
            }
            cut_context_by_group.append((qualifying, ctx))

        # Bước 2: với TỪNG NHÓM bị "cắt" (không dính cross-saler — đã xử lý riêng ở trên), tính
        # gap_amount THEO ĐÚNG PHƯƠNG PHÁP ĐÁNG TIN (_misa_invoice_group_gap_contribution, xem
        # giải thích ở đó) thay vì so displayed_outstanding với exact_outstanding theo TỪNG PHIẾU
        # riêng lẻ như trước — cách cũ không còn phản ánh đúng phần thẻ "Đối chiếu tổng" còn lệch
        # (từ khi _misa_invoice_picking_to_row đã tự sửa displayed_outstanding bằng dữ liệu exact
        # ở nơi khác, 2 số đó gần như luôn khớp nhau dù thẻ vẫn còn lệch thật). exact_outstanding
        # (đọc misa_invoice_exact_*, gọi API 1 lần/đơn nếu chưa có) vẫn giữ lại làm THÔNG TIN
        # tham khảo (số đúng theo đơn hàng), không dùng để tính gap_amount nữa.
        ensured_order_ids = set()
        cut_rows = []
        for qualifying, ctx in cut_context_by_group:
            exact_outstanding = 0.0
            is_estimated = False
            for picking in qualifying:
                for order in picking.misa_invoice_sale_order_ids:
                    if order.id not in ensured_order_ids:
                        if not order.misa_invoice_exact_checked_at:
                            try:
                                picking._misa_invoice_reconcile_order_coverage()
                            except Exception:
                                pass
                        ensured_order_ids.add(order.id)
                    order_shipped = order.misa_invoice_exact_shipped_amount or 0.0
                    order_invoiced = order.misa_invoice_exact_invoiced_amount or 0.0
                    order_outstanding = max(order_shipped - order_invoiced, 0.0)
                    order_pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.state == 'done')
                    if order_shipped <= 0 or len(order_pickings) <= 1 or order_outstanding <= MISA_INVOICE_AMOUNT_TOLERANCE:
                        # order_outstanding <= 0 (đơn đã đủ/thừa hóa đơn) — CHIA 0 CHO BAO NHIÊU
                        # PHIẾU CŨNG RA 0, không có gì mơ hồ để "ước lượng" dù đơn có giao nhiều
                        # đợt hay không (bài học thật: KBC/OUT/12308, đơn giao 2 đợt nhưng đã
                        # xuất đủ HĐ, trước đây vẫn bị gắn nhãn "(ước lượng)" gây hiểu lầm).
                        exact_outstanding += order_outstanding
                    else:
                        is_estimated = True
                        own_actual = picking.misa_invoice_net_actual_amount or 0.0
                        exact_outstanding += order_outstanding * own_actual / order_shipped

            excel_contribution = sum(
                self._misa_invoice_picking_to_row(p, today)['outstanding_amount'] for p in qualifying
            )
            gap_amount = self._misa_invoice_group_gap_contribution(
                date_from, date_to, saler_code, qualifying.ids, excel_contribution,
            )
            if abs(gap_amount) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                continue
            cut_rows.append({
                'picking_names': qualifying.mapped('name'),
                'out_of_date_picking_names': ctx.get('out_of_date_picking_names', []),
                'out_of_date_dates': ctx.get('out_of_date_dates', []),
                'exact_outstanding': exact_outstanding,
                'is_estimated': is_estimated,
                # Dương: nhóm này làm Excel/list CAO hơn thẻ "Đối chiếu tổng". Âm: ngược lại.
                'gap_amount': gap_amount,
            })
        cut_rows.sort(key=lambda r: -abs(r['gap_amount']))

        customs_summary = Picking._misa_invoice_customs_summary(date_from, date_to, saler_code)
        return {
            'cut_groups': cut_rows,
            'cut_groups_total_amount': sum(g['gap_amount'] for g in cut_rows),
            'cross_saler_notes': cross_saler_notes,
            'cross_saler_notes_total_amount': sum(n['gap_amount'] for n in cross_saler_notes),
            'customs_pending_amount': customs_summary['pending_amount'],
            'customs_pending_count': customs_summary['pending_count'],
        }
