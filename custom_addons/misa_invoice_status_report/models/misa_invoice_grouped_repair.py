import logging

from markupsafe import Markup

from odoo import api, models

from .stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

_logger = logging.getLogger(__name__)


class _DryRun(Exception):
    """Ném ra để rollback savepoint khi chạy thử repair."""


class StockPickingGroupedRepair(models.Model):
    """Phiếu giao đợt sau của 1 đơn bị nhận nhầm HĐ của đợt trước.

    Case thật DH125524949235092: KBC/OUT/11995 xuất 8 cái, đề nghị KBC/OUT/11995 ghi 8 cái (HĐ
    00004909); KBC/OUT/14143 giao thêm 2 cái, chưa lập đề nghị. Tìm 14143 theo mã đơn ra đề nghị
    của 11995, rồi khớp dòng hàng loại hẳn 11995 khỏi FIFO nên 2/8 cái của dòng đó khớp sang 14143
    → 14143 "ăn theo" 11995, báo "Đã xuất HĐ". Luật khớp đã sửa (owner_picking_id trong
    _misa_invoice_reconcile_line_match); file này chặn đường tìm theo mã đơn và sửa dữ liệu cũ.
    """
    _inherit = 'stock.picking'

    def _misa_invoice_sibling_pickings(self):
        """Phiếu xuất KHÁC (chưa hủy) cùng đơn bán với phiếu này — đề nghị mang tên / đang thuộc
        các phiếu này là HĐ của đợt giao khác. Không có đơn bán thì trả rỗng."""
        self.ensure_one()
        if not self.misa_invoice_sale_order_ids:
            return self.browse()
        return self.sudo().search([
            ('misa_invoice_sale_order_ids', 'in', self.misa_invoice_sale_order_ids.ids),
            ('picking_type_id.code', '=', 'outgoing'), ('state', '!=', 'cancel'), ('id', '!=', self.id),
        ])

    @api.model
    def _misa_invoice_own_order_matched_lines(self, domain=()):
        """Dòng xuất HĐ chung thuộc CHÍNH đơn của phiếu đại diện, có lượt khớp tự động — những dòng
        luật khớp cũ (loại hẳn phiếu đại diện) có thể đã chia nhầm SL. `domain` lọc thêm."""
        return self.env['misa.invoice.grouped.line'].sudo().search(
            [('match_ids', '!=', False), *domain],
        ).filtered(
            lambda l: l.sale_order_id in l.master_picking_id.misa_invoice_sale_order_ids
            and not all(l.match_ids.mapped('is_manual'))
        )

    @api.model
    def misa_invoice_own_order_overmatch_master_ids(self):
        """Id phiếu đại diện cần khớp lại — để script chạy từng phiếu, mỗi phiếu 1 giao dịch ngắn."""
        return self._misa_invoice_own_order_matched_lines().mapped('master_picking_id').ids

    @api.model
    def repair_misa_invoice_own_order_overmatch(self, master_id, dry_run=True):
        """Khớp lại các dòng xuất HĐ chung thuộc CHÍNH đơn của 1 phiếu đại diện theo luật mới (trừ
        SL phiếu đại diện đã xuất trước). Phiếu ăn theo không còn được phủ đủ thì gỡ ăn theo, trả về
        'Chưa kiểm tra' rồi kiểm tra lại MISA (dry_run=False).

        Từng phiếu đại diện một, trong savepoint riêng: chạy cả trăm phiếu trong 1 giao dịch là giữ
        khóa các dòng gộp cả mấy phút, cron kiểm tra MISA chạy cùng lúc thì deadlock (staging
        19/10/2026). Rollback savepoint nhả khóa ngay.

        Trả list dict {picking, master, item, before, after, released} — before/after là SL dòng
        khớp sang phiếu đó trước/sau khi khớp lại. dry_run=True: tính trong savepoint rồi
        rollback, không gọi MISA, không ghi gì. Không commit — script gọi tự commit."""
        report = []
        released_ids = []
        try:
            with self.env.cr.savepoint():
                report, released_ids = self.sudo().browse(master_id)._misa_invoice_rematch_own_order_lines()
                if dry_run:
                    raise _DryRun()
        except _DryRun:
            pass
        self.env.invalidate_all()
        if not dry_run and released_ids:
            self.sudo().browse(released_ids).action_check_misa_invoice_status()
        return report

    def _misa_invoice_rematch_own_order_lines(self):
        """Phần ghi của repair_misa_invoice_own_order_overmatch cho phiếu đại diện self. Trả
        (report, id phiếu đã gỡ)."""
        self.ensure_one()
        lines = self._misa_invoice_own_order_matched_lines([('master_picking_id', '=', self.id)])
        report = []
        touched = self.browse()
        for line in lines:
            master = line.master_picking_id
            auto = line.match_ids.filtered(lambda m: not m.is_manual)
            before = {m.picking_id: m.quantity for m in auto}
            auto.unlink()
            line.write({'match_state': 'pending', 'match_note': False})
            master._misa_invoice_grouped_try_match(line, owner_picking_id=master.id)
            after = {m.picking_id: m.quantity for m in line.match_ids.filtered(lambda m: not m.is_manual)}
            for picking, qty in before.items():
                if abs(after.get(picking, 0.0) - qty) > 0.001:
                    touched |= picking
                    report.append({
                        'picking': picking.name, 'master': master.name, 'item': line.inventory_item_code,
                        'before': qty, 'after': after.get(picking, 0.0), 'released': False,
                    })
        released = self.browse()
        for picking in touched:
            picking.invalidate_recordset(['misa_invoice_grouped_matched_amount'])
            master = picking.misa_invoice_master_picking_id
            # covers_fully coi "chưa khớp dòng nào" là phủ đủ (hành vi cho ca không đọc được dòng
            # hàng) — ở đây phiếu vừa MẤT hết dòng khớp nên phải xét riêng.
            if not master or (picking.misa_invoice_grouped_match_ids and picking._misa_invoice_request_covers_fully()):
                continue
            picking._misa_invoice_reset_for_recheck(Markup(
                "<b>🔧 Gỡ 'ăn theo' %s:</b> dòng hàng đề nghị của phiếu đó chỉ đủ cho chính nó, phiếu này "
                "bị khớp nhầm phần SL của phiếu đó — trả về 'Chưa kiểm tra' để kiểm tra lại MISA."
            ) % master.name)
            released |= picking
            for row in report:
                if row['picking'] == picking.name:
                    row['released'] = True
        _logger.info("[MISA GROUP REPAIR] khớp lại %s dòng, gỡ ăn theo %s phiếu", len(lines), len(released))
        return report, released.ids

    def _misa_invoice_reset_for_recheck(self, note):
        """Xóa kết quả đối soát của phiếu (trạng thái, HĐ, đề nghị, ăn theo) về 'Chưa kiểm tra' và
        ghi `note` vào chatter — để action_check_misa_invoice_status tính lại từ đầu. Bắt buộc về
        'Chưa kiểm tra' trước: phiếu đang 'Đã xuất HĐ' mà lần kiểm mới không ra đề nghị thì hàm
        kiểm tra GIỮ NGUYÊN dữ liệu cũ (chống mất dữ liệu), không bao giờ tự hạ."""
        self.write({
            'misa_invoice_master_picking_id': False, 'misa_invoice_state': 'not_checked',
            'misa_invoice_amount': 0.0, 'misa_invoice_no': False, 'misa_invoice_date': False,
            'misa_invoice_request_refid': False, 'misa_invoice_request_refno': False,
            'misa_invoice_group_checked': False,
        })
        for picking in self:
            picking.message_post(body=note)

    @api.model
    def misa_invoice_unallocated_invoiced_ids(self):
        """Phiếu báo 'Đã xuất HĐ' mà số theo đơn KHÔNG quy đồng HĐ nào về phiếu (thực xuất > dung
        sai, HĐ quy về ≈ 0), không gắn tay và không có đề nghị mang tên chính nó.

        Đây là dấu vết của tìm theo mã đơn nhận nhầm đề nghị của đợt / đơn khác rồi bị gộp dự
        phòng theo refid (covers_fully coi "chưa khớp dòng nào" là phủ đủ) — case thật 20/10/2026:
        KBC/OUT/14107, 14255 (DH…237496), 14113 (DH…235907) báo 'Đã xuất HĐ' mà HĐ chia 0 đ."""
        domain = self._misa_invoice_dashboard_base_domain() + [
            ('misa_invoice_state', '=', 'invoiced'), ('misa_invoice_order_allocation_ok', '=', True),
            ('misa_invoice_manual_refno', '=', False),
        ]
        return self.sudo().search(domain).filtered(
            lambda p: (p.misa_invoice_net_actual_amount or 0.0) > MISA_INVOICE_AMOUNT_TOLERANCE
            and abs(p.misa_invoice_allocated_amount or 0.0) <= MISA_INVOICE_AMOUNT_TOLERANCE
            and p.misa_invoice_request_refno != p.name
        ).ids

    @api.model
    def recheck_misa_invoice_from_scratch(self, picking_id):
        """Về 'Chưa kiểm tra' rồi kiểm tra lại MISA bằng luật hiện tại cho 1 phiếu. Trả
        {name, before, after} — before/after dạng 'trạng thái | đề nghị | HĐ'. Không commit."""
        picking = self.sudo().browse(picking_id)

        def describe():
            return '%s | %s | %s' % (picking.misa_invoice_state, picking.misa_invoice_request_refno or '—',
                                     picking.misa_invoice_no or '—')

        before = describe()
        picking._misa_invoice_reset_for_recheck(Markup(
            "<b>🔧 Kiểm tra lại từ đầu:</b> phiếu báo 'Đã xuất HĐ' (%s) nhưng số theo đơn không quy đồng "
            "HĐ nào về phiếu — trạng thái cũ do tìm theo mã đơn nhận nhầm đề nghị của đợt/đơn khác."
        ) % before)
        picking.action_check_misa_invoice_status()
        picking.invalidate_recordset()
        return {'name': picking.name, 'before': before, 'after': describe()}
