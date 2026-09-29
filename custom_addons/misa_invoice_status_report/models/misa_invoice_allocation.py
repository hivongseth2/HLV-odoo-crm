from odoo import api, fields, models

from .misa_invoice_amount_utils import split_by_weights


class StockPickingMisaInvoiceAllocation(models.Model):
    """Tiền hóa đơn QUY VỀ TỪNG PHIẾU, không phụ thuộc ai đứng tên đề nghị xuất HĐ.

    misa_invoice_effective_amount dồn TOÀN BỘ tiền hóa đơn của 1 đề nghị gộp vào phiếu đại
    diện (phiếu ăn theo = 0) — cộng tổng toàn công ty thì đúng, nhưng lọc theo sale/khách/kho
    thì sai: 1 đề nghị gộp có thể trộn phiếu của nhiều sale (case thật: đề nghị của
    KBC/OUT/08356 phủ phiếu của TRANTHIMYDUYEN, MAIVANNAM1, LUUTHICONG1), tiền hóa đơn của cả
    nhóm bị tính hết cho sale của phiếu đại diện. Field này chia lại để mọi tổng theo nhóm
    cộng thẳng được, và tổng toàn bộ vẫn giữ nguyên (chỉ chuyển tiền giữa các phiếu).
    """
    _inherit = 'stock.picking'

    # Các dòng hàng của đơn KHÁC nằm trong đề nghị xuất HĐ của phiếu này — cần để biết phiếu
    # này đã "nhường" bao nhiêu tiền hóa đơn cho các phiếu chỉ được phủ 1 phần.
    misa_invoice_grouped_line_ids = fields.One2many(
        'misa.invoice.grouped.line', 'master_picking_id', string='Dòng hàng đơn khác trong đề nghị',
    )
    misa_invoice_allocated_amount = fields.Float(
        string='Tiền HĐ quy về phiếu này',
        compute='_compute_misa_invoice_allocated_amount', store=True,
        help='Phần tiền hóa đơn thuộc về CHÍNH phiếu này, dù hóa đơn nằm ở đề nghị của phiếu '
             'nào. Phiếu ăn theo = tiền thực xuất của nó; phiếu được phủ 1 phần = phần đã khớp '
             'dòng hàng; phiếu đại diện = tiền HĐ của đề nghị trừ đi phần đã quy cho các phiếu '
             'kia. Có thể âm nếu đề nghị không đủ tiền phủ các phiếu đã gán vào nó.',
    )
    # Số theo ĐƠN HÀNG (sale.order._misa_invoice_apply_order_allocation ghi vào) — khi có thì
    # thay hẳn cách tính theo đề nghị ở trên: đơn xuất HĐ qua nhiều đề nghị chỉ đếm đủ được khi
    # cộng theo mã đơn trên MISA, không theo đề nghị nào đang gắn vào phiếu.
    misa_invoice_order_allocated_amount = fields.Float(string='Tiền HĐ quy về (theo đơn hàng)', copy=False)
    misa_invoice_order_allocation_ok = fields.Boolean(string='Đã có số theo đơn hàng', copy=False)

    @api.depends(
        'misa_invoice_order_allocation_ok', 'misa_invoice_order_allocated_amount',
        'misa_invoice_state', 'misa_invoice_amount', 'misa_invoice_effective_amount',
        'misa_invoice_net_actual_amount', 'misa_invoice_grouped_matched_amount',
        'misa_invoice_master_picking_id.misa_invoice_state',
        'misa_invoice_covered_picking_ids.misa_invoice_net_actual_amount',
        'misa_invoice_grouped_line_ids.match_ids.amount',
        'misa_invoice_grouped_line_ids.match_ids.picking_id.misa_invoice_amount',
        'misa_invoice_grouped_line_ids.match_ids.picking_id.misa_invoice_master_picking_id',
    )
    def _compute_misa_invoice_allocated_amount(self):
        for picking in self:
            master = picking.misa_invoice_master_picking_id
            if picking.misa_invoice_order_allocation_ok:
                picking.misa_invoice_allocated_amount = picking.misa_invoice_order_allocated_amount
            elif master:
                # Chỉ gán ăn theo khi dòng hàng đã phủ ĐỦ phiếu này (xem
                # _misa_invoice_discover_grouped_orders), nên nhận đủ tiền thực xuất — miễn là
                # đề nghị của phiếu đại diện vẫn còn hiệu lực.
                picking.misa_invoice_allocated_amount = (
                    picking.misa_invoice_net_actual_amount if master.misa_invoice_state == 'invoiced' else 0.0
                )
            elif picking.misa_invoice_state == 'invoiced' and picking.misa_invoice_amount:
                picking.misa_invoice_allocated_amount = (
                    picking.misa_invoice_effective_amount - picking._misa_invoice_amount_passed_to_others()
                )
            elif not picking.misa_invoice_amount and picking.misa_invoice_grouped_matched_amount > 0:
                # Không tự có tiền HĐ riêng nhưng được phủ 1 phần qua đề nghị của phiếu khác. Gồm cả
                # phiếu 'invoiced' mà tiền = 0: _misa_invoice_dedupe_request_refid_groups để phiếu
                # cùng đề nghị nhưng chỉ được phủ 1 phần ở trạng thái đó (case KBC/OUT/12579 cùng
                # đề nghị với KBC/OUT/12907).
                picking.misa_invoice_allocated_amount = min(
                    picking.misa_invoice_grouped_matched_amount, picking.misa_invoice_net_actual_amount,
                )
            else:
                picking.misa_invoice_allocated_amount = 0.0

    def _misa_invoice_amount_passed_to_others(self):
        """Tổng tiền hóa đơn trong đề nghị của phiếu đại diện này đã quy cho phiếu KHÁC: đủ
        tiền thực xuất của từng phiếu ăn theo, cộng phần khớp dòng hàng của các phiếu chỉ được
        phủ 1 phần. Phiếu đã ăn theo đề nghị khác hoặc tự có tiền hóa đơn riêng thì phần khớp ở
        đây không tính — tiền của chúng đã lấy từ chỗ khác, trừ thêm sẽ làm hụt tổng. Cùng điều
        kiện với nhánh "phủ 1 phần" của _compute_misa_invoice_allocated_amount, để phần nhường
        đi ở đây đúng bằng phần phiếu kia nhận."""
        self.ensure_one()
        covered = self.misa_invoice_covered_picking_ids
        partial = sum(
            match.amount
            for match in self.misa_invoice_grouped_line_ids.match_ids
            if match.picking_id != self
            and match.picking_id not in covered
            and not match.picking_id.misa_invoice_master_picking_id
            and not match.picking_id.misa_invoice_amount
        )
        return sum(covered.mapped('misa_invoice_net_actual_amount')) + partial

    def _misa_invoice_shipped_for_order(self, order):
        """Phần tiền thực xuất của phiếu này thuộc về 1 đơn. Phiếu 1 đơn = cả tiền thực xuất;
        phiếu gộp nhiều đơn chia theo giá trị sau thuế của các dòng hàng (move) mỗi đơn — dòng
        không gắn dòng đơn bán không có trọng số, cả phiếu không có dòng nào gắn thì chia đều."""
        self.ensure_one()
        orders = self.misa_invoice_sale_order_ids
        net = self.misa_invoice_net_actual_amount or 0.0
        if len(orders) <= 1:
            return net
        weights = []
        for o in orders:
            weight = 0.0
            for move in self.move_ids_without_package.filtered(lambda m, o=o: m.sale_line_id.order_id == o):
                line = move.sale_line_id
                if line.product_uom_qty:
                    weight += line.price_total / line.product_uom_qty * move.quantity
            weights.append(weight)
        return dict(zip(orders.ids, split_by_weights(net, weights)))[order.id]
