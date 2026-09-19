from odoo import api, models
from odoo.exceptions import UserError

# Chi tiết HÀNG HÓA cho drawer trang /misa_sale_status: "phiếu này/đơn này có những mặt hàng
# gì, món nào đã xuất kho đủ, món nào còn chưa giao". Trước đây drawer chỉ có số tiền tổng nên
# sale phải mở lại phiếu trong backend Odoo mới biết được hàng gì bên trong.
#
# Tách khỏi stock_picking.py (đã quá lớn) và khỏi misa_invoice_public_api.py (đối soát HĐ) —
# đây là 1 mối quan tâm riêng: tiến độ GIAO HÀNG theo dòng, không đụng tới trạng thái xuất HĐ.
# Trạng thái xuất HĐ theo TỪNG dòng hàng vẫn đọc live từ MISA qua
# get_misa_invoice_line_reconciliation (nút "Xem đối chiếu đề nghị/hóa đơn" trên drawer),
# KHÔNG nhân bản logic đó ở đây.

# Sai số số lượng chấp nhận được khi so "đã giao đủ chưa" — số lượng có thể lẻ do quy đổi đơn
# vị tính, không so bằng == với float.
MISA_INVOICE_QTY_TOLERANCE = 0.001


class StockPickingMisaInvoiceGoodsDetail(models.Model):
    _inherit = 'stock.picking'

    def _misa_invoice_delivery_state(self, ordered_qty, delivered_qty):
        """Tiến độ giao của 1 dòng đơn bán: 'done' (đã giao đủ), 'partial' (giao dở), 'none'
        (chưa giao gì). Dòng có số đặt <= 0 (VD dòng ghi chú/khuyến mãi số lượng 0) coi như
        'done' để không bị tô đỏ nhầm là còn thiếu."""
        if ordered_qty <= MISA_INVOICE_QTY_TOLERANCE:
            return 'done'
        if delivered_qty >= ordered_qty - MISA_INVOICE_QTY_TOLERANCE:
            return 'done'
        return 'partial' if delivered_qty > MISA_INVOICE_QTY_TOLERANCE else 'none'

    def _misa_invoice_goods_line_rows(self, picking):
        """Danh sách hàng THỰC XUẤT của 1 phiếu, kèm tiến độ giao của dòng đơn bán tương ứng
        (đặt bao nhiêu / đã giao tổng cộng bao nhiêu / còn lại bao nhiêu).

        Tái dùng nguyên _misa_invoice_picking_line_items (đã xử lý đúng combo/kit và cách
        prorate tiền theo dòng đơn bán) — ở đây CHỈ bổ sung phần tiến độ giao, không tự tính
        lại giá trị dòng.

        Lưu ý: ordered/delivered lấy từ DÒNG ĐƠN BÁN nên là số của CẢ ĐƠN (cộng mọi đợt giao),
        không phải riêng phiếu này — đúng thứ cần để biết "món này còn phải giao nữa không".
        Dòng sản phẩm con của combo/kit không có số đặt/đã giao riêng (chỉ dòng combo đại diện
        mới có) nên trả về has_delivery_progress=False, frontend để trống thay vì lặp lại số
        của combo gây hiểu nhầm."""
        SaleLine = self.env['sale.order.line'].sudo()
        rows = []
        for item in self._misa_invoice_picking_line_items(picking):
            sale_line = SaleLine.browse(item['sale_line_id']) if item.get('sale_line_id') else SaleLine
            has_progress = bool(sale_line) and not item.get('is_component')
            ordered_qty = sale_line.product_uom_qty if has_progress else 0.0
            delivered_qty = sale_line.qty_delivered if has_progress else 0.0
            remaining_qty = max(ordered_qty - delivered_qty, 0.0)
            rows.append({
                'product_name': item['product_name'],
                'default_code': item['default_code'],
                'uom_name': item['uom_name'],
                'qty': item['qty'],
                'value': item['value'],
                'order_code': item.get('order_code') or '',
                'is_combo': bool(item.get('is_combo')),
                'is_component': bool(item.get('is_component')),
                'has_delivery_progress': has_progress,
                'ordered_qty': ordered_qty,
                'delivered_qty': delivered_qty,
                'remaining_qty': remaining_qty if remaining_qty > MISA_INVOICE_QTY_TOLERANCE else 0.0,
                'delivery_state': (
                    self._misa_invoice_delivery_state(ordered_qty, delivered_qty) if has_progress else False
                ),
            })
        return rows

    def _misa_invoice_order_goods_rows(self, order):
        """Hàng của 1 ĐƠN BÁN kèm tiến độ giao từng dòng — trả lời "món nào đã xuất kho đủ,
        món nào còn chưa giao" ở cấp ĐƠN, khác với _misa_invoice_goods_line_rows vốn chỉ nhìn
        trong phạm vi 1 phiếu (không thấy được món đã đặt mà chưa có phiếu nào giao).

        Tiền dùng price_subtotal (chưa VAT) cho nhất quán với giá trị dòng của phiếu xuất kho
        ở _misa_invoice_picking_line_items."""
        rows = []
        for line in order.order_line:
            # Dòng ghi chú/tiêu đề section không có hàng để giao.
            if line.display_type or not line.product_id:
                continue
            ordered_qty = line.product_uom_qty
            delivered_qty = line.qty_delivered
            remaining_qty = max(ordered_qty - delivered_qty, 0.0)
            rows.append({
                'product_name': line.product_id.display_name,
                'default_code': line.product_id.default_code or False,
                'uom_name': line.product_uom.name,
                'ordered_qty': ordered_qty,
                'delivered_qty': delivered_qty,
                'remaining_qty': remaining_qty if remaining_qty > MISA_INVOICE_QTY_TOLERANCE else 0.0,
                'value': line.price_subtotal,
                'delivery_state': self._misa_invoice_delivery_state(ordered_qty, delivered_qty),
            })
        return rows

    @api.model
    def get_misa_invoice_public_picking_goods(self, picking_id, saler_code):
        """Hàng trong 1 phiếu xuất kho cho drawer trang public — chỉ đọc dữ liệu Odoo (rẻ,
        không gọi MISA), scope theo đúng mã sale đang xem."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        picking = self.sudo().browse(picking_id).exists()
        if not picking or picking.misa_invoice_saler_code != code:
            raise UserError("Bạn không có quyền xem phiếu này.")
        return self.sudo()._misa_invoice_goods_line_rows(picking)

    @api.model
    def get_misa_invoice_public_order_goods(self, order_id, saler_code):
        """Hàng trong 1 đơn bán cho drawer tab Đơn hàng — cùng quy tắc quyền với
        action_public_check_order: phải có ÍT NHẤT 1 phiếu của đơn thuộc đúng mã sale đang
        xem (đơn gộp có thể chứa phiếu của nhiều mã sale)."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        order = self.env['sale.order'].sudo().browse(order_id).exists()
        if not order or not order.misa_invoice_picking_ids.filtered(
            lambda p: p.misa_invoice_saler_code == code
        ):
            raise UserError("Bạn không có quyền xem đơn hàng này.")
        return self.sudo()._misa_invoice_order_goods_rows(order)
