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
    
    def _get_current_datetime(self):
        """Lấy thời điểm hiện tại"""
        return fields.Datetime.now()

    def _get_warehouse_locations(self):
        """Lấy danh sách location của các kho được chọn"""
        if self.warehouse_ids:
            warehouses = self.warehouse_ids
        else:
            warehouses = self.env['stock.warehouse'].search([])
        
        # Lấy tất cả location thuộc kho (internal type)
        location_ids = []
        for wh in warehouses:
            # Lấy view_location_id và tất cả location con
            if wh.lot_stock_id:
                location_ids.append(wh.lot_stock_id.id)
                # Tìm tất cả location con
                child_locs = self.env['stock.location'].search([
                    ('id', 'child_of', wh.lot_stock_id.id),
                    ('usage', '=', 'internal')
                ])
                location_ids.extend(child_locs.ids)
        
        return list(set(location_ids))

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

    def _get_outgoing_qty_between(self, product_id, location_ids, start_datetime, end_datetime):
        """
        Tính tổng số lượng xuất kho từ start_datetime đến end_datetime
        
        Logic: Tìm tất cả move có source là location_ids NHƯNG destination KHÔNG phải location_ids
        (tức là hàng đi từ kho này ra ngoài - bất kể đi đâu: customer, transit, scrap, v.v.)
        """
        # Tìm các stock.move xuất khỏi kho
        # Điều kiện: location_id IN location_ids AND location_dest_id NOT IN location_ids
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_id', 'in', location_ids),
        ])
        
        # Lọc thủ công: chỉ lấy move có destination không nằm trong location_ids
        # (tức là xuất ra ngoài kho, không phải di chuyển nội bộ trong cùng kho)
        outgoing_moves = moves.filtered(lambda m: m.location_dest_id.id not in location_ids)
        
        total_qty = sum(outgoing_moves.mapped('product_uom_qty'))
        
        # Debug logging
        if moves and not outgoing_moves:
            _logger.warning(
                f"Product {product_id}: Found {len(moves)} moves but 0 outgoing moves. "
                f"All moves are internal transfers within location_ids {location_ids}"
            )
        elif outgoing_moves:
            _logger.info(
                f"Product {product_id}: Found {len(outgoing_moves)} outgoing moves, total qty: {total_qty}. "
                f"Pickings: {', '.join(outgoing_moves.mapped('picking_id.name'))}"
            )
        
        return total_qty

    def _get_incoming_qty_between(self, product_id, location_ids, start_datetime, end_datetime):
        """
        Tính tổng số lượng nhập kho từ start_datetime đến end_datetime
        Bao gồm tất cả nguồn: nhập từ supplier, trả hàng, inter-warehouse transit, v.v.
        
        Logic: Tìm tất cả move có destination là location_ids NHƯNG source KHÔNG phải location_ids
        (tức là hàng đi từ nơi khác vào kho này)
        """
        # Tìm các stock.move nhập vào kho
        # Điều kiện: location_dest_id IN location_ids AND location_id NOT IN location_ids
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_dest_id', 'in', location_ids),
        ])
        
        # Lọc thủ công: chỉ lấy move có source không nằm trong location_ids
        incoming_moves = moves.filtered(lambda m: m.location_id.id not in location_ids)
        
        total_qty = sum(incoming_moves.mapped('product_uom_qty'))
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
        Trả về: string danh sách mã đơn cách nhau bởi dấu phẩy, ví dụ: "WH/OUT/00123, WH/OUT/00124"
        
        Logic: Giống hệt _get_outgoing_qty_between để đảm bảo consistency
        """
        # Tìm các stock.move xuất khỏi kho
        moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('location_id', 'in', location_ids),
        ], order='date asc')
        
        # Lọc: chỉ lấy move xuất ra ngoài (destination không trong location_ids)
        outgoing_moves = moves.filtered(lambda m: m.location_dest_id.id not in location_ids)
        
        # Lấy danh sách picking names (unique)
        picking_names = []
        seen_picking_ids = set()
        
        for move in outgoing_moves:
            if move.picking_id and move.picking_id.id not in seen_picking_ids:
                picking_names.append(move.picking_id.name)
                seen_picking_ids.add(move.picking_id.id)
        
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
            {'key': 'picking_names', 'name': 'Chi tiết đơn xuất', 'width': 50},
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

            # Wrap text for 'picking_names' column
            picking_names_cell = ws.cell(row=row_idx, column=9)  # Column 9 is 'picking_names'
            picking_names_cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)

        ws.row_dimensions[HEADER_ROW].height = 35

        return wb

    def action_export(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'pip install openpyxl'."))

        # Lấy thông tin thời gian
        start_of_day = self._get_start_of_day(self.report_date)
        current_datetime = self._get_current_datetime()
        
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
        
        for product in products.sorted(key=lambda p: p.default_code or p.name):
            # Tính tồn đầu ngày
            qty_start = self._get_product_qty_at_datetime(product.id, location_ids, start_of_day)
            
            # Tính số lượng nhập từ đầu ngày đến hiện tại
            qty_in = self._get_incoming_qty_between(product.id, location_ids, start_of_day, current_datetime)
            
            # Tính số lượng xuất từ đầu ngày đến hiện tại
            qty_out = self._get_outgoing_qty_between(product.id, location_ids, start_of_day, current_datetime)
            
            # Tính tồn hiện tại
            qty_current = self._get_product_qty_at_datetime(product.id, location_ids, current_datetime)
            
            # Bỏ qua sản phẩm không có tồn và không có xuất nhập
            if qty_start == 0 and qty_in == 0 and qty_out == 0 and qty_current == 0:
                continue
            
            # Lấy danh sách mã đơn xuất kho
            picking_names = self._get_product_outgoing_picking_names(
                product.id, location_ids, start_of_day, current_datetime
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
                'picking_names': picking_names,
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
