# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _check_qty_validation_before_validate(self):
        """
        Kiểm tra quantity không được vượt quá product_uom_qty trên picking.
        Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên) vì demand luôn = 0.
        """
        self.ensure_one()

        # Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên)
        if self.name and 'INT' in self.name:
            return

        # Danh sách các move vi phạm (qty_done > product_uom_qty)
        violations = []

        # Kiểm tra từng move trong picking
        for move in self.move_ids_without_package:
            # Bỏ qua các move đã done hoặc đã cancel
            if move.state in ('done', 'cancel'):
                continue

            # Lấy số lượng đã đặt (demand) và số lượng thực tế (done)
            qty_demand = float(move.product_uom_qty or 0.0)
            qty_done = float(move.quantity or 0.0)

            # Sử dụng epsilon để xử lý sai số floating point
            EPS = 1e-6

            # Nếu qty_done vượt quá qty_demand
            if qty_done > qty_demand + EPS:
                product_name = move.product_id.display_name or move.product_id.name or _("Sản phẩm không xác định")
                uom_name = move.product_uom.name if move.product_uom else ''

                violations.append({
                    'product': product_name,
                    'demand': qty_demand,
                    'done': qty_done,
                    'uom': uom_name,
                    'move_id': move.id,
                })

                _logger.warning(
                    "⚠️ Picking %s: Move %s (%s) có qty_done (%.2f) > product_uom_qty (%.2f)",
                    self.name, move.id, product_name, qty_done, qty_demand
                )

        # Nếu có vi phạm, chặn xác nhận và hiển thị thông báo lỗi
        if violations:
            error_lines = []
            for v in violations:
                error_lines.append(
                    _("• %s: Đã làm %.2f %s (vượt quá %.2f %s đã đặt)") % (
                        v['product'],
                        v['done'],
                        v['uom'],
                        v['demand'],
                        v['uom']
                    )
                )

            error_message = _(
                "Không thể xác nhận phiếu %s!\n\n"
                "Số lượng thực tế (Done) không được vượt quá số lượng đã đặt (Demand):\n\n"
                "%s\n\n"
                "Vui lòng điều chỉnh số lượng trước khi xác nhận."
            ) % (self.name, "\n".join(error_lines))

            _logger.error("🚫 CHẶN XÁC NHẬN picking %s do vi phạm qty_done > product_uom_qty", self.name)

            raise UserError(error_message)

        _logger.info("✅ Picking %s: Tất cả qty_done đều hợp lệ", self.name)

    def button_validate(self):
        """
        Override button_validate để kiểm tra quantity không được vượt quá product_uom_qty
        trên tất cả các stock.move trước khi xác nhận picking.
        Hỗ trợ xác nhận nhiều picking cùng lúc.
        """
        # Kiểm tra từng picking trước khi validate
        for picking in self:
            picking._check_qty_validation_before_validate()

        # Nếu không có vi phạm, tiếp tục xác nhận bình thường
        return super(StockPicking, self).button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.depends('move_line_ids.qty_done', 'move_line_ids.product_uom_id')
    def _compute_quantity_done(self):
        """
        Override _compute_quantity_done để thêm warning log khi phát hiện
        qty_done > product_uom_qty (không chặn ở đây, chỉ log cảnh báo).
        """
        res = super(StockMove, self)._compute_quantity_done()

        for move in self:
            if move.state in ('done', 'cancel'):
                continue

            qty_demand = float(move.product_uom_qty or 0.0)
            qty_done = float(move.quantity or 0.0)
            EPS = 1e-6

            if qty_done > qty_demand + EPS:
                _logger.debug(
                    "⚠️ Move %s (%s): qty_done (%.2f) > product_uom_qty (%.2f) - sẽ chặn khi validate picking",
                    move.id,
                    move.product_id.display_name,
                    qty_done,
                    qty_demand
                )

        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _get_qty_done_value(self):
        """
        Lấy giá trị qty_done, tương thích cả Odoo 16 (qty_done) và Odoo 17+ (quantity)
        """
        if hasattr(self, 'qty_done'):
            return float(self.qty_done or 0.0)
        return float(self.quantity or 0.0)

    @api.constrains('qty_done', 'quantity')
    def _check_qty_done_not_exceed_demand(self):
        """
        Chặn ngay khi tạo hoặc cập nhật stock.move.line nếu quantity vượt quá
        product_uom_qty của stock.move tương ứng.

        Điều này ngăn chặn việc quét mã vạch dư hoặc nhập thủ công số lượng vượt mức.
        Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên) vì demand luôn = 0.
        """
        # Bypass validation nếu được gọi từ packaging context
        _logger.info(f"DEBUG VALIDATION: Line ID {self.ids} - skip_qty_validation={self.env.context.get('skip_qty_validation')}")
        if self.env.context.get('skip_qty_validation'):
            return
            
        EPS = 1e-6  # Epsilon để xử lý sai số floating point

        for line in self:
            # Bỏ qua nếu không có move liên kết hoặc move đã done/cancel
            if not line.move_id or line.move_id.state in ('done', 'cancel'):
                continue

            # Bỏ qua nếu picking đã done (cho phép điều chỉnh sau khi hoàn thành)
            if line.picking_id and line.picking_id.state == 'done':
                continue

            # Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên)
            if not line.picking_id or (line.picking_id.name and 'INT' in line.picking_id.name):
                continue

            move = line.move_id

            # Lấy tổng qty_done của TẤT CẢ move lines cùng move (bao gồm line hiện tại)
            total_qty_done = sum(
                ml._get_qty_done_value()
                for ml in move.move_line_ids
                if ml.state not in ('done', 'cancel')
            )

            # Số lượng demand (đã đặt)
            qty_demand = float(move.product_uom_qty or 0.0)

            # Kiểm tra vi phạm
            if total_qty_done > qty_demand + EPS:
                product_name = move.product_id.display_name or move.product_id.name or _("Sản phẩm không xác định")
                uom_name = move.product_uom.name if move.product_uom else ''
                picking_name = line.picking_id.name if line.picking_id else _("N/A")

                _logger.error(
                    "🚫 CHẶN tạo/cập nhật move.line: Picking %s, Product %s, "
                    "Total qty_done (%.2f) > demand (%.2f)",
                    picking_name, product_name, total_qty_done, qty_demand
                )

                raise UserError(_(
                    "Không thể nhập số lượng vượt quá demand!\n\n"
                    "📦 Phiếu: %s\n"
                    "🏷️ Sản phẩm: %s\n"
                    "📊 Đã đặt (Demand): %.2f %s\n"
                    "✏️ Đã nhập (Done): %.2f %s\n\n"
                    "❌ Bạn đang cố nhập %.2f %s vượt quá số lượng cho phép.\n\n"
                    "💡 Vui lòng kiểm tra lại số lượng hoặc liên hệ quản lý."
                ) % (
                    picking_name,
                    product_name,
                    qty_demand, uom_name,
                    total_qty_done, uom_name,
                    total_qty_done - qty_demand, uom_name
                ))

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create để validate ngay khi tạo move.line mới
        (ví dụ: khi quét mã vạch)
        """
        lines = super(StockMoveLine, self).create(vals_list)

        # Validate sau khi tạo (bypass nếu có skip flag)
        if not self.env.context.get('skip_qty_validation'):
            lines._check_qty_done_not_exceed_demand()

        return lines

    def write(self, vals):
        """
        Override write để validate khi cập nhật qty_done hoặc quantity
        """
        res = super(StockMoveLine, self).write(vals)

        # Chỉ validate nếu có thay đổi qty_done hoặc quantity (bypass nếu có skip flag)
        if ('qty_done' in vals or 'quantity' in vals) and not self.env.context.get('skip_qty_validation'):
            self._check_qty_done_not_exceed_demand()

        return res
