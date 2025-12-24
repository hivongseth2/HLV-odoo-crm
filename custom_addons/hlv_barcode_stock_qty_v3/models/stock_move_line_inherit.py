# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _check_barcode_qty_limit(self, new_qty_done, product_id, move_id=None, exclude_line_id=None):
        """
        Kiểm tra xem tổng qty_done có vượt quá demand không

        :param new_qty_done: Số lượng mới sẽ được thêm vào
        :param product_id: ID sản phẩm
        :param move_id: ID của move (để lấy demand)
        :param exclude_line_id: ID của dòng cần exclude khi tính tổng (dùng cho write)
        :return: True nếu vượt quá, False nếu OK
        """
        if not move_id:
            return False

        move = self.env['stock.move'].browse(move_id)
        demand = move.product_uom_qty

        # Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên) vì demand luôn = 0
        if move.picking_id and move.picking_id.name and 'INT' in move.picking_id.name:
            return False

        if demand <= 0:
            return False
        
        # Tính tổng qty_done hiện tại của tất cả các dòng cùng product và move
        domain = [
            ('move_id', '=', move_id),
            ('product_id', '=', product_id),
            ('state', 'not in', ['done', 'cancel']),
        ]
        
        if exclude_line_id:
            domain.append(('id', '!=', exclude_line_id))
        
        existing_lines = self.search(domain)
        total_current_qty = sum(existing_lines.mapped('qty_done'))
        
        # Tổng sau khi thêm
        total_after = total_current_qty + new_qty_done
        
        if total_after > demand:
            product = self.env['product.product'].browse(product_id)
            raise UserError(_(
                '⚠️ KHÔNG THỂ QUÉT VƯỢT QUÁ SỐ LƯỢNG!\n\n'
                '📦 Sản phẩm: %s\n'
                '📋 Số lượng đặt hàng: %.2f %s\n'
                '✅ Đã quét: %.2f %s\n'
                '❌ Đang cố quét thêm: %.2f %s\n'
                '🔴 Tổng sẽ vượt quá: %.2f %s\n\n'
                '👉 Vui lòng CHỈ quét đúng số lượng đã đặt hàng!'
            ) % (
                product.display_name,
                demand, move.product_uom.name,
                total_current_qty, move.product_uom.name,
                new_qty_done, move.product_uom.name,
                total_after, move.product_uom.name,
            ))
        
        return False

    def write(self, vals):
        """
        Override write để chặn việc tăng qty_done vượt quá demand
        """
        # Bypass validation nếu được gọi từ packaging context
        if self.env.context.get('skip_qty_validation'):
            return super(StockMoveLine, self).write(vals)
            
        if 'qty_done' in vals and not self.env.context.get('skip_qty_validation'):
            for line in self:
                increment = vals['qty_done'] - line.qty_done
                if increment > 0:
                    # [CŨ] Check Demand
                    if line.move_id:
                        self._check_barcode_qty_limit(increment, line.product_id.id, line.move_id.id, exclude_line_id=line.id)
                    
                    # [MỚI] Check Stock tại Source Location
                    # Lưu ý: Lấy location_id của dòng (nếu có) hoặc của move
                    source_loc_id = line.location_id.id or line.move_id.location_id.id
                    self._check_source_location_stock(line.product_id.id, source_loc_id, increment)

        return super(StockMoveLine, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create để kiểm tra khi tạo dòng mới từ barcode scan
        """
        # Bypass validation nếu được gọi từ packaging context
        if self.env.context.get('skip_qty_validation'):
            return super(StockMoveLine, self).create(vals_list)
            
        for vals in vals_list:
            if not self.env.context.get('skip_qty_validation'):
                qty_done = vals.get('qty_done', 0)
                product_id = vals.get('product_id')
                move_id = vals.get('move_id')
                location_id = vals.get('location_id')

                if qty_done > 0 and product_id:
                    # [CŨ] Check Demand
                    if move_id:
                        self._check_barcode_qty_limit(qty_done, product_id, move_id)
                    
                    # [MỚI] Check Stock tại Source Location
                    # Nếu line không có location, lấy từ move (cần browse move nếu location_id trống)
                    check_loc_id = location_id
                    if not check_loc_id and move_id:
                        check_loc_id = self.env['stock.move'].browse(move_id).location_id.id
                    
                    if check_loc_id:
                        self._check_source_location_stock(product_id, check_loc_id, qty_done)
        
        return super(StockMoveLine, self).create(vals_list)
    
    def _check_source_location_stock(self, product_id, location_id, qty_to_add):
        """
        Kiểm tra xem vị trí nguồn (location_id) có đủ hàng không.
        Nếu không, raise UserError và gợi ý vị trí khác.
        """
        if not location_id or not product_id:
            return

        # Chỉ check nếu vị trí nguồn là kho nội bộ (Internal)
        # Bỏ qua Supplier, Customer, Inventory loss, v.v.
        location = self.env['stock.location'].browse(location_id)
        if location.usage != 'internal':
            return

        # Bỏ qua nếu cấu hình cho phép xuất âm (tùy nhu cầu, ở đây ta chặn chặt)
        # Lấy tồn kho hiện tại ở vị trí đó
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
        ], limit=1)

        # Số lượng hiện có (bao gồm cả reserved vì ta đang thao tác trên line thực tế)
        # Tuy nhiên logic chuẩn: check available_quantity hoặc quantity
        # Ở đây dùng quantity (on-hand) để báo hết hàng vật lý
        current_on_hand = quant.quantity if quant else 0

        # Nếu tồn < 0 hoặc (tồn hiện tại + lượng sắp thêm vẫn <= 0) thì coi như không có hàng
        # Logic đơn giản: Nếu on-hand <= 0 thì báo lỗi ngay
        if current_on_hand <= 0:
            product = self.env['product.product'].browse(product_id)
            
            # Tìm gợi ý
            suggestions = self.env['stock.quant'].get_alternative_locations(product_id, location_id)
            
            msg = _(
                '⚠️ CẢNH BÁO: KHÔNG CÓ HÀNG TẠI VỊ TRÍ NÀY!\n\n'
                '📍 Vị trí quét: %s\n'
                '📦 Sản phẩm: %s\n'
                '❌ Tồn kho hiện tại: %.2f\n'
            ) % (location.display_name, product.display_name, current_on_hand)

            if suggestions:
                msg += _('\n💡 GỢI Ý CÁC VỊ TRÍ CÓ HÀNG:\n%s') % suggestions
            else:
                msg += _('\n⛔ Không tìm thấy hàng ở bất kỳ vị trí nào khác trong kho!')

            raise UserError(msg)

