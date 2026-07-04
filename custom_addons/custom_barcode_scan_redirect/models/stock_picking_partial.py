from odoo import api, fields, models
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

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
        Cơ chế: 
        - Nếu package_name là mã của package đã tồn tại → thêm sản phẩm vào package đó
        - Nếu không tồn tại → tạo package mới với tên từ sequence
        """
        self.ensure_one()
        
        if self.state not in ['assigned', 'confirmed', 'in_progress']:
            raise ValidationError("Chỉ có thể tạo gói từ các phiếu đã xác nhận hoặc đang làm!")
        
        self.env.cr.execute(
            "SELECT id FROM stock_move WHERE picking_id = %s ORDER BY id FOR UPDATE",
            (self.id,),
        )
        self.env.cr.execute(
            "SELECT id FROM stock_move_line WHERE picking_id = %s ORDER BY id FOR UPDATE",
            (self.id,),
        )
        self.env.invalidate_all()
        self = self.browse(self.id)

        Package = self.env['stock.quant.package']
        
        # ⭐ NEW: Kiểm tra xem package_name có tồn tại không
        existing_package = None
        if package_name and package_name.startswith("PACK"):
            # Tìm package theo tên
            existing_package = Package.sudo().search([
                ('name', '=', package_name)
            ], limit=1)
        
        # Nếu package đã tồn tại, sử dụng package đó
        if existing_package:
            new_package = existing_package
        else:
            # Tạo package mới với tên từ sequence
            try:
                pkg_name = self.env['ir.sequence'].next_by_code('stock.quant.package')
            except Exception:
                count = Package.search_count([])
                pkg_name = f"PACK{count + 1:07d}"
            new_package = Package.create({'name': pkg_name})

        # Xử lý từng move_line: tạo move_line mới cho phần được pack (qty),
        # giảm qty_done trên move_line nguồn để giữ phần còn lại cho các pack tiếp theo.
        # Xử lý từng yêu cầu đóng gói
        for data in move_line_data:
            move_line_id = data.get('move_line_id')
            qty_needed = float(data.get('qty', 0) or 0)
            
            if qty_needed <= 0:
                continue

            ref_ml = self.env['stock.move.line'].sudo().browse(move_line_id)
            if not ref_ml.exists():
                continue

            product_id = ref_ml.product_id.id
            
            # 1. ƯU TIÊN LẤY TỪ HÀNG LẺ (LOOSE LINES) TRƯỚC
            # Tìm tất cả line chưa đóng gói của sản phẩm này
            # [FIX] Bỏ điều kiện qty_done > 0 trong domain vì qty_done có thể không store -> Lỗi SQL
            all_loose_lines = self.env['stock.move.line'].sudo().search([
                ('picking_id', '=', self.id),
                ('product_id', '=', product_id),
                ('result_package_id', '=', False),
            ]) 
            
            # Filter và Sort bằng Python
            loose_lines = all_loose_lines.filtered(lambda l: l.qty_done > 0).sorted(key=lambda l: l.qty_done)
            
            _logger.info(f"[PACK] Product {product_id} Need {qty_needed}. Found {len(loose_lines)} loose lines.")

            for loose_ml in loose_lines:
                if qty_needed <= 0:
                    break
                    
                available = loose_ml.qty_done
                take_qty = min(qty_needed, available)
                _logger.info(f"   -> Loose ML {loose_ml.id} has {available}. Taking {take_qty}")
                
                # Logic đưa vào pack
                if take_qty == available:
                    # Lấy hết dòng lẻ -> Gán luôn vào pack
                    loose_ml.sudo().with_context(skip_qty_validation=True).write({
                        'result_package_id': new_package.id
                    })
                else:
                    # Lấy 1 phần -> Tách ra
                    loose_ml.sudo().with_context(skip_qty_validation=True).copy({
                        'qty_done': take_qty,
                        'result_package_id': new_package.id,
                    })
                    loose_ml.sudo().with_context(skip_qty_validation=True).write({
                        'qty_done': available - take_qty
                    })
                
                qty_needed -= take_qty
            
            _logger.info(f"[PACK] After loose Check, Need: {qty_needed}")

            if qty_needed > 0:
                raise ValidationError(
                    "Khong du so luong chua dong goi cho %s. "
                    "Vui long tai lai man hinh hoac bam Lam lai truoc khi tao kien."
                    % (ref_ml.product_id.display_name,)
                )

        # [NEW] Trả về thông tin đồng bộ (Global Packed Qty) để frontend tự sửa
        sync_info = []
        # Lấy danh sách sản phẩm liên quan đến các line vừa đóng gói
        # (Ở đây ta lấy hết sản phẩm trong picking để đồng bộ cho chắc, hoặc chỉ các sp trong gói mới)
        # Lấy các sp trong gói mới:
        package_products = new_package.quant_ids.mapped('product_id') 
        # Tuy nhiên quant_ids có thể chưa cập nhật ngay nếu chưa done? 
        # Dùng move_line_ids của gói thì chuẩn hơn.
        # Nhưng move_line chưa có quan hệ ngược trực tiếp ra gói nhanh?
        # Search ngược (Use SUDO to ensure visibility of changes made by sudo just now)
        # [FIX] Force flush to ensure DB has the latest move_line updates (result_package_id)
        self.env['stock.move.line'].flush_model(['result_package_id', 'qty_done'])
        
        related_lines = self.env['stock.move.line'].sudo().search([
            ('result_package_id', '=', new_package.id)
        ])
        related_products = related_lines.mapped('product_id')
        
        for product in related_products:
            # Tính tổng đã đóng gói (Global) - Use SUDO
            packed_qty = sum(self.env['stock.move.line'].sudo().search([
                ('picking_id', '=', self.id),
                ('product_id', '=', product.id),
                ('result_package_id', '!=', False)
            ]).mapped('qty_done'))
            
            _logger.info(f"[PACK-SYNC] Product {product.display_name} (ID: {product.id}) -> Packed: {packed_qty}")

            sync_info.append({
                'product_id': product.id,
                'product_barcode': product.barcode,
                'product_sku': product.default_code,
                'packed_qty': packed_qty
            })

        _logger.info(f"[PACK-RESULT] Created Package {new_package.name} (ID: {new_package.id}). Sync Info: {sync_info}")

        return {
            'package_id': new_package.id,
            'package_name': new_package.name,
            'sync_info': sync_info
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
        """
        self.ensure_one()

        Package = self.env['stock.quant.package']
        package = Package.sudo().browse(package_id)

        if not package.exists():
            raise ValidationError("Gói hàng không tồn tại!")

        # Lấy move_lines của package này
        move_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('result_package_id', '=', package_id)
        ])

        # Lấy TẤT CẢ move_lines của picking
        all_move_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id)
        ])

        # --- 1. XỬ LÝ ITEMS TRONG GÓI ---
        items = []
        for ml in move_lines:
            qty = float(ml.qty_done or 0)
            if qty <= 0:
                continue
            
            # Lấy thông tin mã
            # Note: Nên dùng '' thay vì 'N/A' để JS check if(code) chuẩn hơn
            product_barcode = ml.product_id.barcode or ''
            product_sku = ml.product_id.default_code or ''

            items.append({
                'move_line_id': ml.id,
                'product_id': ml.product_id.id,
                'product_name': ml.product_id.name,
                'product_sku': product_sku,         # Default Code
                'product_barcode': product_barcode, # Barcode
                'qty_done': qty,
                'uom': ml.product_uom_id.name,
            })

        # --- 2. XỬ LÝ DANH SÁCH GÓI KHÁC ---
        all_packages_in_picking = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('result_package_id', '!=', False)
        ]).mapped('result_package_id')

        other_packages = []
        for pkg in all_packages_in_picking:
            if pkg.id != package_id:
                pkg_name = pkg.name if pkg.name else f"PACK{pkg.id}"
                other_packages.append({
                    'package_id': pkg.id,
                    'package_name': pkg_name
                })

        # --- 3. XỬ LÝ ALL ITEMS (DROPDOWN THÊM SẢN PHẨM) ---
        all_items = []
        product_map = {}

        # A. Quét từ Move Lines
        for ml in all_move_lines:
            pid = ml.product_id.id
            if pid not in product_map:
                product_map[pid] = {
                    'product_name': ml.product_id.name,
                    # [FIX QUAN TRỌNG] Thêm 2 dòng này để tránh KeyError
                    'product_sku': ml.product_id.default_code or '', 
                    'product_barcode': ml.product_id.barcode or '',
                    # ------------------------------------------------
                    'move_line_id': ml.id,
                    'total_scanned': 0.0,
                    'unassigned_scanned': 0.0,
                    'demand': 0.0
                }
            
            qty = float(ml.qty_done or 0)
            product_map[pid]['total_scanned'] += qty
            
            if not ml.result_package_id and qty > 0:
                product_map[pid]['unassigned_scanned'] += qty

        # B. Quét từ Demand (Moves without package)
        for move in self.move_ids_without_package:
             pid = move.product_id.id
             if pid in product_map:
                 product_map[pid]['demand'] += move.product_uom_qty
             elif pid not in product_map:
                 product_map[pid] = {
                    'product_name': move.product_id.name,
                    'product_sku': move.product_id.default_code or '',
                    'product_barcode': move.product_id.barcode or '',
                    'move_line_id': False, 
                    'total_scanned': 0.0,
                    'unassigned_scanned': 0.0,
                    'demand': move.product_uom_qty
                }

        # C. Tổng hợp lại thành list
        for pid, data in product_map.items():
            qty_available = data['unassigned_scanned']

            if qty_available > 0:
                ml_id = data['move_line_id']
                if not ml_id:
                    tmp_ml = self.env['stock.move.line'].sudo().search([
                        ('picking_id', '=', self.id),
                        ('product_id', '=', pid)
                    ], limit=1)
                    if tmp_ml:
                        ml_id = tmp_ml.id
                
                if ml_id:
                    all_items.append({
                        'move_line_id': ml_id,
                        'product_id': pid,
                        'product_name': data['product_name'],
                        # Bây giờ data[] đã có đủ key nên không bị lỗi nữa
                        'product_sku': data['product_sku'],         
                        'product_barcode': data['product_barcode'],
                        'qty_available': qty_available
                    })

        # D. Tạo thông tin Sync UI (Để frontend tự sửa data-packed-qty)
        sync_info = []
        for pid, data in product_map.items():
            total = data['total_scanned']
            unassigned = data['unassigned_scanned']
            packed_qty = total - unassigned
            
            # Chỉ gửi nếu có packed_qty (hoặc gửi hết cũng được để sync chuẩn 100%)
            sync_info.append({
                'product_id': pid,
                'product_barcode': data['product_barcode'],
                'product_sku': data['product_sku'],
                'packed_qty': packed_qty
            })

        return {
            'package_id': package.id,
            'package_name': package.name,
            'items': items,
            'other_packages': other_packages,
            'all_items': all_items,
            'sync_info': sync_info # [NEW]
        }
    def update_package_item_qty(self, package_id, move_line_id, new_qty):
        """
        Cập nhật số lượng của 1 sản phẩm trong package
        LOGIC MỚI: Nếu giảm số lượng -> Tách phần giảm ra thành hàng lẻ (Unpack), không xóa mất qty_done
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
        
        # Trường hợp tăng số lượng: kiểm tra available như cũ
        if new_qty > old_qty:
            # Lấy move gốc để kiểm tra qty_done tối đa
            original_move = move_line.move_id
            if original_move:
                total_current_done = sum(ml.qty_done for ml in original_move.move_line_ids)
                available_qty = original_move.product_uom_qty - (total_current_done - old_qty)
                
                if new_qty > available_qty:
                    raise ValidationError(f"⚠️ Số lượng không được vượt quá {available_qty:.2f} (tối đa cho sản phẩm này)")
            
            move_line.with_context(skip_qty_validation=True).write({'qty_done': new_qty})
            
        # Trường hợp giảm số lượng: Unpack phần thừa
        elif new_qty < old_qty:
            diff = old_qty - new_qty
            
            # 1. Cập nhật dòng hiện tại trong package
            if new_qty == 0:
                # Nếu giảm về 0 -> Unpack toàn bộ (chỉ cần xóa result_package_id)
                move_line.with_context(skip_qty_validation=True).write({'result_package_id': False})
            else:
                # Giảm dòng trong package
                move_line.with_context(skip_qty_validation=True).write({'qty_done': new_qty})
                
                # 2. Tạo dòng mới cho phần thừa (Unpack)
                # Check xem đã có dòng lẻ nào cho SP này chưa để merge? (Optional, nhưng tốt cho data)
                # Để an toàn và đơn giản, cứ copy ra dòng mới, Odoo sẽ tự xử lý hoặc user thấy 2 dòng cũng ko sao.
                # Nhưng tốt nhất là nên check dòng lẻ có sẵn.
                
                existing_loose_line = self.env['stock.move.line'].sudo().search([
                    ('picking_id', '=', self.id),
                    ('product_id', '=', move_line.product_id.id),
                    ('result_package_id', '=', False),
                    ('location_id', '=', move_line.location_id.id),
                    ('location_dest_id', '=', move_line.location_dest_id.id),
                ], limit=1)
                
                if existing_loose_line:
                     existing_loose_line.with_context(skip_qty_validation=True).write({
                         'qty_done': existing_loose_line.qty_done + diff
                     })
                else:
                    move_line.with_context(skip_qty_validation=True).copy({
                        'qty_done': diff,
                        'result_package_id': False
                    })

        return {
            'success': True,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'message': f"Cập nhật thành công: {old_qty} → {new_qty}"
        }

    def remove_package_item(self, package_id, move_line_id):
        """
        Xoá 1 sản phẩm khỏi package -> LOGIC MỚI: UNPACK (Bỏ khỏi kiện, giữ nguyên qty_done)
        """
        self.ensure_one()
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if move_line.result_package_id.id != package_id:
            raise ValidationError("Move line này không thuộc package này!")
        
        # UNPACK: Chỉ cần set result_package_id = False
        move_line.with_context(skip_qty_validation=True).write({
            'result_package_id': False,
            # 'qty_done': 0  <-- KHÔNG set về 0 nữa
        })
        
        # Merge vào dòng lẻ có sẵn nếu muốn đẹp data (Optional but recommended)
        # ... (Có thể làm sau, hiện tại tách ra là được)
        
        return {
            'success': True,
            'message': f"Đã bỏ sản phẩm khỏi kiện (vẫn giữ trạng thái đã quét)"
        }

    def transfer_package_item(self, from_package_id, to_package_id, move_line_id, qty):
        """
        Chuyển 1 sản phẩm từ package này sang package khác
        """
        self.ensure_one()
        
        # [FIX] Enforce Skip Validation Context
        ctx = dict(self.env.context)
        ctx['skip_qty_validation'] = True
        
        # Kiểm tra to_package_id khác from_package_id
        if from_package_id == to_package_id:
            raise ValidationError("Gói nguồn và gói đích phải khác nhau!")
        
        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")
        
        if move_line.result_package_id.id != from_package_id:
            raise ValidationError("Move line này không thuộc package nguồn!")
        
        if qty <= 0 or qty > move_line.qty_done:
            raise ValidationError("Số lượng chuyển không hợp lệ!")
        
        # Kiểm tra to_package_id có tồn tại và thuộc cùng picking không
        to_package = self.env['stock.quant.package'].sudo().browse(to_package_id)
        if not to_package.exists():
            raise ValidationError("Gói đích không tồn tại!")
        
        to_ml_exists = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('result_package_id', '=', to_package_id)
        ], limit=1)
        if not to_ml_exists:
            raise ValidationError("Gói đích không có trong phiếu này hoặc không hợp lệ!")
        
        # Cập nhật package hiện tại
        new_qty = move_line.qty_done - qty
        update_vals = {'qty_done': new_qty}
        if new_qty == 0:
            update_vals['result_package_id'] = False
            
        move_line.with_context(ctx).write(update_vals)
        
        # Kiểm tra xem sản phẩm có trong package đích không
        # [FIX] Must match move_id to avoid merging unrelated lines (e.g. merging 10-line into 6-line)
        existing_in_target = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('product_id', '=', move_line.product_id.id),
            ('result_package_id', '=', to_package_id),
            ('move_id', '=', move_line.move_id.id)
        ], limit=1)
        
        if existing_in_target:
            # Cộng vào sản phẩm hiện có
            existing_in_target.with_context(ctx).write({
                'qty_done': existing_in_target.qty_done + qty
            })
        else:
            # Tạo move_line mới cho package đích
            new_move_line = move_line.with_context(ctx).copy({
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
        Logic MỚI: 
        1. CHỈ lấy từ Unassigned Scanned (đã quét nhưng chưa vào gói)
        2. KHÔNG tự động quét thêm (không lấy từ Unscanned)
        """
        self.ensure_one()

        move_line = self.env['stock.move.line'].sudo().browse(move_line_id)
        if not move_line.exists() or move_line.picking_id.id != self.id:
            raise ValidationError("Move line không tồn tại!")

        if qty <= 0:
            raise ValidationError("Số lượng thêm phải > 0!")

        product = move_line.product_id

        # ⭐ Bước 1: Lấy thông tin tổng quan
        all_product_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('product_id', '=', product.id),
        ])

        # Tính unassigned scanned
        unassigned_lines = all_product_lines.filtered(lambda ml: not ml.result_package_id and ml.qty_done > 0)
        total_unassigned = sum(float(ml.qty_done or 0) for ml in unassigned_lines)
        
        # Tổng khả dụng để thêm = chỉ tính hàng đã quét chưa đóng gói
        qty_available = total_unassigned

        # ⭐ Bước 2: Validate
        if qty > qty_available:
            raise ValidationError(
                f"⚠️ Không thể thêm {qty} vào package.\n"
                f"• Chưa đóng gói (đã quét): {total_unassigned}\n"
                f"• Yêu cầu: Bạn phải quét sản phẩm ở màn hình chính trước khi thêm vào gói!"
            )

        # ⭐ Bước 3: Thực hiện thêm
        remaining_qty_to_add = qty
        
        # 3.1: Lấy từ Unassigned Scanned
        if total_unassigned > 0:
            sorted_unassigned = unassigned_lines.sorted(key=lambda l: l.id)
            
            for ml in sorted_unassigned:
                if remaining_qty_to_add <= 0:
                    break
                
                available = float(ml.qty_done or 0)
                take = min(remaining_qty_to_add, available)
                
                # Tìm dòng trong package đích
                dest_line = all_product_lines.filtered(lambda l: l.result_package_id.id == package_id and l.id != ml.id)
                
                if dest_line:
                    # [FIX] Giảm source TRƯỚC khi tăng đích để tránh vượt quá demand (Trigger constraints)
                    if take == available:
                        ml.with_context(skip_qty_validation=True).unlink() # Hết qty -> xóa
                    else:
                        ml.with_context(skip_qty_validation=True).write({'qty_done': ml.qty_done - take})
                        
                    # Merge vào dest_line
                    dest_line[0].with_context(skip_qty_validation=True).write({
                        'qty_done': dest_line[0].qty_done + take
                    })
                else:
                    # Không có dòng đích
                    if take == available:
                        ml.with_context(skip_qty_validation=True).write({'result_package_id': package_id})
                    else:
                        # Tách dòng
                        ml.with_context(skip_qty_validation=True).write({'qty_done': ml.qty_done - take})
                        ml.with_context(skip_qty_validation=True).copy({
                            'qty_done': take,
                            'result_package_id': package_id
                        })
                
                remaining_qty_to_add -= take

        return {
            'success': True,
            'message': f"✅ Đã thêm {qty} x {product.name} vào package"
        }

    def _reduce_unassigned_qty(self, product, qty_to_reduce):
        """
        Giảm qty từ các move_line chưa được gán package cho sản phẩm cụ thể
        """
        # Lấy các move_line của sản phẩm này chưa được gán package
        unassigned_lines = self.env['stock.move.line'].sudo().search([
            ('picking_id', '=', self.id),
            ('product_id', '=', product.id),
            ('result_package_id', '=', False)
        ], order='id desc')

        remaining_qty = qty_to_reduce

        for line in unassigned_lines:
            if remaining_qty <= 0:
                break

            # ⭐ Filter bằng Python - chỉ xử lý lines có qty_done > 0
            qty_done = float(line.qty_done or 0)
            if qty_done <= 0:
                continue

            reduce_qty = min(remaining_qty, qty_done)
            line.qty_done -= reduce_qty
            remaining_qty -= reduce_qty

        if remaining_qty > 0:
            # Nếu vẫn còn thiếu, lấy từ các dòng đã có package (nhưng không phải package hiện tại)
            other_package_lines = self.env['stock.move.line'].sudo().search([
                ('picking_id', '=', self.id),
                ('product_id', '=', product.id),
                ('result_package_id', '!=', False)
            ], order='id desc')

            for line in other_package_lines:
                if remaining_qty <= 0:
                    break

                # ⭐ Filter bằng Python - chỉ xử lý lines có qty_done > 0
                qty_done = float(line.qty_done or 0)
                if qty_done <= 0:
                    continue

                reduce_qty = min(remaining_qty, qty_done)
                line.qty_done -= reduce_qty
                remaining_qty -= reduce_qty

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
