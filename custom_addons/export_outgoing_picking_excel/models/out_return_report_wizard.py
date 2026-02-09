# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import datetime
from io import BytesIO
from dateutil.relativedelta import relativedelta

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None


class OutReturnReportView(models.Model):
    """Báo cáo OUT + Trả hàng (Lưu trữ) - Cho phép xem danh sách trực tiếp"""
    _name = "out.return.report.view"
    _description = "Dữ liệu báo cáo xuất kho và trả hàng"
    _order = "out_picking_date desc, id"
    
    # Phiếu OUT
    out_picking_id = fields.Many2one("stock.picking", string="Phiếu xuất kho", required=True, ondelete='cascade')
    out_picking_name = fields.Char(string="Mã phiếu xuất")
    out_picking_date = fields.Datetime(string="Ngày xuất")
    partner_id = fields.Many2one("res.partner", string="Khách hàng")
    partner_name = fields.Char(string="Tên khách hàng")
    out_qty_total = fields.Float(string="Tổng SL xuất")
    
    # Phiếu trả hàng
    return_picking_id = fields.Many2one("stock.picking", string="Phiếu trả hàng")
    return_picking_name = fields.Char(string="Mã phiếu trả")
    return_picking_date = fields.Datetime(string="Ngày trả")
    has_return = fields.Boolean(string="Có trả hàng", default=False)
    return_qty_total = fields.Float(string="Tổng SL trả")
    
    # Chi tiết sản phẩm (nếu có trả)
    product_id = fields.Many2one("product.product", string="Sản phẩm")
    product_code = fields.Char(string="Mã SP")
    product_name = fields.Char(string="Tên SP")
    product_uom = fields.Char(string="ĐVT")
    out_qty = fields.Float(string="SL xuất")
    return_qty = fields.Float(string="SL trả")
    
    note = fields.Char(string="Ghi chú")

    def _get_product_qty_in_picking(self, picking, product_id):
        """Lấy số lượng của 1 sản phẩm trong picking"""
        qty = 0.0
        for move in picking.move_ids:
            if move.product_id.id == product_id:
                qty += move.quantity_done if hasattr(move, 'quantity_done') else move.product_uom_qty
        return qty


import logging
_logger = logging.getLogger(__name__)

# ... (existing imports)

# ... (OutReturnReportView class)

