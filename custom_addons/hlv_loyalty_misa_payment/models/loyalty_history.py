# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

from ..services.loyalty_misa_payment_utils import (
    PAID_STATE_SELECTION,
    index_voucher_lines,
    match_loyalty_line,
    paid_state_of,
    qty_shortfall,
    split_vouchers_by_invoice_no,
    summarize_line_states,
)

_logger = logging.getLogger(__name__)

# Số giao dịch điểm quét mỗi lần cron chạy. Để ở ir.config_parameter chứ không cứng trong code
# vì con số hợp lý đổi theo lượng dữ liệu: lúc mới bật cần một đợt quét bù rất lớn cho vài nghìn
# bản ghi cũ, sau đó mỗi đêm chỉ còn vài bản ghi mới phát sinh — không thể sửa code mỗi lần.
MISA_PAYMENT_SCAN_BATCH_PARAM = 'hlv_loyalty_misa_payment.scan_batch_size'
MISA_PAYMENT_SCAN_BATCH_DEFAULT = 500


class HlvLoyaltyHistoryMisaPayment(models.Model):
    _inherit = 'hlv.loyalty.history'

    # 3 field dưới đây là ẢNH CHỤP kết quả lần tra MISA gần nhất, KHÔNG phải nguồn sự thật —
    # nguồn sự thật luôn là MISA. Lưu lại để (a) list Lịch sử điểm lọc/xem được ngay mà không
    # phải gọi API cho từng dòng, (b) cron biết bản ghi nào đã xong để thôi tra lại. Mọi lần
    # tra (cron lẫn mở form/bấm "Tra lại") đều ghi đè 3 field này — xem _misa_payment_store().
    misa_invoice_no = fields.Char(string='Số hóa đơn MISA', copy=False, index=True, readonly=True)
    misa_paid_state = fields.Selection(
        PAID_STATE_SELECTION, string='Thu tiền MISA', copy=False, index=True, readonly=True,
    )
    misa_paid_checked_at = fields.Datetime(string='Lần tra MISA gần nhất', copy=False, readonly=True)

    @api.model
    def get_misa_payment_status(self, history_id, force_refresh=False):
        """Tình trạng THU TIỀN trên MISA của giao dịch điểm này, tra sống tại thời điểm gọi.

        Gọi từ widget trên form Lịch sử điểm (xem static/src/js/loyalty_misa_payment.js) ngay
        khi mở form, để người xét duyệt điểm biết đơn đã thu tiền chưa trước khi bấm xác nhận,
        và từ cron quét hằng đêm (_cron_scan_misa_payment).

        force_refresh=True: bỏ qua số hóa đơn đã lưu sẵn trên phiếu kho, tra lại từ đầu bằng
        API MISA (nút "Tra lại").

        Kết quả luôn được lưu lại vào misa_invoice_no/misa_paid_state (xem _misa_payment_store)
        — tra sống mà MISA đã đổi thì bản lưu đổi theo ngay, không chờ cron.

        Trả dict luôn có 'available' (bool) và 'raw' (dữ liệu thô để người dùng tự đối chiếu);
        lỗi gọi MISA trả 'error' thay vì raise, để form không vỡ chỉ vì MISA đang trục trặc.
        """
        history = self.browse(history_id).exists()
        if not history:
            return {'available': False, 'message': 'Không tìm thấy giao dịch điểm.'}

        # sudo: người duyệt điểm không nhất thiết có quyền đọc phiếu kho/đơn bán của chi nhánh
        # khác, nhưng vẫn cần thấy tình trạng thu tiền để quyết định xác nhận điểm.
        picking = history.picking_id.sudo()
        if not picking:
            return {
                'available': False,
                'message': 'Giao dịch điểm này không gắn với phiếu kho nào để tra hóa đơn MISA.',
            }

        try:
            report = self._misa_payment_report(history, picking, force_refresh)
        except Exception as error:
            _logger.exception(
                "❌ [LOYALTY MISA PAID] Lỗi tra tình trạng thu tiền cho giao dịch điểm %s (phiếu %s)",
                history.id, picking.name,
            )
            report = {
                'available': True,
                'error': str(error),
                'picking_name': picking.name,
                'order_name': history.sale_order_id.sudo().name or '',
            }

        history._misa_payment_store(report)
        return report

    def _misa_payment_store(self, report):
        """Lưu kết quả tra MISA lên chính bản ghi điểm.

        Lần tra LỖI chỉ cập nhật mốc thời gian, KHÔNG đụng tới số hóa đơn/trạng thái đã lưu:
        ghi đè lúc đó sẽ xóa mất kết quả đúng của lần trước chỉ vì MISA đang trục trặc. Nhưng
        mốc thời gian thì luôn phải ghi (kể cả khi lỗi, kể cả khi số liệu không đổi) — cron dựa
        vào nó để xoay vòng, không ghi thì bản ghi hỏng đó chiếm chỗ đầu hàng mãi mãi và phần
        còn lại không bao giờ tới lượt.
        """
        self.ensure_one()
        vals = {'misa_paid_checked_at': fields.Datetime.now()}
        if not report.get('error'):
            vals['misa_invoice_no'] = report.get('invoice_no') or False
            vals['misa_paid_state'] = report.get('summary_state') or False
        self.sudo().write(vals)

    @api.model
    def _misa_payment_scan_domain(self):
        """Giao dịch điểm CÒN cần tra MISA.

        Bỏ qua hẳn bản ghi đã có số hóa đơn VÀ đã thu tiền: đó là trạng thái cuối, MISA không
        đổi ngược lại được, tra thêm chỉ tốn lệnh gọi. Cũng bỏ qua điểm đã hủy và các loại giao
        dịch không sinh ra từ việc bán hàng (đổi thưởng, chuyển điểm, điều chỉnh tay) — những
        cái đó không có hóa đơn để tra.
        """
        return [
            ('picking_id', '!=', False),
            ('transaction_type', '=', 'earn'),
            ('state', '!=', 'cancelled'),
            '|', ('misa_invoice_no', '=', False), ('misa_paid_state', '!=', 'paid'),
        ]

    @api.model
    def _misa_payment_scan_batch_size(self):
        """Số bản ghi quét mỗi lượt cron, đọc từ ir.config_parameter (xem hằng số cùng tên).

        Giá trị rác hoặc <= 0 trong tham số hệ thống thì quay về mặc định thay vì làm hỏng cron.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(MISA_PAYMENT_SCAN_BATCH_PARAM)
        try:
            size = int(raw)
        except (TypeError, ValueError):
            return MISA_PAYMENT_SCAN_BATCH_DEFAULT
        return size if size > 0 else MISA_PAYMENT_SCAN_BATCH_DEFAULT

    @api.model
    def _cron_scan_misa_payment(self, limit=None):
        """Quét tình trạng thu tiền cho các giao dịch điểm chưa xong (chạy 1 lần/ngày).

        Ưu tiên bản ghi CHƯA tra lần nào, còn dư mới lấy tiếp bản ghi tra lâu nhất — để bản ghi
        mới phát sinh luôn có số liệu ngay đêm đầu tiên thay vì xếp hàng sau vài nghìn bản ghi
        cũ. Lỗi của 1 bản ghi (MISA trả lỗi, phiếu dữ liệu lạ) không được làm hỏng cả lượt quét
        nên bắt riêng từng bản ghi.
        """
        limit = limit or self._misa_payment_scan_batch_size()
        domain = self._misa_payment_scan_domain()
        records = self.search(domain + [('misa_paid_checked_at', '=', False)], limit=limit)
        if len(records) < limit:
            records |= self.search(
                domain + [('misa_paid_checked_at', '!=', False)],
                order='misa_paid_checked_at asc',
                limit=limit - len(records),
            )

        # 1 phiếu kho thường sinh 2 bản ghi điểm (điểm xếp hạng + điểm đổi thưởng) và đôi khi
        # nhiều hơn — tra MISA riêng cho từng bản ghi là gọi lại y hệt cùng một bộ API cho cùng
        # một phiếu. Gom theo phiếu, tra 1 lần rồi chép kết quả sang các bản ghi còn lại: cắt
        # được khoảng một nửa số lệnh gọi mà kết quả không đổi (báo cáo vốn chỉ phụ thuộc phiếu).
        groups = {}
        for record in records:
            groups.setdefault(record.picking_id.id, self.browse())
            groups[record.picking_id.id] |= record

        checked = 0
        for group in groups.values():
            leader = group[0]
            try:
                # get_misa_payment_status tự bắt lỗi MISA và trả về 'error' thay vì raise, nên
                # phải đọc kết quả mới biết phiếu này thật sự tra được hay không.
                report = leader.get_misa_payment_status(leader.id)
            except Exception:
                _logger.exception(
                    "❌ [LOYALTY MISA PAID CRON] Lỗi tra giao dịch điểm %s (phiếu %s)",
                    leader.id, leader.picking_id.display_name,
                )
                continue
            for sibling in group - leader:
                sibling._misa_payment_store(report)
            if not report.get('error'):
                checked += len(group)

        # Đếm lại bằng chính domain quét (sau khi đã ghi kết quả) thay vì trừ nhẩm: bản ghi vừa
        # tra xong nhưng CHƯA thu tiền vẫn còn nằm trong hàng đợi, trừ đi là báo thiếu việc.
        _logger.info(
            "✅ [LOYALTY MISA PAID CRON] Đã tra %s/%s giao dịch điểm (%s phiếu kho), "
            "còn %s bản ghi trong hàng đợi.",
            checked, len(records), len(groups), self.search_count(domain),
        )

    def _misa_payment_report(self, history, picking, force_refresh):
        """Ráp báo cáo hoàn chỉnh: số hóa đơn → chứng từ MISA → đối chiếu từng dòng tích điểm."""
        invoice_no, invoice_source, lookup_raw = self._misa_payment_resolve_invoice_no(
            picking, force_refresh,
        )
        report = {
            'available': True,
            'picking_name': picking.name,
            'order_name': history.sale_order_id.sudo().name or '',
            'invoice_no': invoice_no,
            'invoice_source': invoice_source,
            'vouchers': [],
            'other_vouchers': [],
            'lines': [],
            'raw': {'invoice_lookup': lookup_raw},
        }
        if not invoice_no:
            report['summary_state'] = 'no_invoice'
            report['summary_label'] = (
                'Chưa tìm được số hóa đơn MISA cho phiếu %s — nhiều khả năng đơn chưa được xuất '
                'hóa đơn.' % picking.name
            )
            return report

        vouchers, others, voucher_raw = self._misa_payment_fetch_vouchers(invoice_no)
        report['vouchers'] = vouchers
        report['other_vouchers'] = others
        report['raw'].update(voucher_raw)

        loyalty_lines = self._misa_payment_loyalty_lines(picking, report['order_name'])
        report['lines'] = self._misa_payment_build_lines(loyalty_lines, vouchers)

        state, label = summarize_line_states([line['paid_state'] for line in report['lines']])
        if not report['lines'] and vouchers:
            # Phiếu không có dòng giao nào (VD điểm điều chỉnh tay gắn kèm phiếu) — vẫn kết luận
            # được ở mức chứng từ, không bắt người dùng tự suy ra từ bảng rỗng.
            state, label = summarize_line_states([voucher['paid_state'] for voucher in vouchers])
        report['summary_state'] = state
        report['summary_label'] = label
        return report

    def _misa_payment_resolve_invoice_no(self, picking, force_refresh):
        """Số hóa đơn MISA của phiếu kho này, kèm nguồn lấy được và dữ liệu thô từng bước tra.

        Ưu tiên misa_invoice_no đã lưu sẵn trên phiếu (module misa_invoice_status_report đã đối
        soát và ghi xuống) — tiết kiệm 2 lệnh gọi MISA cho phần lớn trường hợp. Chưa có mới tra
        sống: theo tên phiếu trước, không ra thì thử theo mã đơn bán (sale hay tạo đề nghị xuất
        hóa đơn bằng mã đơn thay vì mã phiếu kho — xem stock_picking.action_check_misa_invoice_status
        của module đó). KHÔNG gọi thẳng action_check_misa_invoice_status vì hàm đó GHI kết quả
        xuống phiếu và kéo theo cả chuỗi đối soát nhóm gộp — quá nặng và có tác dụng phụ cho một
        thao tác chỉ để xem.

        Trả (invoice_no, source, raw) — invoice_no là '' nếu không tìm ra.
        """
        raw = {'picking_name': picking.name, 'attempts': []}
        if not force_refresh and picking.misa_invoice_no:
            raw['from_picking'] = {
                'misa_invoice_no': picking.misa_invoice_no,
                'misa_invoice_date': str(picking.misa_invoice_date or ''),
                'misa_invoice_request_refno': picking.misa_invoice_request_refno or '',
            }
            return picking.misa_invoice_no, 'picking', raw

        misa_utils = self.env['misa.api.utils'].sudo()
        # Cùng thứ tự ưu tiên với action_check_misa_invoice_status: mã đề nghị gắn tay (nếu có)
        # thắng tên phiếu, vì đó là mã người dùng đã xác minh tay trên MISA.
        refnos = [picking.misa_invoice_manual_refno or picking.name]
        if not picking.misa_invoice_manual_refno:
            refnos += [name for name in picking.misa_invoice_sale_order_ids.mapped('name') if name]

        for refno in refnos:
            if not refno:
                continue
            status = misa_utils.get_invoice_status_for_refno(refno)
            raw['attempts'].append({'refno': refno, 'status': status})
            if status.get('invoice_no'):
                return status['invoice_no'], 'live', raw
        return '', 'none', raw

    def _misa_payment_fetch_vouchers(self, invoice_no):
        """Các chứng từ bán hàng MISA mang số hóa đơn này, kèm chi tiết từng dòng hàng.

        sa_voucher_get tìm theo kiểu CHỨA nên có thể trả NHIỀU dòng — tách phần khớp chính xác
        số hóa đơn (dùng để kết luận) khỏi phần thừa (chỉ hiển thị cho người dùng tự xem, xem
        split_vouchers_by_invoice_no). Chỉ tải chi tiết dòng hàng cho phần khớp chính xác, khỏi
        tốn thêm lệnh gọi cho chứng từ không liên quan.

        Trả (vouchers, others, raw).
        """
        misa_utils = self.env['misa.api.utils'].sudo()
        page_data = misa_utils.get_vouchers_by_inv_no(invoice_no)
        matched_rows, other_rows = split_vouchers_by_invoice_no(page_data, invoice_no)

        raw = {
            'voucher_search': {'inv_no': invoice_no, 'page_data': page_data},
            'voucher_details': [],
        }
        vouchers = []
        for row in matched_rows:
            detail_rows = misa_utils.get_voucher_lines(row['refid']) if row.get('refid') else []
            raw['voucher_details'].append({'refid': row.get('refid'), 'page_data': detail_rows})
            vouchers.append(self._misa_payment_voucher_values(row, detail_rows))
        others = [self._misa_payment_voucher_values(row, []) for row in other_rows]
        return vouchers, others, raw

    def _misa_payment_voucher_values(self, row, detail_rows):
        """Chuyển 1 dòng sa_voucher_get thô của MISA thành dict gọn cho giao diện."""
        state, label = paid_state_of(row.get('paid_type'))
        return {
            'invoice_no': row.get('inv_no') or '',
            'invoice_series': row.get('inv_series') or '',
            'invoice_date': row.get('inv_date') or '',
            'refno_finance': row.get('refno_finance') or '',
            'partner_name': row.get('account_object_name') or '',
            'total_amount': row.get('total_amount') or 0.0,
            'paid_state': state,
            'paid_label': label,
            'lines': [self._misa_payment_voucher_line_values(line) for line in detail_rows],
        }

    def _misa_payment_voucher_line_values(self, line):
        """Chỉ giữ 4 field cần cho việc khớp + hiển thị của 1 dòng chi tiết chứng từ MISA.

        Phần còn lại MISA trả về (đơn giá, thuế, tài khoản hạch toán...) không bỏ đi đâu cả —
        vẫn nằm nguyên trong 'raw' để người dùng bấm "Xem dữ liệu thô" đối chiếu khi cần.
        """
        return {
            'item_code': line.get('inventory_item_code') or '',
            'order_code': line.get('order_code') or '',
            'quantity': line.get('quantity') or 0.0,
            'amount': line.get('amount_oc') or 0.0,
        }

    def _misa_payment_loyalty_lines(self, picking, fallback_order_name):
        """Các dòng hàng ĐÃ TÍNH ĐIỂM của phiếu này, ở dạng dict để đối chiếu với hóa đơn.

        Dùng lại nguyên _get_loyalty_delivered_lines() của hlv_loyalty — chính hàm đã tính ra
        số điểm — để bảng đối chiếu luôn khớp với thứ đã tích điểm, kể cả cách gộp combo/kit.
        """
        lines = []
        for item in picking._get_loyalty_delivered_lines():
            sale_line = item['sale_line']
            product = item['product']
            lines.append({
                'item_code': product.default_code or '',
                'product_name': product.display_name,
                'qty': item['qty'],
                'order_code': sale_line.order_id.name if sale_line else fallback_order_name,
            })
        return lines

    def _misa_payment_build_lines(self, loyalty_lines, vouchers):
        """Đối chiếu từng dòng hàng tích điểm với chi tiết chứng từ MISA (mã hàng + mã đơn)."""
        by_order_item, by_item = index_voucher_lines(vouchers)
        rows = []
        for loyalty_line in loyalty_lines:
            match = match_loyalty_line(loyalty_line, by_order_item, by_item)
            rows.append(dict(
                loyalty_line,
                paid_state=match['paid_state'],
                match_scope=match['match_scope'],
                invoiced_qty=match['invoiced_qty'],
                invoiced_amount=sum(entry.get('amount') or 0.0 for entry in match['entries']),
                qty_shortfall=qty_shortfall(loyalty_line['qty'], match['invoiced_qty']),
                invoice_nos=match['invoice_nos'],
            ))
        return rows
