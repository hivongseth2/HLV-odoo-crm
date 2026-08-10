from odoo import api, fields, models


class SaleOrderMisaInvoiceStatus(models.Model):
    _inherit = 'sale.order'

    # Chiều ngược của stock.picking.misa_invoice_sale_order_ids — dùng cùng bảng quan hệ
    # để tra "đơn hàng này gắn với những phiếu xuất kho nào" cho tab Đơn hàng trên dashboard.
    misa_invoice_picking_ids = fields.Many2many(
        'stock.picking', 'misa_invoice_picking_sale_order_rel', 'order_id', 'picking_id',
        string='Phiếu xuất kho liên quan',
    )

    # Không lưu (store=False): tính trên các phiếu liên quan MỖI LẦN xem — tránh phải kích
    # hoạt recompute khi mốc đối soát (config, không phải field) thay đổi. Dùng để hiển thị
    # trong view riêng của đơn hàng (nút "Xem tất cả đơn hàng" trên dashboard) — KHÔNG dùng để
    # search/group (field không lưu không search được), việc lọc theo phạm vi dashboard đã làm
    # ở domain của action khi mở, xem get_misa_invoice_order_report_action.
    misa_invoice_state = fields.Selection(
        [
            ('not_checked', 'Chưa kiểm tra'),
            ('missing', 'Chưa có đề nghị xuất HĐ'),
            ('requested', 'Đã đề nghị, chờ HĐ'),
            ('partial', 'Một phần đã xuất HĐ'),
            ('invoiced', 'Đã xuất hóa đơn'),
        ],
        string='Trạng thái xuất HĐ MISA', compute='_compute_misa_invoice_status',
    )
    misa_invoice_amount = fields.Float(string='Tiền đã xuất HĐ MISA', compute='_compute_misa_invoice_status')
    misa_invoice_outstanding_amount = fields.Float(
        string='Tiền chưa xuất HĐ MISA', compute='_compute_misa_invoice_status'
    )

    def _misa_invoice_relevant_pickings(self):
        """Phiếu xuất kho THẬT SỰ nằm trong phạm vi đối soát MISA (loại Shopee/trả hàng,
        chỉ tính phiếu xuất đã done) — không lọc theo mốc đối soát ngày (đó là bộ lọc xem,
        không phải thuộc tính cố định của phiếu)."""
        self.ensure_one()
        return self.misa_invoice_picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing'
            and p.state == 'done'
            and not p.misa_invoice_is_shopee
            and 'trả hàng' not in (p.origin or '').lower()
        )

    @api.depends(
        'misa_invoice_picking_ids.misa_invoice_state',
        'misa_invoice_picking_ids.misa_invoice_amount',
        'misa_invoice_picking_ids.misa_invoice_master_picking_id.misa_invoice_amount',
        'amount_total',
    )
    def _compute_misa_invoice_status(self):
        Picking = self.env['stock.picking']
        for order in self:
            pickings = order._misa_invoice_relevant_pickings()
            if not pickings:
                order.misa_invoice_state = 'not_checked'
                order.misa_invoice_amount = 0.0
                order.misa_invoice_outstanding_amount = 0.0
                continue
            states = pickings.mapped('misa_invoice_state')
            overall_state = Picking._misa_invoice_order_state(states)
            invoiced = pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced')
            # Quy về phiếu ĐẠI DIỆN của từng đề nghị rồi khử trùng — tránh cộng lặp tiền hóa
            # đơn khi nhiều phiếu "ăn theo" cùng 1 đề nghị gộp chung đều thuộc đơn này.
            representatives = {
                (p.misa_invoice_master_picking_id or p).id: (p.misa_invoice_master_picking_id or p)
                for p in invoiced
            }
            order.misa_invoice_state = overall_state
            order.misa_invoice_amount = sum(rep.misa_invoice_amount or 0.0 for rep in representatives.values())
            order.misa_invoice_outstanding_amount = 0.0 if overall_state == 'invoiced' else order.amount_total