class OutReturnReportRefreshWizard(models.TransientModel):
    """Wizard cập nhật dữ liệu báo cáo"""
    _name = "out.return.report.refresh.wizard"
    _description = "Cập nhật dữ liệu báo cáo"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)
    warehouse_ids = fields.Many2many("stock.warehouse", string="Kho")

    def _get_out_pickings_domain(self):
        # Convert date to datetime to cover full day range
        start_date = fields.Datetime.to_datetime(self.date_from)
        end_date = fields.Datetime.to_datetime(self.date_to) + datetime.timedelta(days=1)
        
        domain = [
            ("date_done", ">=", start_date),
            ("date_done", "<", end_date),
            ("picking_type_id.sequence_code", "=", "OUT"),
            ("state", "=", "done"),
        ]
        if self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))
        
        _logger.info("Out Pickings Domain: %s", domain)
        return domain

    # ... (_find_return_pickings)

    def action_refresh_data(self):
        """Tính toán lại dữ liệu và lưu vào Model out.return.report.view"""
        self.ensure_one()
        ReportView = self.env["out.return.report.view"]
        
        _logger.info("ACTION REFRESH DATA: From %s To %s, Warehouses: %s", self.date_from, self.date_to, self.warehouse_ids.mapped('name'))
        
        # 1. Xóa dữ liệu cũ
        existing_domain = [
            ("out_picking_date", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("out_picking_date", "<=", fields.Datetime.to_datetime(self.date_to) + datetime.timedelta(days=1)),
        ]
        deleted_count = ReportView.search(existing_domain).unlink()
        _logger.info("Deleted %s existing report lines", len(deleted_count) if isinstance(deleted_count, list) else 'records')
        
        # 2. Tính toán mới
        domain = self._get_out_pickings_domain()
        out_pickings = self.env["stock.picking"].sudo().search(domain, order="date_done desc")
        
        _logger.info("Found %s OUT pickings", len(out_pickings))
        
        lines_data = []
        for out_picking in out_pickings:
            max_date = out_picking.date_done + relativedelta(months=1)
            return_pickings = self._find_return_pickings(out_picking, max_date)
            
            if return_pickings:
                _logger.info(">> Found Returns for OUT %s: %s", out_picking.name, return_pickings.mapped('name'))
                # ... (logic cũ)
                for return_picking in return_pickings:
                    return_qty_total = sum(return_picking.move_ids.mapped(
                        lambda m: m.quantity_done if hasattr(m, 'quantity_done') else m.product_uom_qty
                    ))
                    
                    for move in return_picking.move_ids:
                        product = move.product_id
                        return_qty = move.quantity_done if hasattr(move, 'quantity_done') else move.product_uom_qty
                        # Helper từ ReportView class cần được gọi thông qua instance hoặc copy logic
                        # Ở đây copy logic cho nhanh
                        out_qty = 0.0
                        for out_move in out_picking.move_ids:
                            if out_move.product_id.id == product.id:
                                out_qty += out_move.quantity_done if hasattr(out_move, 'quantity_done') else out_move.product_uom_qty

                        lines_data.append({
                            'out_picking_id': out_picking.id,
                            'out_picking_name': out_picking.name,
                            'out_picking_date': out_picking.date_done,
                            'partner_id': out_picking.partner_id.id if out_picking.partner_id else False,
                            'partner_name': out_picking.partner_id.name if out_picking.partner_id else '',
                            'out_qty_total': out_qty_total,
                            'return_picking_id': return_picking.id,
                            'return_picking_name': return_picking.name,
                            'return_picking_date': return_picking.date_done,
                            'has_return': True,
                            'return_qty_total': return_qty_total,
                            'product_id': product.id,
                            'product_code': product.default_code or '',
                            'product_name': product.name,
                            'product_uom': move.product_uom.name if move.product_uom else '',
                            'out_qty': out_qty,
                            'return_qty': return_qty,
                        })
        
        if lines_data:
            ReportView.create(lines_data)
            
        # Quay về view Report
        return {
            'type': 'ir.actions.act_window',
            'name': 'Báo cáo xuất kho và trả hàng',
            'res_model': 'out.return.report.view',
            'view_mode': 'list', # Odoo 18 dùng list view xml tag, nhưng view_mode vẫn là 'tree' hoặc 'list'?? Thực tế action thường dùng 'tree'
            'view_mode': 'tree,form',
            'target': 'current',
        }


class OutReturnReportExportWizard(models.TransientModel):
    """Wizard xuất Excel từ dữ liệu đã có"""
    _name = "out.return.report.export.wizard"
    _description = "Xuất Excel báo cáo"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    def action_export_excel(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl."))

        # Lấy dữ liệu từ Model ReportView theo ngày chọn
        # Lưu ý: Lọc theo out_picking_date
        domain = [
            ("out_picking_date", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("out_picking_date", "<=", fields.Datetime.to_datetime(self.date_to) + datetime.timedelta(days=1)),
            ("has_return", "=", True) # Chỉ lấy dòng có return như yêu cầu
        ]
        report_lines = self.env["out.return.report.view"].search(domain)
        
        if not report_lines:
            raise UserError(_("Không có dữ liệu trong khoảng thời gian này. Vui lòng chạy 'Cập nhật dữ liệu' trước."))

        wb = Workbook()
        
        # Styles
        header_font = Font(name='Arial', size=10, bold=True)
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        date_alignment = Alignment(horizontal='center', vertical='center')
        border_side = Side(style='thin', color='000000')
        border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)
        
        # ===== SHEET 1: CHI TIẾT PHIẾU XUẤT (OUT) =====
        ws1 = wb.active
        ws1.title = "Chi tiết phiếu xuất"
        
        columns1 = [
            {'key': 'stt', 'name': 'STT', 'width': 5},
            {'key': 'out_picking_name', 'name': 'Mã phiếu xuất', 'width': 15},
            {'key': 'origin', 'name': 'Mã báo giá', 'width': 15},
            {'key': 'out_picking_date', 'name': 'Ngày xuất', 'width': 15},
            {'key': 'partner_name', 'name': 'Khách hàng', 'width': 25},
            {'key': 'product_code', 'name': 'Mã SP', 'width': 15},
            {'key': 'product_name', 'name': 'Tên SP', 'width': 40},
            {'key': 'product_uom', 'name': 'ĐVT', 'width': 8},
            {'key': 'out_qty', 'name': 'SL xuất', 'width': 10},
            {'key': 'has_return', 'name': 'Có trả lại', 'width': 10},
        ]
        
        for col_idx, col_def in enumerate(columns1, start=1):
            cell = ws1.cell(row=1, column=col_idx)
            cell.value = col_def['name']
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = border
            ws1.column_dimensions[get_column_letter(col_idx)].width = col_def['width']
            
        # Get unique OUT picking IDs from report lines
        out_picking_ids = report_lines.mapped('out_picking_id')
        
        row_idx = 2
        stt = 1
        
        for out_picking in out_picking_ids:
            for move in out_picking.move_ids:
                # Check has_return logic again just to be safe (though report lines ensure it exists)
                # But we need to write "Có" or "Không"
                # Since we filtered report_lines with has_return=True, all these out_pickings HAVE returns
                has_return = True 
                
                ws1.cell(row=row_idx, column=1).value = stt
                ws1.cell(row=row_idx, column=2).value = out_picking.name
                ws1.cell(row=row_idx, column=3).value = out_picking.origin or ''
                ws1.cell(row=row_idx, column=4).value = out_picking.date_done.strftime('%d/%m/%Y') if out_picking.date_done else ''
                ws1.cell(row=row_idx, column=4).alignment = date_alignment
                ws1.cell(row=row_idx, column=5).value = out_picking.partner_id.name or ''
                ws1.cell(row=row_idx, column=6).value = move.product_id.default_code or ''
                ws1.cell(row=row_idx, column=7).value = move.product_id.name
                ws1.cell(row=row_idx, column=8).value = move.product_uom.name
                ws1.cell(row=row_idx, column=9).value = move.quantity_done if hasattr(move, 'quantity_done') else move.product_uom_qty
                ws1.cell(row=row_idx, column=10).value = 'Có'
                
                for col in range(1, 11):
                    ws1.cell(row=row_idx, column=col).border = border
                
                row_idx += 1
                stt += 1

        # ===== SHEET 2: CHI TIẾT PHIẾU TRẢ (RETURN) =====
        ws2 = wb.create_sheet("Chi tiết phiếu trả")
        
        columns2 = [
            {'key': 'stt', 'name': 'STT', 'width': 5},
            {'key': 'out_picking_name', 'name': 'Mã phiếu xuất gốc', 'width': 15},
            {'key': 'return_picking_name', 'name': 'Mã phiếu trả', 'width': 15},
            {'key': 'return_picking_date', 'name': 'Ngày trả', 'width': 15},
            {'key': 'partner_name', 'name': 'Khách hàng', 'width': 25},
            {'key': 'product_code', 'name': 'Mã SP', 'width': 15},
            {'key': 'product_name', 'name': 'Tên SP', 'width': 40},
            {'key': 'product_uom', 'name': 'ĐVT', 'width': 8},
            {'key': 'return_qty', 'name': 'SL trả', 'width': 10},
        ]
        
        for col_idx, col_def in enumerate(columns2, start=1):
            cell = ws2.cell(row=1, column=col_idx)
            cell.value = col_def['name']
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = border
            ws2.column_dimensions[get_column_letter(col_idx)].width = col_def['width']
            
        row_idx = 2
        stt = 1
        
        # Sort lines by return date
        sorted_lines = report_lines.sorted(key=lambda r: r.return_picking_date, reverse=True)
        
        for line in sorted_lines:
            ws2.cell(row=row_idx, column=1).value = stt
            ws2.cell(row=row_idx, column=2).value = line.out_picking_name
            ws2.cell(row=row_idx, column=3).value = line.return_picking_name
            ws2.cell(row=row_idx, column=4).value = line.return_picking_date.strftime('%d/%m/%Y') if line.return_picking_date else ''
            ws2.cell(row=row_idx, column=4).alignment = date_alignment
            ws2.cell(row=row_idx, column=5).value = line.partner_name
            ws2.cell(row=row_idx, column=6).value = line.product_code
            ws2.cell(row=row_idx, column=7).value = line.product_name
            ws2.cell(row=row_idx, column=8).value = line.product_uom
            ws2.cell(row=row_idx, column=9).value = line.return_qty
            
            for col in range(1, 10):
                ws2.cell(row=row_idx, column=col).border = border
            
            row_idx += 1
            stt += 1
            
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        
        filename = f"BaoCao_XuatKho_TraHang_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "out.return.report.export.wizard",
            "res_id": self.id,
        })
        
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

