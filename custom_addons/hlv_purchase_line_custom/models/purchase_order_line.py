from odoo import api, fields, models
from odoo.tools import float_compare


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    stt = fields.Char(
        string="STT",
        compute="_compute_stt",
        store=False,
        help="Số thứ tự tự động của dòng sản phẩm trong đơn mua hàng",
    )
    production_year = fields.Char(
        string="Năm sản xuất",
        help="Năm sản xuất của sản phẩm",
    )
    country_of_origin = fields.Char(
        string="Xuất xứ",
        help="Quốc gia/Nơi xuất xứ của sản phẩm",
    )
    picking_ids = fields.Many2many(
        "stock.picking",
        compute="_compute_picking_info",
        string="Phiếu nhập kho",
        help="Các phiếu nhập kho liên kết với dòng sản phẩm này.",
    )
    picking_count = fields.Integer(
        compute="_compute_picking_info",
        string="Số lượng phiếu nhập",
    )

    @api.depends("move_ids", "move_ids.picking_id", "move_ids.state")
    def _compute_picking_info(self):
        for line in self:
            moves = line.move_ids.filtered(lambda m: m.picking_id and m.state != "cancel")
            pickings = moves.mapped("picking_id")
            line.picking_ids = pickings
            line.picking_count = len(pickings)

    def action_open_picking(self):
        self.ensure_one()
        pickings = self.picking_ids
        if not pickings:
            pickings = self.order_id.picking_ids.filtered(lambda p: p.state != "cancel")
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.action_picking_tree_all")
        if len(pickings) == 1:
            action["views"] = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["res_id"] = pickings.id
        else:
            action["domain"] = [("id", "in", pickings.ids)]
        return action

    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        """Move âm (giảm SL dòng) mang khoá gộp của move nhận còn mở để Odoo trừ thẳng vào đó.

        Core tạo move âm từ cấu hình đơn (kệ mặc định của loại phiếu nhập, date_planned của dòng).
        Phiếu nhập mà kho đã chọn kệ khác / đổi hạn thì lệch khoá, move âm không trừ được và bị
        đảo thành phiếu trả NCC (loại OUT) cho hàng chưa hề nhận — VD DMH23661 → KBC/OUT/13928.
        """
        vals = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        if float_compare(product_uom_qty, 0.0, precision_rounding=product_uom.rounding) < 0:
            receipt = self._open_receipt_move(picking)
            if receipt:
                vals.update(receipt._negative_merge_key_vals())
        return vals

    def _open_receipt_move(self, picking):
        """Move nhận còn mở của dòng trong `picking` — chỉ phiếu này được core xét khi trừ move âm.

        Lấy move có SL lớn nhất để trừ trọn được nhiều nhất; không có thì trả recordset rỗng.
        """
        receipts = self.move_ids.filtered(
            lambda m: m.picking_id == picking
            and m.state not in ("draft", "done", "cancel")
            and m.product_uom_qty > 0
            and not m._is_purchase_return()
        )
        return receipts.sorted("product_uom_qty", reverse=True)[:1]

    @api.depends("order_id.order_line", "order_id.order_line.sequence", "order_id.order_line.display_type")
    def _compute_stt(self):
        for line in self:
            line.stt = False

        for order in self.mapped("order_id"):
            number = 0
            for line in order.order_line:
                if line.display_type:
                    line.stt = False
                    continue
                number += 1
                line.stt = str(number)



