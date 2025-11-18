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

    def create_partial_pack(self, move_line_data, package_name=None):
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
        
        # Tạo package mới (stock.quant.package) với tên từ sequence hoặc tên cung cấp
        Package = self.env['stock.quant.package']

        # Luôn dùng tên từ sequence, bỏ qua AUTO-PKG hoặc bất kỳ tên truyền từ JS
        try:
            pkg_name = self.env['ir.sequence'].next_by_code('stock.quant.package')
        except Exception:
            count = Package.search_count([])
            pkg_name = f"PACK{count + 1:07d}"

        new_package = Package.create({'name': pkg_name})

        # Xử lý từng move_line: tạo move_line mới cho phần được pack (qty),
        # giảm qty_done trên move_line nguồn để giữ phần còn lại cho các pack tiếp theo.
        for data in move_line_data:
            move_line_id = data.get('move_line_id')
            qty = float(data.get('qty', 0) or 0)

            move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
            if not move_line.exists() or qty <= 0:
                continue

            # Nếu source move_line có đủ qty_done để tách
            src_done = float(move_line.qty_done or 0.0)
            take_qty = min(qty, src_done)

            if take_qty <= 0:
                # không còn qty_done trên dòng nguồn; skip
                continue

            # Luôn tạo move_line mới cho package, không gán trực tiếp move_line nguồn vào package
            move_line.sudo().copy({
                'qty_done': take_qty,
                'result_package_id': new_package.id,
            })

            # Giảm qty_done trên dòng nguồn
            remaining = src_done - take_qty
            move_line.sudo().write({'qty_done': remaining})
        
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

    def get_package_details(self, package_id):
        """
        Lấy chi tiết sản phẩm trong 1 package để hiển thị modal edit
        Returns: {
            'package_id': int,
            'package_name': str,
            'items': [
                {'move_line_id': int, 'product_id': int, 'product_name': str, 'qty_done': float, 'uom': str},
                ...
            ]
        }
        """
        self.ensure_one()
        
        Package = self.env['stock.quant.package']
        package = Package.sudo().browse(package_id)
        
        if not package.exists():
            raise ValidationError("Gói hàng không tồn tại!")
        
        # Lấy tất cả move_lines của picking này và package này
        move_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('result_package_id', '=', package_id)
        ])
        
        items = []
        for ml in move_lines:
            items.append({
                'move_line_id': ml.id,
                'product_id': ml.product_id.id,
                'product_name': ml.product_id.name,
                'qty_done': ml.qty_done,
                'uom': ml.product_uom_id.name,
            })
        
        return {
            'package_id': package.id,
            'package_name': package.name,
            'items': items,
        }

    def update_package_item_qty(self, package_id, move_line_id, new_qty):
        """
        Cập nhật số lượng của 1 sản phẩm trong package
        """
        self.ensure_one()
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if move_line.result_package_id.id != package_id:
            raise ValidationError("Move line này không thuộc package này!")
        
        if new_qty < 0:
            raise ValidationError("Số lượng không được âm!")
        
        old_qty = move_line.qty_done
        move_line.qty_done = new_qty
        
        return {
            'success': True,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'message': f"Cập nhật thành công: {old_qty} → {new_qty}"
        }

    def remove_package_item(self, package_id, move_line_id):
        """
        Xoá 1 sản phẩm khỏi package (đặt qty_done = 0 và xoá result_package_id)
        """
        self.ensure_one()
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if move_line.result_package_id.id != package_id:
            raise ValidationError("Move line này không thuộc package này!")
        
        # Xoá khỏi package
        move_line.result_package_id = None
        move_line.qty_done = 0
        
        return {
            'success': True,
            'message': f"Đã xoá sản phẩm khỏi package"
        }

    def transfer_package_item(self, from_package_id, to_package_id, move_line_id, qty):
        """
        Chuyển 1 sản phẩm từ package này sang package khác
        """
        self.ensure_one()
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if move_line.result_package_id.id != from_package_id:
            raise ValidationError("Move line này không thuộc package nguồn!")
        
        if qty <= 0 or qty > move_line.qty_done:
            raise ValidationError("Số lượng chuyển không hợp lệ!")
        
        # Cập nhật package hiện tại
        move_line.qty_done -= qty
        if move_line.qty_done == 0:
            move_line.result_package_id = None
        
        # Kiểm tra xem sản phẩm có trong package đích không
        existing_in_target = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('product_id', '=', move_line.product_id.id),
            ('result_package_id', '=', to_package_id)
        ], limit=1)
        
        if existing_in_target:
            # Cộng vào sản phẩm hiện có
            existing_in_target.qty_done += qty
        else:
            # Tạo move_line mới cho package đích
            new_move_line = move_line.copy({
                'result_package_id': to_package_id,
                'qty_done': qty,
            })
        
        return {
            'success': True,
            'message': f"Chuyển {qty} sang package đích thành công"
        }

    def add_item_to_package(self, package_id, move_line_id, qty):
        """
        Thêm sản phẩm vào package (bổ sung sau, quét thêm)
        move_line_id là item chưa được gán vào package nào hoặc đã có quantity khả dụng
        """
        self.ensure_one()
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if qty <= 0:
            raise ValidationError("Số lượng thêm phải > 0!")
        
        # Kiểm tra có chỗ trống có sẵn không
        existing_in_target = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('product_id', '=', move_line.product_id.id),
            ('result_package_id', '=', package_id)
        ], limit=1)
        
        if existing_in_target:
            # Cộng vào sản phẩm hiện có
            existing_in_target.qty_done += qty
            move_line.qty_done -= qty
            if move_line.qty_done == 0:
                move_line.result_package_id = None
        else:
            # Tạo move_line mới hoặc di chuyển
            move_line.qty_done -= qty
            new_move_line = move_line.copy({
                'result_package_id': package_id,
                'qty_done': qty,
            })
            if move_line.qty_done == 0:
                move_line.result_package_id = None
        
        return {
            'success': True,
            'message': f"Thêm {qty} vào package thành công"
        }

    def split_package_to_new_picking(self, package_id):
        """
        Tách 1 package thành phiếu mới (tương tự tách đơn trong bán hàng)
        Cơ chế:
        - Tạo 1 stock.picking mới (cùng picking_type, partner, locations)
        - Tính tổng qty_done đã tách cho mỗi sản phẩm
        - Copy move cho phần tách (với product_uom_qty = tổng qty_done tách)
        - Copy move_line sang picking mới với qty_done = qty_done tách
        - Trên original move: tính remaining planned qty = product_uom_qty - tổng qty_done tách
          và cập nhật move gốc
        - Xóa move_line đã tách khỏi original picking
        - Trả về id, name của picking mới
        """
        self.ensure_one()

        Package = self.env['stock.quant.package']
        package = Package.sudo().browse(package_id)
        if not package.exists():
            raise ValidationError("Gói hàng không tồn tại!")

        # Lấy tất cả move_line trong picking thuộc package này
        ml_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('result_package_id', '=', package_id)
        ])

        if not ml_lines:
            raise ValidationError("Không có sản phẩm nào trong gói để tách!")

        # Tạo 1 picking mới kế thừa một số thông tin
        new_picking_vals = {
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'partner_id': self.partner_id.id or False,
            'origin': (self.origin or self.name) + (f'/{package.name}' if package.name else ''),
            'move_type': self.move_type,
            'group_id': self.group_id and self.group_id.id or False,
        }
        new_picking = self.env['stock.picking'].sudo().create(new_picking_vals)

        # Track moved quantities and move_lines by original move
        # For each original move, we need to know total qty_done being moved out
        moved_by_move = {}  # {move_id: {'move': move_obj, 'moved_qty': total, 'move_lines': [...]}}
        moved_ml_ids = []

        for ml in ml_lines:
            if ml.qty_done <= 0:
                continue

            orig_move = ml.move_id
            moved_qty = float(ml.qty_done or 0.0)

            # Track this move_line for removal later
            if orig_move.id not in moved_by_move:
                moved_by_move[orig_move.id] = {
                    'move': orig_move,
                    'moved_qty': 0.0,
                    'move_lines': []
                }
            moved_by_move[orig_move.id]['moved_qty'] += moved_qty
            moved_by_move[orig_move.id]['move_lines'].append(ml)
            moved_ml_ids.append(ml.id)

        # Now process each original move: create new move with moved qty, 
        # and update original move's planned qty
        for orig_move_id, info in moved_by_move.items():
            orig_move = info['move']
            total_moved_qty = float(info['moved_qty'] or 0.0)
            move_lines_to_move = info['move_lines']

            # Create a new move in the new picking with qty = total moved
            new_move = orig_move.copy({
                'picking_id': new_picking.id,
                'product_uom_qty': total_moved_qty,
            })

            # For each move_line, copy it to the new move/picking
            for ml in move_lines_to_move:
                new_ml = ml.copy({
                    'move_id': new_move.id,
                    'qty_done': ml.qty_done,
                    'result_package_id': package.id,
                })

            # Update original move's planned qty: reduce it by the moved qty
            # Remaining planned qty = original planned qty - total moved qty_done
            try:
                orig_planned_qty = float(orig_move.product_uom_qty or 0.0)
            except Exception:
                orig_planned_qty = 0.0
            
            remaining_planned_qty = orig_planned_qty - total_moved_qty
            if remaining_planned_qty < 0:
                remaining_planned_qty = 0.0
            
            orig_move.sudo().write({'product_uom_qty': remaining_planned_qty})

        # Remove moved move_lines from original picking
        if moved_ml_ids:
            self.env['stock.move.line'].sudo().browse(moved_ml_ids).unlink()

        # Try to assign new picking
        try:
            new_picking.action_assign()
        except Exception:
            pass

        return {'picking_id': new_picking.id, 'picking_name': new_picking.name}
