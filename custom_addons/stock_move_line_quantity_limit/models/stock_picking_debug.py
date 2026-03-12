from odoo import api, models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockQuantityLimitDebugHelper(models.TransientModel):
    _name = 'stock.quantity.limit.debug'
    _description = 'Debug tool cho stock picking assign issues'

    picking_id = fields.Many2one('stock.picking', string='Picking', required=True)
    debug_log = fields.Text(string='Debug Log', readonly=True)

    def action_debug_picking(self):
        """
        Phân tích picking để tìm lý do assign không được.
        Kiểm tra quants ở các location khác nhau.
        """
        self.ensure_one()
        picking = self.picking_id
        
        logs = []
        logs.append(f"╔═══════════════════════════════════════════════════╗")
        logs.append(f"📋 PICKING DEBUG: {picking.name}")
        logs.append(f"╚═══════════════════════════════════════════════════╝\n")

        logs.append(f"📊 THÔNG TIN PICKING")
        logs.append(f"  • Trạng thái: {picking.state}")
        logs.append(f"  • Loại: {picking.picking_type_id.name if picking.picking_type_id else 'N/A'}")
        logs.append(f"  • Vị trí từ (chính): {picking.location_id.display_name}")
        logs.append(f"  • Vị trí đến: {picking.location_dest_id.display_name}")
        logs.append(f"  • Tổng moves: {len(picking.move_ids)}\n")

        # Analyze từng move
        total_available_all_locations = 0
        
        for i, move in enumerate(picking.move_ids, 1):
            logs.append(f"─ MOVE #{i}: {move.name}")
            logs.append(f"  📦 Sản phẩm: {move.product_id.display_name}")
            logs.append(f"  📊 Qty yêu cầu: {move.product_uom_qty} {move.product_uom.name}")
            logs.append(f"  🏠 Từ (move): {move.location_id.display_name}")
            logs.append(f"  🎯 Đến: {move.location_dest_id.display_name}")
            logs.append(f"  🔄 Trạng thái: {move.state}")
            logs.append(f"  📦 Move lines: {len(move.move_line_ids)}")

            # **QUAN TRỌNG**: Kiểm tra quants ở TOÀN BỘ locations (không chỉ location của move)
            all_quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id.usage', '=', 'internal'),  # Chỉ internal locations
            ])

            if all_quants:
                logs.append(f"  ✅ SẢN PHẨM CÓ Ở CÁC VỊ TRÍ:")
                total_qty_available = 0
                for q in all_quants:
                    logs.append(
                        f"     • {q.location_id.display_name}: "
                        f"Qty={q.quantity}, Available={q.available_quantity}"
                    )
                    total_qty_available += q.available_quantity
                
                logs.append(f"  📊 TỔNG AVAILABLE TẠI TẤT CẢ LOCATIONS: {total_qty_available}")
                total_available_all_locations += total_qty_available
                
                if total_qty_available >= move.product_uom_qty:
                    logs.append(f"  ✅ ĐỦ HÀNG (nhưng có thể phân tán)")
                else:
                    logs.append(f"  ❌ KHÔNG ĐỦ HÀNG TOÀN PHẦN ({total_qty_available} < {move.product_uom_qty})")
            else:
                logs.append(f"  ❌ KHÔNG CÓ HÀNG TRONG KHO!")

            logs.append("")

        # Tóm tắt
        logs.append(f"╔═══════════════════════════════════════════════════╗")
        logs.append(f"📝 TÓM TẮT CHẨN ĐOÁN")
        logs.append(f"╚═══════════════════════════════════════════════════╝\n")

        for move in picking.move_ids:
            # Tính total available
            all_quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ])
            total_available = sum(q.available_quantity for q in all_quants)
            
            # Quant tại specific location của move
            specific_quant = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.location_id.id),
            ], limit=1)
            
            specific_available = specific_quant.available_quantity if specific_quant else 0

            logs.append(f"Move {move.name}:")
            logs.append(f"  • Yêu cầu: {move.product_uom_qty}")
            logs.append(f"  • Tại location {move.location_id.display_name}: {specific_available}")
            logs.append(f"  • Tổng tất cả locations: {total_available}")
            
            if total_available < move.product_uom_qty:
                logs.append(f"  ❌ THIẾU HÀNG TOÀN PHẦN")
            elif specific_available < move.product_uom_qty and total_available >= move.product_uom_qty:
                logs.append(f"  ⚠️  HÀNG PHÂN TÁN - Cần combine multiple locations!")
            elif specific_available >= move.product_uom_qty:
                logs.append(f"  ✅ ĐỦ TẠI LOCATION CHÍNH")
            
            logs.append("")

        logs.append(f"╔═══════════════════════════════════════════════════╗")
        logs.append(f"💡 HƯỚNG DẪN")
        logs.append(f"╚═══════════════════════════════════════════════════╝\n")
        logs.append(f"Nếu hàng PHÂN TÁN ở nhiều vị trí:")
        logs.append(f"  1. Tạo transfer trong kho để gộp hàng vào 1 location")
        logs.append(f"  2. Hoặc chỉnh location picking về vị trí có nhiều hàng nhất")
        logs.append(f"  3. Thực hiện assign sau khi xử lý\n")
        logs.append(f"Nếu THIẾU HÀNG:")
        logs.append(f"  1. Nhập thêm hàng vào kho")
        logs.append(f"  2. Hoặc giảm qty picking")

        self.debug_log = "\n".join(logs)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
