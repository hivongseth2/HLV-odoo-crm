import base64
import io

import xlsxwriter

from odoo import api, fields, models

# Toàn bộ logic "Xuất Excel" của module (cả tab Phiếu xuất kho lẫn tab Đơn hàng, cả dashboard
# nội bộ lẫn trang public /misa_sale_status) được gom về đây — tách khỏi stock_picking.py
# (đã hơn 5000 dòng) để file đó đỡ phình thêm. Vẫn là _inherit = 'stock.picking' (không phải
# model riêng) nên mọi method ở đây gọi thẳng self.<method_khác> bình thường, kể cả các
# method còn định nghĩa bên stock_picking.py (get_misa_invoice_order_list,
# get_misa_invoice_public_list, _misa_invoice_picking_to_row, _misa_invoice_picking_line_items,
# _misa_invoice_validate_public_saler_code...) — Odoo gộp mọi _inherit cùng _name thành 1 class
# lúc chạy, thứ tự file trong models/__init__.py không ảnh hưởng gì tới việc gọi lẫn nhau.


class StockPickingMisaInvoiceExport(models.Model):
    _inherit = 'stock.picking'

    def _misa_invoice_export_workbook(
        self, sheet_name, headers, rows, money_cols=None, percent_cols=None, merge_col=None, note_col=None,
        summary_lines=None,
    ):
        """Dựng file .xlsx trong bộ nhớ (xlsxwriter) — dùng chung cho mọi nút "Xuất Excel"
        trên dashboard. money_cols: tập chỉ số cột (0-based) cần định dạng số tiền.
        percent_cols: tập chỉ số cột cần định dạng "%" (VD cột VAT — giá trị lưu ở dạng SỐ
        THƯỜNG như 8, 10, không phải 0.08, chỉ thêm ký hiệu % lúc hiển thị).
        merge_col: cột (0-based) cần MERGE các ô LIÊN TIẾP có cùng giá trị (VD gộp ô "Khách
        hàng" khi xuất chi tiết dòng hàng nhiều dòng cùng 1 khách đứng liền nhau) — rows PHẢI
        đã được sắp xếp theo đúng cột này trước khi gọi, nếu không sẽ chỉ gộp được các đoạn
        liên tiếp tình cờ trùng giá trị. note_col: cột (0-based) chứa ghi chú giải thích lệch
        (xem _misa_invoice_reconciliation_notes_by_picking) — CHỈ những Ô CÓ giá trị trong cột
        này được tô đỏ để dễ nhận ra, các ô rỗng vẫn viền/canh lề bình thường.

        summary_lines: list [{'text': str, 'bold': bool}] ghi THÊM ở CUỐI sheet (sau 1 dòng
        trống), MERGE ngang hết bề rộng bảng, tô ĐỎ toàn bộ — dùng cho phần giải thích "vì sao
        Còn lại chưa xuất HĐ khác tổng cộng dồn" (xem
        _misa_invoice_gap_explain_summary_lines), để người xuất Excel hiểu ngay lý do lệch mà
        không cần mở modal trên dashboard."""
        money_cols = money_cols or set()
        percent_cols = percent_cols or set()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(sheet_name[:31])

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#2a78d6', 'font_color': '#ffffff',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_money = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0', 'align': 'right'})
        fmt_percent = workbook.add_format({
            'border': 1, 'valign': 'vcenter', 'num_format': '0.##"%"', 'align': 'right',
        })
        fmt_note = workbook.add_format({
            'border': 1, 'valign': 'vcenter', 'bg_color': '#fde2e2', 'font_color': '#a3241f',
        })
        fmt_summary_title = workbook.add_format({
            'bold': True, 'font_color': '#ffffff', 'bg_color': '#a3241f', 'font_size': 12, 'valign': 'vcenter',
        })
        fmt_summary_line = workbook.add_format({
            'font_color': '#a3241f', 'text_wrap': True, 'valign': 'top',
        })

        worksheet.set_row(0, 22)
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, fmt_header)
            worksheet.set_column(col, col, max(14, len(header) + 4))
        if note_col is not None:
            worksheet.set_column(note_col, note_col, 60)

        for row_idx, row in enumerate(rows, start=1):
            for col, value in enumerate(row):
                if col == note_col and value:
                    fmt = fmt_note
                else:
                    fmt = fmt_money if col in money_cols else (fmt_percent if col in percent_cols else fmt_cell)
                worksheet.write(row_idx, col, value, fmt)

        if merge_col is not None and rows:
            n = len(rows)
            group_start = 0
            for i in range(1, n + 1):
                if i == n or rows[i][merge_col] != rows[group_start][merge_col]:
                    excel_start, excel_end = group_start + 1, i
                    if excel_end > excel_start:
                        worksheet.merge_range(
                            excel_start, merge_col, excel_end, merge_col,
                            rows[group_start][merge_col], fmt_cell,
                        )
                    group_start = i

        if summary_lines:
            last_col = max(len(headers) - 1, 0)
            row_idx = len(rows) + 2
            for line in summary_lines:
                fmt = fmt_summary_title if line.get('bold') else fmt_summary_line
                if last_col > 0:
                    worksheet.merge_range(row_idx, 0, row_idx, last_col, line['text'], fmt)
                else:
                    worksheet.write(row_idx, 0, line['text'], fmt)
                worksheet.set_row(row_idx, 20 if line.get('bold') else 34)
                row_idx += 1

        workbook.close()
        output.seek(0)
        return output.read()

    def _misa_invoice_create_export_attachment(self, filename, content):
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': 0,
        })
        return attachment.id

    def _misa_invoice_reconciliation_notes_by_picking(self, explain):
        """Map {tên phiếu: ghi chú} cho các phiếu bị ảnh hưởng bởi phần lệch đã biết giữa tổng
        cộng dồn theo phiếu và thẻ "Đối chiếu tổng" (nhóm bị cắt bởi bộ lọc ngày/mã sale — xem
        get_misa_invoice_reconciliation_gap_explain) — gắn thẳng vào cột "Ghi chú" NGAY TRÊN
        dòng phiếu đó khi xuất Excel, thay vì tạo dòng tổng hợp riêng (dễ hiểu lầm là 1 phiếu
        thật, số âm khó hiểu). Hóa đơn hải quan chưa khớp PXK không gắn được vào phiếu nào nên
        không có trong map này. `explain` = kết quả get_misa_invoice_reconciliation_gap_explain
        đã tính SẴN ở nơi gọi (dùng chung với _misa_invoice_gap_explain_summary_lines, tránh gọi
        2 lần cho cùng 1 lần xuất Excel)."""
        notes = {}
        for g in explain['cut_groups']:
            text = 'Dùng chung đề nghị xuất HĐ với %s (ngày %s, NGOÀI khoảng đang lọc) — số đúng theo đơn hàng: %s%s — chênh lệch góp vào "Đối chiếu tổng": %s' % (
                ', '.join(g['out_of_date_picking_names']), ', '.join(g['out_of_date_dates']),
                '{:,.0f}'.format(g['exact_outstanding']),
                ' (ƯỚC LƯỢNG — đơn giao nhiều đợt)' if g['is_estimated'] else '',
                '{:,.0f}'.format(g['gap_amount']),
            )
            for name in g['picking_names']:
                notes[name] = (notes[name] + '; ' + text) if name in notes else text
        for n in explain.get('cross_saler_notes', []):
            text = 'Dùng chung đề nghị xuất HĐ (%s) với phiếu %s thuộc mã sale %s — chênh lệch góp vào "Đối chiếu tổng": %s' % (
                n['representative_name'],
                ', '.join(n.get('other_saler_picking_labels') or n['other_saler_picking_names']),
                ', '.join(n['other_saler_codes']),
                '{:,.0f}'.format(n['gap_amount']),
            )
            for name in n['picking_names']:
                notes[name] = (notes[name] + '; ' + text) if name in notes else text
        return notes

    def _misa_invoice_gap_explain_summary_lines(self, explain):
        """Dựng khối giải thích "vì sao Còn lại chưa xuất HĐ khác tổng cộng dồn theo phiếu/đơn"
        (tô đỏ) để ghi thẳng vào CUỐI file Excel xuất ra — cùng nội dung với modal "Xem chi tiết
        vì sao lệch" trên dashboard, để người xuất Excel hiểu ngay lý do lệch mà không cần mở
        dashboard. `explain` = kết quả get_misa_invoice_reconciliation_gap_explain đã tính SẴN ở
        nơi gọi. Trả về [] nếu không có nguyên nhân nào (khớp đủ, không cần ghi gì thêm)."""
        total = (
            (explain.get('customs_pending_amount') or 0.0)
            + (explain.get('cut_groups_total_amount') or 0.0)
            + (explain.get('cross_saler_notes_total_amount') or 0.0)
        )
        if abs(total) <= 1.0 and not explain.get('cut_groups') and not explain.get('cross_saler_notes'):
            return []
        fmt = lambda v: '{:,.0f}'.format(v).replace(',', '.')
        lines = [{
            'text': 'VÌ SAO "CÒN LẠI CHƯA XUẤT HĐ" (Đối chiếu tổng) KHÁC TỔNG "TIỀN CHƯA XUẤT HĐ" CỘNG DỒN Ở TRÊN — TỔNG CHÊNH LỆCH: %s đ' % fmt(total),
            'bold': True,
        }]
        if explain.get('customs_pending_amount'):
            lines.append({'text': (
                'Hóa đơn hải quan chưa khớp phiếu xuất kho: %s hóa đơn, tổng %s đ — không gắn với phiếu nào nên '
                'không xuất hiện ở dòng nào phía trên, nhưng vẫn được trừ vào "Còn lại chưa xuất HĐ" trên Đối chiếu tổng.'
            ) % (explain['customs_pending_count'], fmt(explain['customs_pending_amount']))})
        for g in explain.get('cut_groups', []):
            lines.append({'text': (
                'Phiếu %s dùng chung đề nghị xuất HĐ với %s (ngày %s, NGOÀI khoảng đang lọc) — số đúng theo đơn hàng: %s đ%s '
                '— chênh lệch góp vào Đối chiếu tổng: %s đ.'
            ) % (
                ', '.join(g['picking_names']), ', '.join(g['out_of_date_picking_names']),
                ', '.join(g['out_of_date_dates']), fmt(g['exact_outstanding']),
                ' (ước lượng — đơn giao nhiều đợt)' if g['is_estimated'] else '',
                fmt(g['gap_amount']),
            )})
        for n in explain.get('cross_saler_notes', []):
            lines.append({'text': (
                'Phiếu %s dùng chung đề nghị xuất HĐ (%s) với phiếu %s thuộc mã sale %s — chênh lệch góp vào '
                'Đối chiếu tổng: %s đ.'
            ) % (
                ', '.join(n['picking_names']), n['representative_name'],
                ', '.join(n.get('other_saler_picking_labels') or n['other_saler_picking_names']),
                ', '.join(n['other_saler_codes']), fmt(n['gap_amount']),
            )})
        return lines

    @api.model
    def export_misa_invoice_picking_list_excel(
        self, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Xuất Excel TOÀN BỘ phiếu khớp filter hiện tại của tab 'Phiếu xuất kho' (không giới
        hạn theo trang đang xem) — trả về id ir.attachment, JS tự điều hướng tới
        /web/content/<id>?download=true để tải về."""
        Picking = self.sudo()
        domain = self._misa_invoice_picking_list_domain(
            search, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
        )
        pickings = Picking.search(domain, order='date_done desc')
        today = fields.Date.context_today(self)
        explain = self.get_misa_invoice_reconciliation_gap_explain(
            date_from=date_from, date_to=date_to, saler_code=saler_code,
        )
        notes = self._misa_invoice_reconciliation_notes_by_picking(explain)
        rows = [
            [
                row['name'], row['partner_name'], row['sale_order_name'], row['date_done'],
                row['actual_amount'], row['invoice_amount'], row['outstanding_amount'], row['state_label'],
                notes.get(row['name'], ''),
            ]
            for row in (self._misa_invoice_picking_to_row(picking, today) for picking in pickings)
        ]
        headers = [
            'Phiếu', 'Khách hàng', 'Đơn bán', 'Ngày xuất kho',
            'Tiền thực xuất', 'Tiền đã xuất HĐ', 'Tiền chưa xuất HĐ', 'Trạng thái', 'Ghi chú',
        ]
        content = self._misa_invoice_export_workbook(
            'Phiếu xuất kho', headers, rows, money_cols={4, 5, 6}, note_col=8,
            summary_lines=self._misa_invoice_gap_explain_summary_lines(explain),
        )
        return self._misa_invoice_create_export_attachment(
            'phieu_xuat_kho_%s.xlsx' % fields.Date.to_string(today), content
        )

    @api.model
    def export_misa_invoice_public_list_excel(
        self, saler_code, search=False, state=False, states=None, date_from=False, date_to=False,
    ):
        """Xuất Excel TOÀN BỘ phiếu khớp filter hiện tại của tab 'Phiếu xuất kho' trên
        /misa_sale_status — tái dùng NGUYÊN get_misa_invoice_public_list (kể cả multi-select
        states) để đảm bảo xuất ĐÚNG y hệt danh sách đang xem, không xây domain riêng lần 2."""
        result = self.get_misa_invoice_public_list(
            saler_code=saler_code, search=search, state=state, states=states,
            date_from=date_from, date_to=date_to, limit=10000, offset=0,
        )
        explain = self.get_misa_invoice_reconciliation_gap_explain(
            date_from=date_from, date_to=date_to, saler_code=saler_code,
        )
        notes = self._misa_invoice_reconciliation_notes_by_picking(explain)
        rows = [
            [
                row['name'], row['partner_name'], row['sale_order_name'], row['date_done'],
                row['actual_amount'], row['invoice_amount'], row['outstanding_amount'], row['state_label'],
                notes.get(row['name'], ''),
            ]
            for row in result['rows']
        ]
        headers = [
            'Phiếu', 'Khách hàng', 'Đơn bán', 'Ngày xuất kho',
            'Tiền thực xuất', 'Tiền đã xuất HĐ', 'Tiền chưa xuất HĐ', 'Trạng thái', 'Ghi chú',
        ]
        content = self._misa_invoice_export_workbook(
            'Phiếu xuất kho', headers, rows, money_cols={4, 5, 6}, note_col=8,
            summary_lines=self._misa_invoice_gap_explain_summary_lines(explain),
        )
        return self._misa_invoice_create_export_attachment(
            'phieu_xuat_kho_%s.xlsx' % fields.Date.to_string(fields.Date.context_today(self)), content
        )

    _MISA_INVOICE_DETAIL_LINES_HEADERS = [
        'Khách hàng', 'Mã đơn hàng', 'Phiếu xuất kho', 'Đề nghị (refno)', 'Số hóa đơn',
        'Tên hàng', 'Mã hàng', 'Số lượng',
        'Đơn giá trước thuế', 'Thành tiền trước thuế', 'VAT (%)', 'Thuế', 'Đơn giá sau thuế', 'Tổng tiền',
    ]

    def _misa_invoice_detail_line_row(self, partner_name, order_name, picking, line):
        """1 dòng cho export "chi tiết dòng hàng" — dùng chung cho CẢ tab 'Đơn hàng' (partner/
        order_name lấy theo NGỮ CẢNH đơn đang duyệt, vì 1 phiếu gộp có thể thuộc nhiều đơn) lẫn
        tab 'Phiếu xuất kho' (partner/order_name lấy thẳng từ phiếu) — tránh lặp code 2 nơi mà
        vẫn giữ đúng ngữ cảnh gọi, không gộp nhầm khi 1 phiếu thuộc nhiều đơn."""
        effective = picking.misa_invoice_master_picking_id or picking
        pre_tax_amount = line['value']
        tax_amount = line['tax_value']
        # Suy ra % VAT từ chính 2 số tiền đã tính sẵn (không đọc line.tax_id) — đúng với BẤT KỲ
        # cách cấu hình thuế nào trên dòng đơn bán (kể cả thuế gộp/nhiều thuế), không phụ thuộc
        # phải có ĐÚNG 1 thuế dạng percent mới suy ra đúng.
        vat_rate_pct = round(tax_amount / pre_tax_amount * 100, 2) if pre_tax_amount else 0.0
        return [
            partner_name, order_name, picking.name,
            effective.misa_invoice_request_refno or '', effective.misa_invoice_no or '',
            line['product_name'], line['default_code'] or '', line['qty'],
            line['pre_tax_unit_price'], pre_tax_amount, vat_rate_pct, tax_amount,
            line['post_tax_unit_price'], pre_tax_amount + tax_amount,
        ]

    def _misa_invoice_export_detail_lines_attachment(self, filename_prefix, detail_rows):
        """Sắp xếp theo Khách hàng (để merge_col=0 gộp đúng đoạn liên tiếp) rồi dựng file —
        bước cuối dùng chung cho cả 2 nút "Xuất dòng chi tiết" (Đơn hàng/Phiếu xuất kho)."""
        detail_rows.sort(key=lambda r: (r[0], r[1], r[2]))
        content = self._misa_invoice_export_workbook(
            'Chi tiết dòng hàng', self._MISA_INVOICE_DETAIL_LINES_HEADERS, detail_rows,
            money_cols={8, 9, 11, 12, 13}, percent_cols={10}, merge_col=0,
        )
        return self._misa_invoice_create_export_attachment(
            '%s_%s.xlsx' % (filename_prefix, fields.Date.to_string(fields.Date.context_today(self))), content
        )

    @api.model
    def _misa_invoice_dedupe_order_rows(self, rows):
        """Khử đếm-trùng invoice_amount/outstanding_amount khi 1 phiếu ĐẠI DIỆN (đề nghị gộp
        chung) được NHIỀU đơn hàng khác nhau trong CHÍNH danh sách `rows` này cùng tham chiếu
        — xem comment gốc rễ vấn đề trong _misa_invoice_order_row (stock_picking.py): mỗi đơn
        tự cộng ĐỦ effective_amount của đại diện, chỉ chặn trần theo amount_total CỦA RIÊNG NÓ,
        nên tổng cộng dồn qua nhiều đơn > số tiền hóa đơn THẬT chỉ có 1 lần (case thật đã đo
        được: 1 đại diện liên quan 12 đơn, KBC/OUT/09217).

        Cách xử lý: với mỗi đại diện bị > 1 đơn (trong CHÍNH rows này) tham chiếu, CHIA LẠI
        effective_amount của nó theo tỷ lệ amount_total giữa các đơn cùng tham chiếu (đơn giá
        trị hợp đồng lớn hơn được chia phần lớn hơn) — thay vì mỗi đơn tự nhận ĐỦ. Đây là ước
        lượng hợp lý, KHÔNG phải con số tuyệt đối chính xác cho TỪNG đơn riêng lẻ (muốn tuyệt
        đối phải tra chi tiết dòng hàng qua API sống theo order_code — xem
        _misa_invoice_compute_order_coverage_detail — quá tốn để chạy hàng loạt lúc xuất Excel)
        — nhưng đảm bảo TỔNG cộng dồn qua các đơn trong file xuất ra khớp đúng số tiền hóa đơn
        thật (không còn thừa do đếm trùng), giải quyết đúng vấn đề "cộng Excel ra số khác đối
        chiếu tổng".

        Giới hạn đã biết: chỉ khử trùng được phần chia sẻ giữa các đơn CÙNG có mặt trong `rows`
        — nếu đại diện còn được đơn NGOÀI phạm vi export hiện tại (VD saler_code khác) dùng
        chung, phần đó không có dữ liệu để chia nên không tính vào, tổng có thể vẫn còn lệch
        (nhỏ) so với "Đối chiếu tổng" toàn hệ thống.

        Đơn đã có `row['exact']=True` (invoice_amount/outstanding_amount đã CHÍNH XÁC tuyệt đối
        — xem misa_invoice_exact_* trên sale.order, _misa_invoice_order_row) bị LOẠI HOÀN TOÀN
        khỏi hàm này — không tham gia phát hiện đại diện dùng chung, không bị tính lại — để
        không lấy số ước lượng đè lên số đã đúng sẵn."""
        approx_rows = [row for row in rows if not row.get('exact')]
        rep_orders = {}
        for row in approx_rows:
            seen = set()
            for p in row['pickings']:
                if p['state'] != 'invoiced':
                    continue
                rep_id = p['master_picking_id'] or p['id']
                if rep_id in seen:
                    continue
                seen.add(rep_id)
                bucket = rep_orders.setdefault(rep_id, {'amount': p['invoice_amount'] or 0.0, 'order_ids': set()})
                bucket['order_ids'].add(row['id'])

        shared_reps = {rep_id: data for rep_id, data in rep_orders.items() if len(data['order_ids']) > 1}
        if not shared_reps:
            return rows

        amount_total_by_order = {row['id']: row['amount_total'] for row in approx_rows}
        alloc = {}
        for rep_id, data in shared_reps.items():
            total_amount_total = sum(amount_total_by_order.get(oid, 0.0) for oid in data['order_ids'])
            for oid in data['order_ids']:
                share = (
                    amount_total_by_order.get(oid, 0.0) / total_amount_total if total_amount_total > 0
                    else 1.0 / len(data['order_ids'])
                )
                alloc[(oid, rep_id)] = data['amount'] * share

        for row in approx_rows:
            seen = set()
            raw_sum = 0.0
            for p in row['pickings']:
                if p['state'] != 'invoiced':
                    continue
                rep_id = p['master_picking_id'] or p['id']
                if rep_id in seen:
                    continue
                seen.add(rep_id)
                raw_sum += alloc[(row['id'], rep_id)] if rep_id in shared_reps else (p['invoice_amount'] or 0.0)
            corrected_invoiced = min(raw_sum, row['amount_total'])
            row['invoice_amount'] = corrected_invoiced
            row['outstanding_amount'] = max(row['amount_total'] - corrected_invoiced, 0.0)
        return rows

    def export_misa_invoice_order_list_excel(
        self, search=False, state=False, saler_code=False, multi_request=False, partial_coverage_only=False,
        mismatch_only=False, states=None, date_from=False, date_to=False,
        invoice_date_from=False, invoice_date_to=False,
    ):
        """Xuất Excel TOÀN BỘ đơn hàng khớp filter hiện tại của tab 'Đơn hàng' — trả về id
        ir.attachment, JS tự điều hướng tới /web/content/<id>?download=true để tải về.
        Giới hạn 10.000 dòng (đủ dư cho quy mô dữ liệu hiện tại) để tránh xuất vô hạn nếu
        filter quá rộng."""
        result = self.get_misa_invoice_order_list(
            limit=10000, offset=0, search=search, state=state, saler_code=saler_code, multi_request=multi_request,
            partial_coverage_only=partial_coverage_only, mismatch_only=mismatch_only, states=states,
            date_from=date_from, date_to=date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        )
        rows_data = self._misa_invoice_dedupe_order_rows(result['rows'])
        rows = [
            [
                row['name'], row['partner_name'], row['picking_names'],
                row['amount_total'], row['invoice_amount'], row['outstanding_amount'], row['state_label'],
            ]
            for row in rows_data
        ]
        headers = [
            'Đơn hàng', 'Khách hàng', 'Phiếu xuất kho',
            'Tổng tiền đơn', 'Tiền đã xuất HĐ', 'Tiền chưa xuất HĐ', 'Trạng thái',
        ]
        content = self._misa_invoice_export_workbook('Đơn hàng', headers, rows, money_cols={3, 4, 5})
        return self._misa_invoice_create_export_attachment(
            'don_hang_%s.xlsx' % fields.Date.to_string(fields.Date.context_today(self)), content
        )

    @api.model
    def export_misa_invoice_order_detail_lines_excel(
        self, search=False, state=False, saler_code=False, multi_request=False, partial_coverage_only=False,
        mismatch_only=False, states=None, date_from=False, date_to=False,
        invoice_date_from=False, invoice_date_to=False,
    ):
        """Xuất Excel CHI TIẾT TỪNG DÒNG HÀNG (mỗi dòng = 1 sản phẩm đã xuất kho) của TOÀN BỘ
        đơn khớp filter hiện tại của tab 'Đơn hàng' — merge ô Khách hàng khi nhiều dòng liền
        nhau cùng 1 khách, để dễ đối chiếu/gửi khách hơn là 1 bảng phẳng lặp lại tên khách ở
        mọi dòng. Đơn giá/thuế lấy từ CHÍNH dòng đơn bán Odoo (prorate theo SL đã xuất kho,
        xem _misa_invoice_picking_line_items) — không gọi thêm API MISA nào (số hóa đơn/refno
        chỉ là 2 cột thông tin lấy sẵn trên phiếu, không phải nguồn xuất dòng hàng)."""
        result = self.get_misa_invoice_order_list(
            limit=10000, offset=0, search=search, state=state, saler_code=saler_code, multi_request=multi_request,
            partial_coverage_only=partial_coverage_only, mismatch_only=mismatch_only, states=states,
            date_from=date_from, date_to=date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        )
        Picking = self.sudo()
        detail_rows = []
        for row in result['rows']:
            for p in row['pickings']:
                picking = Picking.browse(p['id'])
                for line in self._misa_invoice_picking_line_items(picking):
                    if line.get('is_component'):
                        # Giá trị dòng con combo/kit đã gộp hết vào dòng combo đại diện
                        # (value=0 ở đây) — xuất thêm sẽ ra dòng 0đ gây rối, bỏ qua như mọi chỗ
                        # khác đang tổng hợp giá trị (_misa_invoice_group_odoo_lines).
                        continue
                    detail_rows.append(
                        self._misa_invoice_detail_line_row(row['partner_name'], row['name'], picking, line)
                    )
        return self._misa_invoice_export_detail_lines_attachment('chi_tiet_dong_hang', detail_rows)

    @api.model
    def export_misa_invoice_public_order_list_excel(
        self, saler_code, search=False, state=False, partial_coverage_only=False, mismatch_only=False,
        states=None, date_from=False, date_to=False,
    ):
        """Như export_misa_invoice_order_list_excel nhưng scope theo saler_code cho trang
        public /misa_sale_status (nút "Xuất đơn hàng")."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().export_misa_invoice_order_list_excel(
            search=search, state=state, saler_code=code, mismatch_only=mismatch_only, states=states,
            partial_coverage_only=partial_coverage_only, date_from=date_from, date_to=date_to,
        )

    @api.model
    def export_misa_invoice_public_order_detail_lines_excel(
        self, saler_code, search=False, state=False, partial_coverage_only=False, mismatch_only=False,
        states=None, date_from=False, date_to=False,
    ):
        """Như export_misa_invoice_order_detail_lines_excel nhưng scope theo saler_code cho
        trang public /misa_sale_status (nút "Xuất dòng chi tiết")."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().export_misa_invoice_order_detail_lines_excel(
            search=search, state=state, saler_code=code, mismatch_only=mismatch_only, states=states,
            partial_coverage_only=partial_coverage_only, date_from=date_from, date_to=date_to,
        )

    @api.model
    def export_misa_invoice_public_picking_detail_lines_excel(
        self, saler_code, search=False, state=False, states=None, date_from=False, date_to=False,
    ):
        """Xuất Excel CHI TIẾT TỪNG DÒNG HÀNG cho tab 'Phiếu xuất kho' trên /misa_sale_status —
        đúng cặp với export_misa_invoice_public_list_excel (danh sách phiếu), giống hệt cách
        tab 'Đơn hàng' có 2 nút "Xuất đơn hàng"/"Xuất dòng chi tiết". Nguồn phiếu lấy từ
        get_misa_invoice_public_list (limit cao) để luôn khớp đúng bộ filter đang xem."""
        result = self.get_misa_invoice_public_list(
            saler_code=saler_code, search=search, state=state, states=states,
            date_from=date_from, date_to=date_to, limit=10000, offset=0,
        )
        Picking = self.sudo()
        detail_rows = []
        for row in result['rows']:
            picking = Picking.browse(row['id'])
            for line in self._misa_invoice_picking_line_items(picking):
                if line.get('is_component'):
                    continue
                detail_rows.append(
                    self._misa_invoice_detail_line_row(row['partner_name'], row['sale_order_name'], picking, line)
                )
        return self._misa_invoice_export_detail_lines_attachment('chi_tiet_dong_hang', detail_rows)
