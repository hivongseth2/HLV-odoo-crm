# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import datetime
import json
from io import BytesIO

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None


def _to_date_str(val):
    if not val:
        return ""
    if isinstance(val, str):
        try:
            d = fields.Datetime.from_string(val)
            if d:
                return d.strftime("%A, %B %d, %Y")
        except Exception:
            try:
                d2 = fields.Date.from_string(val)
                if d2:
                    return d2.strftime("%A, %B %d, %Y")
            except Exception:
                return val
        return val
    if isinstance(val, datetime.datetime):
        return val.strftime("%A, %B %d, %Y")
    if isinstance(val, datetime.date):
        return val.strftime("%A, %B %d, %Y")
    return str(val)


class StockExportWizard(models.TransientModel):
    _name = "stock.export.wizard"
    _description = "Xuất Excel Kho (Nội bộ & Xuất bán)"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)
    
    warehouse_ids = fields.Many2many(
        "stock.warehouse", string="Kho",
        help="Để trống để lấy tất cả kho trong công ty hiện tại."
    )
    
    picking_type_code = fields.Selection([
        ('outgoing', 'Xuất bán hàng'),
        ('internal', 'Nội bộ'),
        ('all', 'Tất cả'),
    ], string="Loại phiếu", default='all')
    
    state_filter = fields.Selection([
        ('done', 'Hoàn thành'),
        ('assigned', 'Sẵn sàng'),
        ('all', 'Tất cả')
    ], string="Trạng thái", default='done')

    def _get_warehouse_code(self, picking):
        """Lấy mã kho"""
        if picking.picking_type_id and picking.picking_type_id.warehouse_id:
            return picking.picking_type_id.warehouse_id.code
        # fallback source location
        loc = picking.location_id
        if loc and loc.warehouse_id:
            return loc.warehouse_id.code
        return ""

    def _partner_code(self, partner):
        if not partner:
            return ""
        return partner.ref or ""

    def _domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("date_done", ">=", fields.Date.to_date(self.date_from)),
            ("date_done", "<=", fields.Date.to_date(self.date_to)),
        ]
        
        # Picking Type Filter
        if self.picking_type_code == 'outgoing':
             domain.append(("picking_type_code", "=", "outgoing"))
        elif self.picking_type_code == 'internal':
             domain.append(("picking_type_code", "=", "internal"))
        else:
             domain.append(("picking_type_code", "in", ["outgoing", "internal"]))

        # State Filter
        if self.state_filter and self.state_filter != 'all':
            domain.append(("state", "=", self.state_filter))
        else:
            domain.append(("state", "in", ["done", "assigned"]))

        if self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))

        return domain

    # ====== STOCK EXPORT TEMPLATE ======
    
    def _get_stock_export_columns(self):
        """Định nghĩa cột cho mẫu Xuất Kho (22 columns)"""
        return [
            {'key': 'loai_xuat_kho', 'name': 'Loại xuất kho', 'width': 20},
            {'key': 'ngay_hach_toan', 'name': 'Ngày hạch toán (*)', 'width': 18},
            {'key': 'ngay_chung_tu', 'name': 'Ngày chứng từ (*)', 'width': 18},
            {'key': 'so_chung_tu', 'name': 'Số chứng từ (*)', 'width': 20},
            {'key': 'ma_doi_tuong', 'name': 'Mã đối tượng', 'width': 15},
            {'key': 'ten_doi_tuong', 'name': 'Tên đối tượng', 'width': 30},
            {'key': 'dia_chi', 'name': 'Địa chỉ/Bộ phận', 'width': 40},
            {'key': 'ly_do_xuat', 'name': 'Lý do xuất', 'width': 30},
            {'key': 'ma_hang', 'name': 'Mã hàng (*)', 'width': 18},
            {'key': 'ten_hang', 'name': 'Tên hàng', 'width': 35},
            {'key': 'la_dong_ghi_chu', 'name': 'Là dòng ghi chú', 'width': 15},
            {'key': 'hang_khuyen_mai', 'name': 'Hàng khuyến mại', 'width': 15},
            {'key': 'ma_kho', 'name': 'Mã kho', 'width': 15},
            {'key': 'tk_no', 'name': 'TK Nợ (*)', 'width': 12},
            {'key': 'tk_co', 'name': 'TK Có (*)', 'width': 12},
            {'key': 'dvt', 'name': 'ĐVT', 'width': 10},
            {'key': 'so_luong', 'name': 'Số lượng', 'width': 12},
            {'key': 'don_gia', 'name': 'Đơn giá', 'width': 15},
            {'key': 'thanh_tien', 'name': 'Thành tiền', 'width': 15},
            {'key': 'so_lenh_sx', 'name': 'Số lệnh sản xuất', 'width': 15},
            {'key': 'ma_khoan_muc_cp', 'name': 'Mã khoản mục chi phí', 'width': 18},
            {'key': 'ma_doi_tuong_thcp', 'name': 'Mã đối tượng THCP', 'width': 18},
        ]

    def _get_stock_export_row_data(self, picking):
        """Xây dựng rows cho mẫu Xuất Kho"""
        rows = []
        
        # --- Common Info ---
        date_done = picking.date_done or picking.scheduled_date or fields.Datetime.now()
        date_str = _to_date_str(date_done)
        
        partner = picking.partner_id
        partner_code = self._partner_code(partner)
        partner_name = (partner and partner.name) or ""
        
        # Address
        partner_address = ""
        if partner:
            parts = []
            for p in [partner.street, partner.city, partner.state_id.name if partner.state_id else '']:
                if p: parts.append(p)
            partner_address = ", ".join(parts)
            
        warehouse_code = self._get_warehouse_code(picking)
        ly_do_xuat = picking.note or picking.name
        if picking.picking_type_code == 'outgoing':
             loai_xuat = '2. Xuất bán hàng'
        elif picking.picking_type_code == 'internal':
             loai_xuat = '4. Xuất khác'
        else:
             loai_xuat = '2. Xuất bán hàng'
        
        # Determine moves
        moves = picking.move_line_ids if picking.move_line_ids else picking.move_ids_without_package
        
        for line in moves:
            # Determine move & product
            if line._name == 'stock.move.line':
                prod = line.product_id
                move = line.move_id
                qty = line.qty_done
                uom = line.product_uom_id
            else:
                prod = line.product_id
                move = line
                qty = line.quantity_done if hasattr(line, 'quantity_done') else line.product_uom_qty
                uom = line.product_uom
            
            if not prod: continue

            # Values
            standard_price = prod.standard_price or 0.0
            cost_value = standard_price * qty
            
            row = {
                'loai_xuat_kho': loai_xuat,
                'ngay_hach_toan': date_str,
                'ngay_chung_tu': date_str,
                'so_chung_tu': picking.name,
                'ma_doi_tuong': partner_code,
                'ten_doi_tuong': partner_name,
                'dia_chi': partner_address,
                'ly_do_xuat': ly_do_xuat,
                'ma_hang': prod.default_code or '',
                'ten_hang': prod.name,
                'la_dong_ghi_chu': 'Không',
                'hang_khuyen_mai': 'Không',
                'ma_kho': warehouse_code,
                'tk_no': '632',
                'tk_co': '1561',
                'dvt': uom.name if uom else '',
                'so_luong': qty,
                'don_gia': standard_price,
                'thanh_tien': cost_value,
                'so_lenh_sx': '',
                'ma_khoan_muc_cp': '',
                'ma_doi_tuong_thcp': '',
            }
            rows.append(row)
            
        return rows

    def _create_stock_export_workbook(self, pickings):
        """Tạo workbook Excel mẫu Xuất Kho"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Phiếu Xuất Kho"

        columns = self._get_stock_export_columns()

        # Styles
        header_font = Font(name='Arial', size=10, bold=True)
        header_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        border_side = Side(style='thin', color='000000')
        border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)
        cell_alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
        number_alignment = Alignment(horizontal='right', vertical='center')

        # Header
        for col_idx, col_def in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = col_def['name']
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border
            ws.column_dimensions[get_column_letter(col_idx)].width = col_def.get('width', 15)

        # Data
        current_row = 2
        for picking in pickings:
             rows_data = self._get_stock_export_row_data(picking)
             for row_data in rows_data:
                 for col_idx, col_def in enumerate(columns, start=1):
                     cell = ws.cell(row=current_row, column=col_idx)
                     value = row_data.get(col_def['key'], '')
                     if value is None: value = ''
                     
                     cell.value = value
                     cell.border = border
                     
                     if isinstance(value, (int, float)) and value != '':
                         cell.alignment = number_alignment
                         if 'so_luong' in col_def['key']:
                             cell.number_format = '#,##0.00'
                         elif 'tien' in col_def['key'] or 'gia' in col_def['key']:
                             cell.number_format = '#,##0'
                     else:
                         cell.alignment = cell_alignment
                 current_row += 1
        
        ws.row_dimensions[1].height = 30
        return wb

    def action_export_stock_template(self):
        """Action xuất Excel mẫu Xuất Kho"""
        self.ensure_one()
        if Workbook is None:
             raise UserError(_("Thiếu thư viện openpyxl."))

        domain = self._domain()
        
        pickings = self.env["stock.picking"].sudo().search(domain, order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho trong khoảng thời gian này."))

        wb = self._create_stock_export_workbook(pickings)
        
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        
        filename = f"Xuat_Kho_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "stock.export.wizard",
            "res_id": self.id,
        })
        
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
