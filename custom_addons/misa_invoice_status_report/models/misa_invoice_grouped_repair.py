import logging

from markupsafe import Markup

from odoo import api, models

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

    def _misa_invoice_sibling_request_owner(self, status):
        """Phiếu xuất KHÁC cùng đơn mà đề nghị trong `status` mang tên — tức đề nghị đó là của
        phiếu kia, không phải của phiếu này. Trả recordset rỗng nếu đề nghị không mang tên phiếu
        nào (VD đặt theo mã đơn / DN00…) hoặc phiếu mang tên đó không chung đơn với phiếu này."""
        self.ensure_one()
        refno = (status.get('master_refno') or '').strip()
        if not refno or refno == self.name:
            return self.browse()
        owner = self.sudo().search([
            ('name', '=', refno), ('picking_type_id.code', '=', 'outgoing'), ('id', '!=', self.id),
        ], limit=1)
        if owner and owner.misa_invoice_sale_order_ids & self.misa_invoice_sale_order_ids:
            return owner
        return self.browse()

    @api.model
    def repair_misa_invoice_own_order_overmatch(self, dry_run=True):
        """Khớp lại các dòng xuất HĐ chung thuộc CHÍNH đơn của phiếu đại diện theo luật mới (trừ SL
        phiếu đại diện đã xuất trước). Phiếu ăn theo không còn được phủ đủ thì gỡ ăn theo, trả về
        'Chưa kiểm tra' rồi kiểm tra lại MISA (dry_run=False).

        Trả list dict {picking, master, item, before, after, released} — before/after là SL dòng
        khớp sang phiếu đó trước/sau khi khớp lại. dry_run=True: tính trong savepoint rồi
        rollback, không gọi MISA, không ghi gì."""
        report = []
        released_ids = []
        try:
            with self.env.cr.savepoint():
                report, released_ids = self._misa_invoice_rematch_own_order_lines()
                if dry_run:
                    raise _DryRun()
        except _DryRun:
            pass
        self.env.invalidate_all()
        if not dry_run and released_ids:
            self.sudo().browse(released_ids).action_check_misa_invoice_status()
        return report

    def _misa_invoice_rematch_own_order_lines(self):
        """Phần ghi của repair_misa_invoice_own_order_overmatch. Trả (report, id phiếu đã gỡ)."""
        GroupedLine = self.env['misa.invoice.grouped.line'].sudo()
        lines = GroupedLine.search([('match_ids', '!=', False)]).filtered(
            lambda l: l.sale_order_id in l.master_picking_id.misa_invoice_sale_order_ids
            and not all(l.match_ids.mapped('is_manual'))
        )
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
            picking.write({
                'misa_invoice_master_picking_id': False, 'misa_invoice_state': 'not_checked',
                'misa_invoice_amount': 0.0, 'misa_invoice_no': False, 'misa_invoice_date': False,
                'misa_invoice_request_refid': False, 'misa_invoice_request_refno': False,
                'misa_invoice_group_checked': False,
            })
            picking.message_post(body=Markup(
                "<b>🔧 Gỡ 'ăn theo' %s:</b> dòng hàng đề nghị của phiếu đó chỉ đủ cho chính nó, phiếu này "
                "bị khớp nhầm phần SL của phiếu đó — trả về 'Chưa kiểm tra' để kiểm tra lại MISA."
            ) % master.name)
            released |= picking
            for row in report:
                if row['picking'] == picking.name:
                    row['released'] = True
        _logger.info("[MISA GROUP REPAIR] khớp lại %s dòng, gỡ ăn theo %s phiếu", len(lines), len(released))
        return report, released.ids
