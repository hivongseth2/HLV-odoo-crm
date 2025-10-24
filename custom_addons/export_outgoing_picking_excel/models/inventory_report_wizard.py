# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import datetime
from io import BytesIO
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.styles.numbers import FORMAT_NUMBER_COMMA_SEPARATED1
except ImportError:
    Workbook = None


class InventoryReportWizard(models.TransientModel):
    _name = "inventory.report.wizard"
    _description = "Xuất báo cáo tồn kho Excel"

    report_date = fields.Date(
        string="Ngày báo cáo", 
        required=True, 
        default=fields.Date.context_today,
        help="Báo cáo sẽ tính tồn đầu ngày (0h) và tồn cuối tại thời điểm xuất file"
    )
    
    warehouse_ids = fields.Many2many(
        "stock.warehouse",
        string="Kho",
        help="Để trống = Tất cả kho. Chọn 1 hoặc nhiều kho để lọc cụ thể.",
    )

    def _get_start_of_day(self, date_val):
        """Lấy thời điểm bắt đầu ngày (0h)"""
        return datetime.datetime.combine(date_val, datetime.time.min)
    
    def _get_end_of_day(self, date_val):
        """Lấy thời điểm cuối ngày (23h59:59)"""
        return datetime.datetime.combine(date_val, datetime.time.max)
    
    def _get_current_datetime(self):
        """Lấy thời điểm hiện tại"""
        return fields.Datetime.now()
    
    def _get_report_end_datetime(self):
        """
        Lấy thời điểm kết thúc cho báo cáo:
        - Nếu ngày báo cáo = hôm nay: lấy thời điểm hiện tại
        - Nếu ngày báo cáo < hôm nay: lấy 23h59:59 của ngày đó
        """
        today = fields.Date.context_today(self)
        if self.report_date >= today:
            return self._get_current_datetime()
        else:
            return self._get_end_of_day(self.report_date)

    def _get_warehouse_locations(self):
        """
        Lấy danh sách location của các kho được chọn, bao gồm TẤT CẢ child locations
        NHƯNG PHẢI loại trừ transit locations để tính xuất/nhập đúng
        
        ⚠️ QUAN TRỌNG: Nếu transit location nằm trong location_ids:
        - Move KHD → Transit: cả source và dest đều trong location_ids → KHÔNG tính xuất
        - Move Transit → KBC: cả source và dest đều trong location_ids → KHÔNG tính nhập
        → KẾT QUẢ: Mất hết dữ liệu inter-warehouse transfer!
        """
        if self.warehouse_ids:
            warehouses = self.warehouse_ids
        else:
            warehouses = self.env['stock.warehouse'].search([])
        
        # Lấy tất cả location thuộc kho, bao gồm cả sub-locations
        location_ids = []
        excluded_count = 0
        
        for wh in warehouses:
            # Lấy view_location_id để tìm tất cả location con
            if wh.view_location_id:
                # Tìm TẤT CẢ location con có usage = internal HOẶC transit
                # (Vì một số hệ thống đặt transit usage = 'internal')
                child_locs = self.env['stock.location'].search([
                    ('id', 'child_of', wh.view_location_id.id),
                    '|',
                    ('usage', '=', 'internal'),
                    ('usage', '=', 'transit')
                ])
                
                # 🔧 LOẠI BỎ TRANSIT: Kiểm tra nhiều điều kiện
                # Bao gồm: usage='transit' HOẶC tên chứa 'transit', 'inter-warehouse', etc.
                filtered_locs = child_locs.filtered(
                    lambda loc: (
                        loc.usage != 'transit'  # ✓ Loại bỏ usage = transit
                        and 'transit' not in loc.complete_name.lower() 
                        and 'inter-warehouse' not in loc.complete_name.lower()
                        and 'inter warehouse' not in loc.complete_name.lower()
                        and not loc.name.lower().startswith('inter')
                        # Thêm điều kiện: location có parent là warehouse transit
                        and (not loc.location_id or 'transit' not in loc.location_id.complete_name.lower())
                    )
                )
                
                excluded_locs = child_locs - filtered_locs
                excluded_count += len(excluded_locs)
                
                location_ids.extend(filtered_locs.ids)
                
                _logger.info(
                    f"✓ Warehouse {wh.name}: Included {len(filtered_locs)} locations, "
                    f"Excluded {len(excluded_locs)} transit locations"
                )
                if excluded_locs:
                    _logger.info(
                        f"  ✗ Excluded transit locations: "
                        f"{', '.join([f'{loc.complete_name} (usage:{loc.usage})' for loc in excluded_locs])}"
                    )
                if filtered_locs:
                    _logger.info(
                        f"  ✓ Included locations: "
                        f"{', '.join([f'{loc.complete_name} (usage:{loc.usage})' for loc in filtered_locs])}"
                    )
        
        location_ids = list(set(location_ids))
        _logger.info(
            f"📦 Total warehouse locations: {len(location_ids)} (excluded {excluded_count} transit locations)"
        )
        
        return location_ids

    def _get_product_qty_at_datetime(self, product_id, location_ids, target_datetime):
        """
        Tính số lượng tồn kho của product tại thời điểm target_datetime
        Sử dụng stock.quant và stock.move để tính toán
        """
        # Lấy tồn kho hiện tại
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product_id),
            ('location_id', 'in', location_ids),
        ])
        
        current_qty = sum(quants.mapped('quantity'))
        
        # Tìm các stock.move đã hoàn thành SAU target_datetime
        # để trừ ngược lại và tính tồn tại target_datetime
        moves_after = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>', target_datetime),
            '|',
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'in', location_ids),
        ])
        
        adjustment = 0
        for move in moves_after:
            # Nếu move vào kho (location_dest_id in location_ids) -> trừ đi
            if move.location_dest_id.id in location_ids and move.location_id.id not in location_ids:
                adjustment -= move.product_uom_qty
            # Nếu move ra khỏi kho (location_id in location_ids) -> cộng lại
            elif move.location_id.id in location_ids and move.location_dest_id.id not in location_ids:
                adjustment += move.product_uom_qty
            # Nếu move nội bộ (cả 2 đều trong location_ids) -> không ảnh hưởng
        
        return current_qty + adjustment

    def _get_outgoing_qty_between(self, product_id, location_ids, start_datetime, end_datetime, log_locations=False):
        """
        Tính tổng số lượng xuất kho từ start_datetime đến end_datetime
        
        Logic: Tính các move xuất RA KHỎI kho (destination không trong location_ids)
        Bao gồm: xuất đến customer, transit, packing zone bên ngoài kho, etc.
        """
        # Log location_ids để debug (chỉ log 1 lần khi được yêu cầu)
        if log_locations:
            location_objs = self.env['stock.location'].browse(location_ids)
            _logger.info(
                f"🗂️ Location IDs in scope ({len(location_ids)} locations): "
                f"{', '.join([f'{loc.complete_name} (ID:{loc.id}, Usage:{loc.usage})' for loc in location_objs])}"
            )
        
        # Tìm các stock.move xuất khỏi kho
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_id', 'in', location_ids),
        ])
        
        # Lọc: lấy move xuất ra ngoài kho (destination không trong location_ids)
        # 🔧 FIX: Bao gồm cả move có location_dest_id = location_id (bug dữ liệu)
        # NHƯNG có move_dest_ids link sang kho khác (inter-warehouse transfer)
        outgoing_moves = moves.filtered(
            lambda m: m.location_dest_id.id not in location_ids or
            (m.move_dest_ids and any(
                dest_move.location_dest_id.id not in location_ids 
                for dest_move in m.move_dest_ids
            ))
        )
        
        total_qty = sum(outgoing_moves.mapped('product_uom_qty'))
        
        # Debug logging - ENHANCED
        if moves:
            internal_moves = moves - outgoing_moves
            _logger.info(
                f"📤 Product {product_id}: Total {len(moves)} moves from warehouse, "
                f"{len(outgoing_moves)} are OUTGOING (qty: {total_qty}), "
                f"{len(internal_moves)} are INTERNAL transfers (ignored)"
            )
            
            if outgoing_moves:
                for move in outgoing_moves:
                    _logger.info(
                        f"  ✓ Outgoing: {move.picking_id.name if move.picking_id else 'N/A'}, "
                        f"Qty: {move.product_uom_qty}, "
                        f"From: {move.location_id.complete_name} (ID:{move.location_id.id}) → "
                        f"To: {move.location_dest_id.complete_name} (ID:{move.location_dest_id.id}, "
                        f"Usage:{move.location_dest_id.usage})"
                    )
            
            if internal_moves:
                _logger.warning(
                    f"  ⚠️ Ignored {len(internal_moves)} internal moves (both source & dest in location_ids):"
                )
                for move in internal_moves:
                    # Kiểm tra xem có phải move_dest_ids có picking khác không (inter-warehouse)
                    has_dest_picking = bool(move.move_dest_ids and move.move_dest_ids.filtered(lambda m: m.picking_id))
                    dest_picking_info = ""
                    if has_dest_picking:
                        dest_pickings = move.move_dest_ids.mapped('picking_id')
                        dest_picking_info = f", Linked to: {', '.join(dest_pickings.mapped('name'))}"
                    
                    _logger.warning(
                        f"    → Picking: {move.picking_id.name if move.picking_id else 'N/A'} "
                        f"(Move ID: {move.id}, Type: {move.picking_id.picking_type_id.code if move.picking_id and move.picking_id.picking_type_id else 'N/A'}), "
                        f"Qty: {move.product_uom_qty}, "
                        f"From: {move.location_id.complete_name} (ID:{move.location_id.id}, In list: {move.location_id.id in location_ids}) → "
                        f"To: {move.location_dest_id.complete_name} (ID:{move.location_dest_id.id}, Usage:{move.location_dest_id.usage}, "
                        f"In list: {move.location_dest_id.id in location_ids}){dest_picking_info}"
                    )
        
        return total_qty

    def _get_incoming_qty_between(self, product_id, location_ids, start_datetime, end_datetime):
        """
        Tính tổng số lượng nhập kho từ start_datetime đến end_datetime
        
        Logic: Tính TẤT CẢ move nhập VÀO kho (source không trong location_ids)
        Bao gồm: nhập từ supplier, trả hàng từ customer, nhận từ kho khác (transit), etc.
        """
        # Tìm các stock.move nhập vào kho
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_dest_id', 'in', location_ids),
        ])
        
        # Lọc: lấy TẤT CẢ move nhập từ bên ngoài vào kho (source không trong location_ids)
        # Bao gồm cả nhập từ transit/inter-warehouse transfer
        incoming_moves = moves.filtered(lambda m: m.location_id.id not in location_ids)
        
        total_qty = sum(incoming_moves.mapped('product_uom_qty'))
        
        # Debug logging - ENHANCED
        if moves:
            internal_moves = moves - incoming_moves
            _logger.info(
                f"📥 Product {product_id}: Total {len(moves)} moves to warehouse, "
                f"{len(incoming_moves)} are INCOMING (qty: {total_qty}), "
                f"{len(internal_moves)} are INTERNAL transfers (ignored)"
            )
            
            if incoming_moves:
                for move in incoming_moves:
                    _logger.info(
                        f"  ✓ Incoming: {move.picking_id.name if move.picking_id else 'N/A'}, "
                        f"Qty: {move.product_uom_qty}, "
                        f"From: {move.location_id.complete_name} (ID:{move.location_id.id}, "
                        f"Usage:{move.location_id.usage}) → "
                        f"To: {move.location_dest_id.complete_name} (ID:{move.location_dest_id.id})"
                    )
            
            if internal_moves:
                _logger.warning(
                    f"  ⚠️ Ignored {len(internal_moves)} internal moves (both source & dest in location_ids):"
                )
                for move in internal_moves:
                    # Kiểm tra xem có phải move_orig_ids có picking khác không (inter-warehouse source)
                    has_orig_picking = bool(move.move_orig_ids and move.move_orig_ids.filtered(lambda m: m.picking_id))
                    orig_picking_info = ""
                    if has_orig_picking:
                        orig_pickings = move.move_orig_ids.mapped('picking_id')
                        orig_picking_info = f", Linked from: {', '.join(orig_pickings.mapped('name'))}"
                    
                    _logger.warning(
                        f"    → Picking: {move.picking_id.name if move.picking_id else 'N/A'} "
                        f"(Move ID: {move.id}, Type: {move.picking_id.picking_type_id.code if move.picking_id and move.picking_id.picking_type_id else 'N/A'}), "
                        f"Qty: {move.product_uom_qty}, "
                        f"From: {move.location_id.complete_name} (ID:{move.location_id.id}, In list: {move.location_id.id in location_ids}) → "
                        f"To: {move.location_dest_id.complete_name} (ID:{move.location_dest_id.id}, Usage:{move.location_dest_id.usage}, "
                        f"In list: {move.location_dest_id.id in location_ids}){orig_picking_info}"
                    )
        
        return total_qty

    def _get_all_products_with_movement(self, location_ids, start_datetime):
        """
        Lấy tất cả sản phẩm có tồn kho hoặc có phát sinh từ start_datetime
        """
        # Sản phẩm có tồn kho hiện tại
        quants = self.env['stock.quant'].search([
            ('location_id', 'in', location_ids),
            ('quantity', '!=', 0),
        ])
        product_ids = set(quants.mapped('product_id').ids)
        
        # Sản phẩm có phát sinh từ start_datetime
        moves = self.env['stock.move'].search([
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            '|',
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'in', location_ids),
        ])
        product_ids.update(moves.mapped('product_id').ids)
        
        return list(product_ids)

    def _get_product_outgoing_picking_names(self, product_id, location_ids, start_datetime, end_datetime):
        """
        Lấy danh sách tên (mã) các picking xuất kho của sản phẩm trong khoảng thời gian
        Trả về: string danh sách mã đơn cách nhau bởi dấu phẩy
        
        Logic: 
        - Lấy TẤT CẢ picking xuất ra khỏi location_ids (bao gồm cả xuất sang transit)
        - Nếu xuất sang inter-warehouse transit, tìm thêm picking nhận ở kho đích
        """
        # Tìm TẤT CẢ các stock.move xuất khỏi kho (bao gồm location_id trong location_ids)
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_id', 'in', location_ids),
        ], order='date asc')
        
        # 🔧 FIX: Lấy TẤT CẢ move xuất từ kho (destination không trong location_ids)
        # Bao gồm CẢ move xuất sang transit location
        # VÀ cả move có bug dữ liệu (location_dest = location_id) nhưng có link đến kho khác
        outgoing_moves = moves.filtered(
            lambda m: m.location_dest_id.id not in location_ids or
            (m.move_dest_ids and any(
                dest_move.location_dest_id.id not in location_ids 
                for dest_move in m.move_dest_ids
            ))
        )
        
        picking_names = []
        seen_picking_ids = set()
        
        for move in outgoing_moves:
            if not move.picking_id:
                continue
            
            picking = move.picking_id
            
            # Thêm picking xuất
            if picking.id not in seen_picking_ids:
                picking_names.append(picking.name)
                seen_picking_ids.add(picking.id)
                
                dest_location = move.location_dest_id
                dest_usage = dest_location.usage
                
                _logger.info(
                    f"Product {product_id} - Outgoing Move in Picking {picking.name}: "
                    f"From: {move.location_id.complete_name} (ID: {move.location_id.id}) -> "
                    f"To: {dest_location.complete_name} (ID: {dest_location.id}, Usage: {dest_usage})"
                )
                
                # Kiểm tra xem có phải là inter-warehouse transfer không
                # 🔧 FIX: Bao gồm cả trường hợp move có bug (dest = source) nhưng có move_dest_ids
                is_transit = (
                    dest_usage == 'transit' or 
                    'transit' in dest_location.complete_name.lower() or
                    'inter-warehouse' in dest_location.complete_name.lower() or
                    (move.location_dest_id.id == move.location_id.id and move.move_dest_ids)  # Bug data case
                )
                
                if is_transit or move.move_dest_ids:
                    # Tìm picking nhận ở kho đích qua move_dest_ids
                    dest_picking = self._find_destination_picking_from_move(move)
                    if dest_picking and dest_picking.id not in seen_picking_ids:
                        picking_names.append(dest_picking.name)
                        seen_picking_ids.add(dest_picking.id)
                        _logger.info(
                            f"Product {product_id} - Found destination picking: {dest_picking.name}"
                        )
        
        return ', '.join(picking_names) if picking_names else ''

    def _find_destination_picking_from_move(self, outgoing_move):
        """
        Tìm picking nhận ở kho đích cho move xuất qua transit
        Sử dụng move_dest_ids để tìm chính xác
        """
        # Phương pháp 1: Qua move_dest_ids (linked moves) - ĐÁNG TIN CẬY NHẤT
        if outgoing_move.move_dest_ids:
            for dest_move in outgoing_move.move_dest_ids:
                if dest_move.picking_id and dest_move.state == 'done':
                    _logger.info(
                        f"✓ Found linked destination move via move_dest_ids: {dest_move.picking_id.name}, "
                        f"From: {dest_move.location_id.complete_name} -> "
                        f"To: {dest_move.location_dest_id.complete_name}"
                    )
                    return dest_move.picking_id
        
        # Phương pháp 2: Tìm qua location_dest_id của outgoing_move
        # Nếu outgoing_move đi đến transit, tìm move tiếp theo từ transit
        transit_location_id = outgoing_move.location_dest_id.id
        
        # 🔧 Nới rộng điều kiện tìm kiếm để bắt được các move nhận từ transit
        dest_moves = self.env['stock.move'].search([
            ('product_id', '=', outgoing_move.product_id.id),
            ('state', '=', 'done'),
            ('location_id', '=', transit_location_id),
            ('date', '>=', outgoing_move.date),  # Phải sau hoặc cùng lúc với move xuất
            ('date', '<=', outgoing_move.date + datetime.timedelta(days=2)),  # Trong vòng 2 ngày
        ], order='date asc', limit=1)
        
        if dest_moves and dest_moves.picking_id:
            _logger.info(
                f"✓ Found destination move via transit search: {dest_moves.picking_id.name}, "
                f"From: {dest_moves.location_id.complete_name} -> To: {dest_moves.location_dest_id.complete_name}"
            )
            return dest_moves.picking_id
        
        _logger.warning(
            f"✗ Could not find destination picking for outgoing move {outgoing_move.picking_id.name} "
            f"to transit location {outgoing_move.location_dest_id.complete_name}"
        )
        return None

    def _get_product_incoming_picking_names(self, product_id, location_ids, start_datetime, end_datetime):
        """
        Lấy danh sách tên (mã) các picking nhập kho của sản phẩm trong khoảng thời gian
        Trả về: string danh sách mã đơn cách nhau bởi dấu phẩy, ví dụ: "WH/IN/00123, WH/IN/00124, KBC/INT/00456"
        
        Logic: Lấy TẤT CẢ picking nhập vào kho, bao gồm cả inter-warehouse transfer
        """
        # Tìm các stock.move nhập vào kho
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_dest_id', 'in', location_ids),
        ], order='date asc')
        
        # Lọc: lấy TẤT CẢ move nhập từ bên ngoài vào kho
        incoming_moves = moves.filtered(lambda m: m.location_id.id not in location_ids)
        
        # Lấy danh sách picking names
        picking_names = []
        seen_picking_ids = set()
        
        for move in incoming_moves:
            if not move.picking_id:
                continue
                
            picking = move.picking_id
            
            if picking.id not in seen_picking_ids:
                picking_names.append(picking.name)
                seen_picking_ids.add(picking.id)
                
                # Debug logging
                _logger.info(
                    f"Product {product_id} - Incoming Picking: {picking.name}, "
                    f"Type: {picking.picking_type_id.code if picking.picking_type_id else 'N/A'}, "
                    f"From: {move.location_id.complete_name} -> To: {move.location_dest_id.complete_name}"
                )
        
        return ', '.join(picking_names) if picking_names else ''

    def _create_excel_workbook(self, data_rows):
        """Tạo workbook Excel với hyperlink đến picking"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Báo cáo tồn kho"

        # Định nghĩa cột
        columns = [
            {'key': 'stt', 'name': 'STT', 'width': 8},
            {'key': 'product_code', 'name': 'Mã hàng', 'width': 20},
            {'key': 'product_name', 'name': 'Tên hàng', 'width': 40},
            {'key': 'uom', 'name': 'ĐVT', 'width': 12},
            {'key': 'qty_start', 'name': 'Tồn đầu ngày (0h)', 'width': 20},
            {'key': 'qty_in', 'name': 'Số lượng nhập', 'width': 18},
            {'key': 'qty_out', 'name': 'Số lượng xuất', 'width': 18},
            {'key': 'qty_current', 'name': 'Tồn hiện tại', 'width': 18},
            {'key': 'incoming_picking_names', 'name': 'Chi tiết đơn nhập', 'width': 50},
            {'key': 'outgoing_picking_names', 'name': 'Chi tiết đơn xuất', 'width': 50},
        ]

        # Styles
        header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        border_side = Side(style='thin', color='000000')
        border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

        cell_alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
        number_alignment = Alignment(horizontal='right', vertical='center')

        # Header row
        HEADER_ROW = 1
        DATA_START = 2

        for col_idx, col_def in enumerate(columns, start=1):
            cell = ws.cell(row=HEADER_ROW, column=col_idx)
            cell.value = col_def['name']
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border
            ws.column_dimensions[get_column_letter(col_idx)].width = col_def.get('width', 15)

        # Data rows
        for row_idx, row_data in enumerate(data_rows, start=DATA_START):
            for col_idx, col_def in enumerate(columns, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                
                # Lấy giá trị
                value = row_data.get(col_def['key'], "")
                if value is None:
                    value = ""
                cell.value = value
                
                cell.border = border

                # Number formatting
                if col_def['key'] in ['qty_start', 'qty_in', 'qty_out', 'qty_current']:
                    cell.alignment = number_alignment
                    cell.number_format = '#,##0.00'
                elif col_def['key'] == 'stt':
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                else:
                    cell.alignment = cell_alignment

        # Wrap text for specific columns
        for row_idx in range(DATA_START, len(data_rows) + DATA_START):
            # Wrap text for 'product_name' column
            product_name_cell = ws.cell(row=row_idx, column=3)  # Column 3 is 'product_name'
            product_name_cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)

            # Wrap text for 'incoming_picking_names' column
            incoming_picking_names_cell = ws.cell(row=row_idx, column=9)  # Column 9 is 'incoming_picking_names'
            incoming_picking_names_cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)

            # Wrap text for 'outgoing_picking_names' column
            outgoing_picking_names_cell = ws.cell(row=row_idx, column=10)  # Column 10 is 'outgoing_picking_names'
            outgoing_picking_names_cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)

        ws.row_dimensions[HEADER_ROW].height = 35

        return wb

    def action_export(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'pip install openpyxl'."))

        # Lấy thông tin thời gian
        start_of_day = self._get_start_of_day(self.report_date)
        end_of_period = self._get_report_end_datetime()
        
        # Lấy danh sách location
        location_ids = self._get_warehouse_locations()
        if not location_ids:
            raise UserError(_("Không tìm thấy location kho nào."))

        # Lấy danh sách sản phẩm
        product_ids = self._get_all_products_with_movement(location_ids, start_of_day)
        if not product_ids:
            raise UserError(_("Không có sản phẩm nào có tồn kho hoặc phát sinh."))

        products = self.env['product.product'].browse(product_ids)
        
        # Tạo dữ liệu báo cáo
        data_rows = []
        stt = 1
        is_first_product = True
        
        for product in products.sorted(key=lambda p: p.default_code or p.name):
            # Tính tồn đầu ngày
            qty_start = self._get_product_qty_at_datetime(product.id, location_ids, start_of_day)
            
            # Tính số lượng nhập từ đầu ngày đến end_of_period
            qty_in = self._get_incoming_qty_between(product.id, location_ids, start_of_day, end_of_period)
            
            # Tính số lượng xuất từ đầu ngày đến end_of_period
            qty_out = self._get_outgoing_qty_between(product.id, location_ids, start_of_day, end_of_period, log_locations=is_first_product)
            is_first_product = False
            
            # Tính tồn tại end_of_period
            qty_current = self._get_product_qty_at_datetime(product.id, location_ids, end_of_period)
            
            # Bỏ qua sản phẩm không có tồn và không có xuất nhập
            if qty_start == 0 and qty_in == 0 and qty_out == 0 and qty_current == 0:
                continue
            
            # Lấy danh sách mã đơn nhập kho (chỉ picking nhập vào kho hiện tại)
            incoming_picking_names = self._get_product_incoming_picking_names(
                product.id, location_ids, start_of_day, end_of_period
            )
            
            # Lấy danh sách mã đơn xuất kho (bao gồm cả xuất sang transit/kho khác)
            outgoing_picking_names = self._get_product_outgoing_picking_names(
                product.id, location_ids, start_of_day, end_of_period
            )
            
            row = {
                'stt': stt,
                'product_code': product.default_code or '',
                'product_name': product.name or '',
                'uom': product.uom_id.name if product.uom_id else '',
                'qty_start': qty_start,
                'qty_in': qty_in,
                'qty_out': qty_out,
                'qty_current': qty_current,
                'incoming_picking_names': incoming_picking_names,
                'outgoing_picking_names': outgoing_picking_names,
            }
            data_rows.append(row)
            stt += 1

        if not data_rows:
            raise UserError(_("Không có dữ liệu để xuất báo cáo."))

        # Tạo Excel workbook
        wb = self._create_excel_workbook(data_rows)

        # Xuất file
        out = BytesIO()
        wb.save(out)
        out.seek(0)

        warehouse_names = ", ".join(self.warehouse_ids.mapped('name')) if self.warehouse_ids else "TatCaKho"
        filename = f"BaoCao_TonKho_{self.report_date}_{warehouse_names}.xlsx"
        
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "inventory.report.wizard",
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

