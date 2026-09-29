from odoo import api, fields, models

from .misa_invoice_amount_utils import invoice_vat_ratio, pair_invoice_lines


class MisaInvoiceCustomsLine(models.Model):
    _name = 'misa.invoice.customs.line'
    _description = 'Dòng hàng đã xuất hóa đơn MISA trước khi xuất kho Odoo (hàng hải quan)'
    _order = 'fetched_at desc, invoice_no, order_code'

    # Trường hợp "hải quan": hóa đơn được lập trên MISA TRƯỚC khi phiếu xuất kho Odoo tồn
    # tại, nên không thể đối soát theo refno=tên phiếu như luồng thông thường. Ghi nhận thủ
    # công (nhập số hóa đơn, fetch 1 lần) ở mức ĐƠN HÀNG + MÃ HÀNG (không phải toàn đơn) vì
    # 1 hóa đơn có thể chỉ phủ MỘT PHẦN đơn hàng (xuất kho từng phần).
    invoice_no = fields.Char(string='Số hóa đơn MISA', required=True, index=True)
    invoice_refid = fields.Char(string='MISA Voucher RefID')
    # Số chứng từ hạch toán (khác số hóa đơn) — kế toán dùng để đối chiếu sổ sách, MISA trả
    # riêng field này (refno_finance) tách biệt với inv_no.
    refno_finance = fields.Char(string='Số chứng từ (refno_finance)')
    invoice_date = fields.Date(string='Ngày hóa đơn')
    partner_name = fields.Char(string='Khách hàng')
    # Mã nhân viên sale trên chứng từ MISA (employee_code) — dùng để trang public
    # /misa_sale_status chỉ hiện đúng hóa đơn của sale đang xem (so với mã đã chọn, khớp
    # đúng cách misa_invoice_saler_code lọc dữ liệu ở phần còn lại của trang).
    employee_code = fields.Char(string='Mã nhân viên sale (MISA)', index=True)

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', ondelete='set null', index=True)
    # Giữ lại mã gốc từ MISA dù có khớp được sale.order hay không — để biết ngay khi khớp
    # thất bại (VD sai tên đơn, đơn chưa tồn tại trong Odoo) thay vì mất luôn thông tin.
    order_code = fields.Char(string='Mã đơn hàng (MISA)', required=True, index=True)

    inventory_item_code = fields.Char(string='Mã hàng', required=True)
    description = fields.Char(string='Tên hàng')
    quantity = fields.Float(string='Số lượng')
    unit_price = fields.Float(string='Đơn giá')
    # amount phải CÓ VAT: đem so với misa_invoice_net_actual_amount của phiếu (cũng có VAT).
    # Dòng ghi nhận trước bản sửa này lưu nhầm số chưa VAT (amount_includes_vat=False) — cron
    # hải quan tự đọc lại hóa đơn từ MISA và sửa, xem resync_amounts_from_misa().
    amount = fields.Float(string='Thành tiền (có VAT)')
    amount_before_vat = fields.Float(string='Thành tiền (chưa VAT)')
    amount_includes_vat = fields.Boolean(string='Tiền đã gồm VAT', default=False)
    # Lỗi lần đọc lại gần nhất — hóa đơn lỗi xếp sau hóa đơn chưa thử, để 1 hóa đơn MISA không
    # còn tra được không chiếm mãi suất đọc lại của các hóa đơn khác mỗi lượt cron.
    amount_resync_error = fields.Char(string='Lỗi đọc lại tiền từ MISA')

    # Khi lưu, hệ thống thử tìm NGAY phiếu xuất kho (đã done) khớp đơn bán + mã hàng — nếu
    # phiếu chưa tồn tại hoặc chưa hoàn tất, dòng này ở lại 'pending' và cron định kỳ
    # (_cron_scan_misa_customs_pending) sẽ tự thử lại, không cần thao tác gì thêm. 1 dòng có
    # thể được xuất kho THÀNH NHIỀU ĐỢT (hóa đơn ghi 2 nhưng phiếu đầu chỉ xuất 1) nên quan hệ
    # với phiếu xuất kho tách ra bảng match_ids riêng thay vì 1 Many2one duy nhất.
    match_ids = fields.One2many('misa.invoice.customs.match', 'line_id', string='Các lượt khớp phiếu xuất kho')
    # picking_id giữ lại = phiếu của lượt khớp GẦN NHẤT — chỉ để hiển thị nhanh (list, badge...)
    # mà không phải join qua match_ids; nguồn sự thật thực sự là match_ids.
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu xuất kho (gần nhất)', compute='_compute_matched_qty', store=True,
    )
    matched_qty = fields.Float(string='Số lượng đã khớp', compute='_compute_matched_qty', store=True)
    match_state = fields.Selection([
        ('pending', 'Chờ xuất kho'),
        ('partial', 'Khớp một phần'),
        ('matched', 'Đã khớp phiếu xuất kho'),
    ], string='Trạng thái khớp', default='pending', index=True, required=True)
    matched_at = fields.Datetime(string='Thời điểm khớp')
    # Lý do CỤ THỂ đang ở trạng thái pending/partial (không tìm thấy sản phẩm / chưa có phiếu /
    # còn thiếu số lượng...) — để người dùng tự biết cần sửa gì mà không phải đoán mù hay chờ
    # tới lượt cron sau mới biết.
    match_note = fields.Char(string='Ghi chú khớp')

    fetched_by_id = fields.Many2one('res.users', string='Người ghi nhận')
    fetched_at = fields.Datetime(string='Thời điểm ghi nhận')

    @api.depends('match_ids.quantity', 'match_ids.picking_id', 'match_ids.matched_at')
    def _compute_matched_qty(self):
        for line in self:
            line.matched_qty = sum(line.match_ids.mapped('quantity'))
            line.picking_id = line.match_ids[-1].picking_id if line.match_ids else False

    def remaining_qty(self):
        self.ensure_one()
        return max(self.quantity - self.matched_qty, 0.0)

    @api.model
    def resync_amounts_from_misa(self, limit=None):
        """Đọc lại từ MISA các hóa đơn có dòng còn lưu tiền chưa VAT và ghi đúng tiền có VAT
        của TỪNG DÒNG (cùng cách tính với lúc ghi nhận mới, qua fetch_misa_customs_invoice).
        Sửa TẠI CHỖ: ghi nhận lại hóa đơn (save_misa_customs_invoice) xóa dòng cũ, mất hết lượt
        khớp tay. Lượt khớp đổi tiền theo đơn giá mới, rồi cộng lại tiền HĐ của phiếu.

        Dòng đã lưu không còn trên hóa đơn MISA (hóa đơn bị sửa sau khi ghi nhận) quy đổi theo
        tỉ lệ tổng hóa đơn MISA. Gọi MISA lỗi thì giữ nguyên, ghi lỗi vào amount_resync_error
        để lượt sau thử lại (xếp sau hóa đơn chưa thử).

        limit: số hóa đơn tối đa mỗi lượt (None = tất cả). Trả list {invoice_no, lines, before,
        after, error} từng hóa đơn đã thử.
        """
        Picking = self.env['stock.picking'].sudo()
        todo = self.sudo().search([('amount_includes_vat', '=', False)])
        failed_before = set(todo.filtered('amount_resync_error').mapped('invoice_no'))
        inv_nos = sorted(set(todo.mapped('invoice_no')), key=lambda inv: (inv in failed_before, inv))
        report = []
        for inv_no in inv_nos[:limit] if limit else inv_nos:
            lines = todo.filtered(lambda l, inv_no=inv_no: l.invoice_no == inv_no)
            before = sum(lines.mapped('amount'))
            try:
                preview = Picking.fetch_misa_customs_invoice(inv_no)
            except Exception as e:
                lines.write({'amount_resync_error': str(e)[:250]})
                report.append({'invoice_no': inv_no, 'lines': len(lines), 'before': before, 'error': str(e)})
                continue
            fallback_ratio = invoice_vat_ratio(preview['total_amount'], [l['amount'] for l in preview['lines']])
            paired = pair_invoice_lines(
                [(l.id, l.order_code, l.inventory_item_code, l.quantity) for l in lines], preview['lines'],
            )
            for line in lines:
                fresh = paired.get(line.id)
                new_amount = fresh['amount_with_vat'] if fresh else line.amount * fallback_ratio
                unit = new_amount / line.quantity if line.quantity else 0.0
                line.write({
                    'amount_before_vat': fresh['amount'] if fresh else line.amount,
                    'amount': new_amount,
                    'amount_includes_vat': True,
                    'amount_resync_error': False,
                })
                for match in line.match_ids:
                    match.amount = unit * match.quantity
            for picking in lines.mapped('match_ids.picking_id'):
                Picking._misa_invoice_customs_apply_to_picking(picking)
            lines.mapped('sale_order_id').filtered('misa_invoice_order_checked_at')._misa_invoice_apply_order_allocation()
            report.append({
                'invoice_no': inv_no, 'lines': len(lines), 'before': before,
                'after': sum(lines.mapped('amount')), 'unpaired': len(lines) - len(paired), 'error': False,
            })
        return report
