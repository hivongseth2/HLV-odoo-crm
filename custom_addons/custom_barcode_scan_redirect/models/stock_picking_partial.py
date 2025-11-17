# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class StockPickingPartial(models.Model):
    _inherit = "stock.picking"

    # Lưu trạng thái partial pack
    partial_pack_id = fields.Many2one(
        "stock.picking",
        string="Partial Pack From",
        help="Nếu đây là partial pack, lưu picking gốc"
    )
    partial_pack_ids = fields.One2many(
        "stock.picking",
        "partial_pack_id",
        string="Partial Packs",
        help="Danh sách các partial packs tạo từ picking này"
    )
    
    # Trạng thái unpack (để biết có thể unpack hay không)
    is_partial_packed = fields.Boolean(
        string="Is Partial Packed",
        default=False,
        help="True nếu picking đã được partial pack (hoàn tất một phần)"
    )

    def create_partial_pack(self, move_line_data):
        """
        Tạo gói hàng (package) từ các move_line hoàn tất
        move_line_data: [
            {'move_line_id': int, 'qty': float},
            ...
        ]
        Cơ chế: Không tạo phiếu mới, chỉ tạo stock.quant.package và gán vào result_package_id
        """
        self.ensure_one()
        
        if self.state not in ['assigned', 'confirmed', 'in_progress']:
            raise ValidationError("Chỉ có thể tạo gói từ các phiếu đã xác nhận hoặc đang làm!")
        
        # Tạo package mới (stock.quant.package) với tên từ sequence
        Package = self.env['stock.quant.package']
        
        # Lấy tên package từ ir.sequence hoặc tạo tên mặc định
        try:
            package_name = self.env['ir.sequence'].next_by_code('stock.quant.package')
        except:
            # Fallback: nếu sequence không tồn tại, dùng định dạng PACK + số
            count = Package.search_count([])
            package_name = f"PACK{count + 1:07d}"
        
        new_package = Package.create({
            'name': package_name,
        })
        
        # Cập nhật result_package_id cho các move_line hoàn tất
        for data in move_line_data:
            move_line_id = data.get('move_line_id')
            
            move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
            if not move_line.exists():
                continue
            
            # Gán package cho move_line này
            move_line.result_package_id = new_package.id
        
        return {
            'package_id': new_package.id,
            'package_name': new_package.name,
        }


    def unpack_partial(self):
        """
        Unpack: chuyển items từ partial pack này về lại picking gốc
        """
        self.ensure_one()
        
        if not self.partial_pack_id:
            raise ValidationError("Đây không phải là partial pack!")
        
        # Đặt lại qty_done về 0 cho move_lines trong picking gốc
        for move_line in self.move_line_ids:
            # Tìm move_line gốc
            if move_line.original_move_line_id:
                origin_ml = move_line.original_move_line_id
                origin_ml.qty_done += move_line.qty_done
        
        # Hủy picking partial
        self.action_cancel()
        return True

    def add_to_pack(self, move_line_data):
        """
        Thêm items vào pack này từ picking gốc
        move_line_data: [{'move_line_id': int, 'qty': float}, ...]
        """
        self.ensure_one()
        
        if not self.partial_pack_id:
            raise ValidationError("Chỉ có thể thêm vào partial pack!")
        
        for data in move_line_data:
            move_line_id = data.get('move_line_id')
            qty = data.get('qty', 0)
            
            if qty <= 0:
                continue
            
            origin_move_line = self.partial_pack_id.move_line_ids.sudo().browse(move_line_id)
            if not origin_move_line.exists():
                continue
            
            # Kiểm tra qty khả dụng
            available_qty = origin_move_line.product_uom_qty - origin_move_line.qty_done
            add_qty = min(qty, available_qty)
            
            # Thêm vào current pack
            existing = self.move_line_ids.filtered(
                lambda ml: ml.product_id == origin_move_line.product_id
            )
            if existing:
                existing[0].qty_done += add_qty
            else:
                # Tạo move_line mới
                target_move = self.move_ids.filtered(
                    lambda m: m.product_id == origin_move_line.product_id
                )
                if not target_move:
                    target_move = origin_move_line.move_id.copy({
                        'picking_id': self.id,
                        'product_uom_qty': add_qty,
                    })
                
                origin_move_line.copy({
                    'move_id': target_move.id,
                    'qty_done': add_qty,
                    'original_move_line_id': origin_move_line.id,
                })
            
            # Cập nhật origin
            origin_move_line.qty_done += add_qty

    def transfer_pack_item(self, target_pack_id, move_line_data):
        """
        Chuyển items từ pack này sang pack khác
        """
        self.ensure_one()
        target_pack = self.env['stock.picking'].sudo().browse(target_pack_id)
        
        if not target_pack.exists():
            raise ValidationError("Pack đích không tồn tại!")
        
        for data in move_line_data:
            move_line_id = data.get('move_line_id')
            qty = data.get('qty', 0)
            
            if qty <= 0:
                continue
            
            move_line = self.move_line_ids.sudo().browse(move_line_id)
            if not move_line.exists():
                continue
            
            # Giảm qty từ pack hiện tại
            move_line.qty_done -= qty
            
            # Thêm vào pack đích
            target_existing = target_pack.move_line_ids.filtered(
                lambda ml: ml.product_id == move_line.product_id
            )
            if target_existing:
                target_existing[0].qty_done += qty
            else:
                target_move = target_pack.move_ids.filtered(
                    lambda m: m.product_id == move_line.product_id
                )
                if not target_move:
                    target_move = move_line.move_id.copy({
                        'picking_id': target_pack.id,
                        'product_uom_qty': qty,
                    })
                
                move_line.copy({
                    'move_id': target_move.id,
                    'qty_done': qty,
                    'original_move_line_id': move_line.original_move_line_id,
                })
