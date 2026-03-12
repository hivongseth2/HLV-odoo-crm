from odoo import api, models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPickingDebugHelper(models.TransientModel):
    _name = 'stock.picking.debug.helper'
    _description = 'Debug tool cho stock picking assign issues'

    picking_id = fields.Many2one('stock.picking', string='Picking', required=True)
    debug_log = fields.Text(string='Debug Log', readonly=True)

    def action_debug_picking(self):
        """
        Analyze picking để tìm lý do assign không được.
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
        logs.append(f"  • Đầu quá: {picking.location_id.display_name}")
        logs.append(f"  • Đến: {picking.location_dest_id.display_name}")
        logs.append(f"  • Tổng moves: {len(picking.move_ids)}\n")

        # Analyze từng move
        for i, move in enumerate(picking.move_ids, 1):
            logs.append(f"─ MOVE #{i}: {move.name}")
            logs.append(f"  📦 Sản phẩm: {move.product_id.display_name}")
            logs.append(f"  📊 Qty yêu cầu: {move.product_uom_qty} {move.product_uom.name}")
            logs.append(f"  🏠 Từ: {move.location_id.display_name}")
            logs.append(f"  🎯 Đến: {move.location_dest_id.display_name}")
            logs.append(f"  🔄 Trạng thái: {move.state}")
            logs.append(f"  📦 Move lines: {len(move.move_line_ids)}")

            # Check quant
            quant = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.location_id.id),
            ], limit=1)

            if quant:
                logs.append(f"  ✅ QUANT TỒN TẠI")
                logs.append(f"     • Quantity: {quant.quantity}")
                logs.append(f"     • Reserved: {quant.reserved_quantity}")
                logs.append(f"     • Available: {quant.available_quantity}")
                logs.append(f"     • Owner: {quant.owner_id.display_name if quant.owner_id else 'Không'}")
                logs.append(f"     • Lot: {quant.lot_id.display_name if quant.lot_id else 'Không'}")
            else:
                logs.append(f"  ❌ KHÔNG CÓ QUANT TẠI ĐỊA ĐIỂM NÀY!")
                
                # Tìm quant ở nơi khác
                other_quants = self.env['stock.quant'].search([
                    ('product_id', '=', move.product_id.id),
                ])
                if other_quants:
                    logs.append(f"  💡 Sản phẩm này ở những nơi khác:")
                    for q in other_quants:
                        logs.append(f"     • {q.location_id.display_name}: {q.quantity} (available: {q.available_quantity})")

            logs.append("")

        # Tóm tắt
        logs.append(f"╔═══════════════════════════════════════════════════╗")
        logs.append(f"📝 CHẨN ĐOÁN")
        logs.append(f"╚═══════════════════════════════════════════════════╝\n")

        all_ok = True
        for move in picking.move_ids:
            quant = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.location_id.id),
            ], limit=1)

            if not quant:
                logs.append(f"❌ {move.name}: Không có quant tại {move.location_id.display_name}")
                all_ok = False
            elif quant.available_quantity < move.product_uom_qty:
                logs.append(
                    f"⚠️  {move.name}: Không đủ hàng "
                    f"({quant.available_quantity} < {move.product_uom_qty})"
                )
                all_ok = False
            else:
                logs.append(f"✅ {move.name}: OK")

        if all_ok:
            logs.append(f"\n💡 Lý do assign không được có thể:")
            logs.append(f"   • Stock quant bị lock bởi process khác")
            logs.append(f"   • UoM (Unit of Measure) không khớp")
            logs.append(f"   • Concurrent issue (nhiều picking cùng lúc)")
            logs.append(f"   • Owner/Lot mismatch")
        else:
            logs.append(f"\n⚠️  Kiểm tra các vấn đề trên!")

        logs.append(f"\n\n🔧 HÀNH ĐỘNG TRỢ GIÚP")
        logs.append(f"1. Thử bấm 'Kiểm tra tình trạng còn hàng' (action_assign) lại")
        logs.append(f"2. Nếu vẫn fail, vào move line chọn tay vị trí và số lượng")
        logs.append(f"3. Hoặc check xem có move/picking khác giữ quant không")

        self.debug_log = "\n".join(logs)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_force_assign(self):
        """
        Cố gắng force assign từng move.
        """
        self.ensure_one()
        picking = self.picking_id

        logs = []
        logs.append("🔧 FORCE ASSIGN ATTEMPT\n")

        for move in picking.move_ids:
            if move.state in ['done', 'cancel']:
                logs.append(f"⏭️  {move.name}: Bỏ qua (state={move.state})")
                continue

            try:
                move._action_assign()
                logs.append(f"✅ {move.name}: Assign thành công (state={move.state})")
            except Exception as e:
                logs.append(f"❌ {move.name}: {str(e)[:80]}")

        self.debug_log += "\n" + "\n".join(logs)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
