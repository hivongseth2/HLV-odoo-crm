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
        
        # Chỉ check với outgoing transfer
        if move.picking_id.picking_type_code != 'outgoing':
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
        if 'qty_done' in vals:
            for line in self:
                current_qty = line.qty_done
                new_qty = vals['qty_done']
                increment = new_qty - current_qty
                
                if increment > 0 and line.move_id:
                    self._check_barcode_qty_limit(
                        increment,
                        line.product_id.id,
                        line.move_id.id,
                        exclude_line_id=line.id
                    )
        
        return super(StockMoveLine, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create để kiểm tra khi tạo dòng mới từ barcode scan
        """
        for vals in vals_list:
            qty_done = vals.get('qty_done', 0)
            product_id = vals.get('product_id')
            move_id = vals.get('move_id')
            
            if qty_done > 0 and product_id and move_id:
                self._check_barcode_qty_limit(
                    qty_done,
                    product_id,
                    move_id,
                    exclude_line_id=None
                )
        
        return super(StockMoveLine, self).create(vals_list)

