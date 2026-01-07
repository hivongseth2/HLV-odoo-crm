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


class PickingExportWizard(models.TransientModel):
    def _harsh_warehouse_code(self, code):
        if code == "KBC":
            return "BENCAM"
        if code == "TSN":
            return "HCM"
        if code == "KHD":
            return "HIENDUC"
        if code == "TSNSR":
            return "HCM_SHOWROOM"
        return code
    _name = "picking.export.wizard"
    _description = "Xuất Excel lệnh xuất kho theo template kế toán"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    warehouse_ids = fields.Many2many(
        "stock.warehouse",
        string="Kho xuất",
        help="Để trống = Tất cả kho. Chọn 1 hoặc nhiều kho để lọc cụ thể.",
    )

    state_filter = fields.Selection(
        [
            ("all", "Tất cả"),
            ("assigned", "Đã kiểm tra tồn (assigned)"),
            ("done", "Đã hoàn thành (done)"),
            ("confirmed", "Đã xác nhận (confirmed)"),
            ("waiting", "Chờ khác (waiting)"),
        ],
        string="Trạng thái",
        default="all",
    )

    def _find_sale_order(self, move, picking):
        # 1) Từ sale_line_id trực tiếp
        if getattr(move, 'sale_line_id', False) and move.sale_line_id.order_id:
            return move.sale_line_id.order_id
        # 2) Từ procurement group
        grp = getattr(move, 'group_id', False)
        if grp and getattr(grp, 'sale_id', False):
            return grp.sale_id
        # 3) Từ picking
        if getattr(picking, 'sale_id', False):
            return picking.sale_id
        return False

    def _get_columns_definition(self):
        """Định nghĩa các cột theo template kế toán"""
        return [
            {'key': 'hinh_thuc_ban_hang', 'name': 'Hình thức bán hàng', 'width': 25},
            {'key': 'phuong_thuc_thanh_toan', 'name': 'Phương thức thanh toán', 'width': 25},
            {'key': 'hinh_thuc_giao_hang', 'name': 'Hình thức giao hàng', 'width': 25},
            {'key': 'hinh_thuc_thanh_toan_so', 'name': 'Hình thức thanh toán (SO)', 'width': 25},
            {'key': 'ben_tra_phi_van_chuyen', 'name': 'Bên trả phí vận chuyển', 'width': 25},
            {'key': 'kiem_phieu_xuat_kho', 'name': 'Kiêm phiếu xuất kho', 'width': 20},
            {'key': 'lap_kem_hoa_don', 'name': 'Lập kèm hóa đơn', 'width': 18},
            {'key': 'da_lap_hoa_don', 'name': 'Đã lập hóa đơn', 'width': 18},
            {'key': 'ngay_hach_toan', 'name': 'Ngày hạch toán (*)', 'width': 25},
            {'key': 'ngay_chung_tu', 'name': 'Ngày chứng từ (*)', 'width': 25},
            {'key': 'so_chung_tu', 'name': 'Số chứng từ (*)', 'width': 20},
            {'key': 'so_phieu_xuat', 'name': 'Số phiếu xuất', 'width': 20},
            {'key': 'mau_so_hd', 'name': 'Mẫu số HĐ', 'width': 15},
            {'key': 'ky_hieu_hd', 'name': 'Ký hiệu HĐ', 'width': 15},
            {'key': 'so_hoa_don', 'name': 'Số hóa đơn', 'width': 15},
            {'key': 'ngay_hoa_don', 'name': 'Ngày hóa đơn', 'width': 25},
            {'key': 'ma_khach_hang', 'name': 'Mã khách hàng', 'width': 15},
            {'key': 'ten_khach_hang', 'name': 'Tên khách hàng', 'width': 40},
            {'key': 'dia_chi', 'name': 'Địa chỉ', 'width': 50},
            {'key': 'ma_so_thue', 'name': 'Mã số thuế', 'width': 15},
            {'key': 'don_vi_giao_dai_ly', 'name': 'Đơn vị giao đại lý', 'width': 30},
            {'key': 'nguoi_nop', 'name': 'Người nộp', 'width': 25},
            {'key': 'nop_vao_tk', 'name': 'Nộp vào TK', 'width': 15},
            {'key': 'ten_ngan_hang', 'name': 'Tên ngân hàng', 'width': 30},
            {'key': 'dien_giai', 'name': 'Diễn giải/Lý do nộp', 'width': 40},
            {'key': 'ly_do_xuat', 'name': 'Lý do xuất', 'width': 40},
            {'key': 'ma_nhan_vien', 'name': 'Mã nhân viên bán hàng', 'width': 20},
            {'key': 'so_ct_phieu_thu', 'name': 'Số chứng từ kèm theo (Phiếu thu)', 'width': 25},
            {'key': 'so_ct_phieu_xuat', 'name': 'Số chứng từ kèm theo (Phiếu xuất)', 'width': 25},
            {'key': 'han_thanh_toan', 'name': 'Hạn thanh toán', 'width': 20},
            {'key': 'ma_hang', 'name': 'Mã hàng (*)', 'width': 18},
            {'key': 'thuoc_combo', 'name': 'Thuộc combo', 'width': 15},
            {'key': 'ten_hang', 'name': 'Tên hàng', 'width': 40},
            {'key': 'la_dong_ghi_chu', 'name': 'Là dòng ghi chú', 'width': 18},
            {'key': 'hang_khuyen_mai', 'name': 'Hàng khuyến mại', 'width': 18},
            {'key': 'chiet_khau_thuong_mai', 'name': 'Chiết khấu thương mại', 'width': 25},
            {'key': 'tk_tien_no', 'name': 'TK Tiền/Chi phí/Nợ (*)', 'width': 22},
            {'key': 'tk_doanh_thu_co', 'name': 'TK Doanh thu/Có (*)', 'width': 20},
            {'key': 'dvt', 'name': 'ĐVT', 'width': 12},
            {'key': 'so_luong', 'name': 'Số lượng', 'width': 12},
            {'key': 'don_gia', 'name': 'Đơn giá', 'width': 15},
            {'key': 'thanh_tien', 'name': 'Thành tiền', 'width': 15},
            {'key': 'ty_le_ck', 'name': 'Tỷ lệ CK (%)', 'width': 12},
            {'key': 'tien_chiet_khau', 'name': 'Tiền chiết khấu', 'width': 15},
            {'key': 'tk_chiet_khau', 'name': 'TK chiết khấu', 'width': 15},
            {'key': 'gia_tinh_thue_xk', 'name': 'Giá tính thuế XK', 'width': 15},
            {'key': 'ty_le_thue_xk', 'name': '% thuế xuất khẩu', 'width': 15},
            {'key': 'tien_thue_xk', 'name': 'Tiền thuế xuất khẩu', 'width': 18},
            {'key': 'tk_thue_xk', 'name': 'TK thuế xuất khẩu', 'width': 18},
            {'key': 'ty_le_thue_gtgt', 'name': '% thuế GTGT', 'width': 12},
            {'key': 'ty_le_thue_khac', 'name': '% thuế suất KHAC', 'width': 18},
            {'key': 'tien_thue_gtgt', 'name': 'Tiền thuế GTGT', 'width': 15},
            {'key': 'tk_thue_gtgt', 'name': 'TK thuế GTGT', 'width': 15},
            {'key': 'bien_kiem_soat', 'name': 'Biển kiểm soát ', 'width': 18},
            {'key': 'hh_khong_th_tren_to_khai', 'name': 'HH không TH trên tờ khai thuế GTGT', 'width': 35},
            {'key': 'ma_khoan_muc_cp', 'name': 'Mã khoản mục chi phí', 'width': 22},
            {'key': 'ma_don_vi', 'name': 'Mã đơn vị', 'width': 15},
            {'key': 'ma_doi_tuong_thcp', 'name': 'Mã đối tượng THCP', 'width': 20},
            {'key': 'ma_cong_trinh', 'name': 'Mã công trình', 'width': 18},
            {'key': 'so_don_dat_hang', 'name': 'Số đơn đặt hàng', 'width': 20},
            {'key': 'so_hop_dong_ban', 'name': 'Số hợp đồng bán', 'width': 20},
            {'key': 'ma_thong_ke', 'name': 'Mã thống kê', 'width': 15},
            {'key': 'so_khe_uoc_cho_vay', 'name': 'Số khế ước cho vay', 'width': 20},
            {'key': 'cp_khong_hop_ly', 'name': 'CP không hợp lý', 'width': 18},
            {'key': 'ma_kho', 'name': 'Mã kho', 'width': 15},
            {'key': 'tk_gia_von', 'name': 'TK giá vốn', 'width': 15},
            {'key': 'tk_kho', 'name': 'TK Kho', 'width': 12},
            {'key': 'don_gia_von', 'name': 'Đơn giá vốn', 'width': 15},
            {'key': 'tien_von', 'name': 'Tiền vốn', 'width': 15},
            {'key': 'hang_hoa_giu_ho', 'name': 'Hàng hóa giữ hộ/bán hộ', 'width': 25},
            {'key': 'vi_tri', 'name': 'vị trí', 'width': 25},
            {'key': 'misa_sync', 'name': 'Misa Sync', 'width': 15},
        ]

    def _domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("picking_type_code", "=", "outgoing"),
            ("date_done", ">=", fields.Date.to_date(self.date_from)),
            ("date_done", "<=", fields.Date.to_date(self.date_to)),
            ("state", "=", "done"),
        ]

        if self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))

        # Không cần lọc state_filter nữa vì đã cố định là 'done'

        return domain

    def _partner_code(self, partner):
        if not partner:
            return ""
        return partner.ref or (partner.barcode if hasattr(partner, "barcode") else None) or partner.vat or str(partner.id) or ""

    def _get_warehouse_code(self, picking):
        """Lấy mã kho"""
        pt = picking.picking_type_id
        if pt and pt.warehouse_id:
            code = pt.warehouse_id.code or pt.warehouse_id.name or ""
            return self._harsh_warehouse_code(code)
        return ""

    # ====== HELPERS: xác định parent combo cho 1 sale.order.line ======
    def _thuoc_combo_code_for_move(self, move):
        """
        Trả về mã combo cha (default_code) cho move nếu là dòng con của combo.
        Sử dụng Studio fields x_studio_is_combo_child và x_studio_combo_parent_code
        để xác định chính xác thay vì dựa vào giá = 0.
        """
        sol = getattr(move, 'sale_line_id', False)
        if not sol:
            return ''
        
        # 🆕 Đọc từ Studio fields
        try:
            is_combo_child = getattr(sol, 'x_studio_is_combo_child', False)
            combo_parent_code = getattr(sol, 'x_studio_combo_parent_code', False)
            
            if is_combo_child and combo_parent_code:
                return combo_parent_code
        except Exception as e:
            # Fallback nếu Studio fields không tồn tại
            pass
        
        return ''

    def _get_move_line_rows(self, picking):
        rows = []
        so = self._find_sale_order(picking.move_ids_without_package[0] if picking.move_ids_without_package else None, picking)
        
        # Thông tin chung từ Sale Order hoặc Picking
        scheduled_date_str = _to_date_str(picking.scheduled_date)
        picking_name = picking.name or ""
        partner = picking.partner_id
        partner_code = self._partner_code(partner)
        partner_name = (partner and partner.name) or ""
        partner_address = ""
        import unicodedata
        def normalize_addr(s):
            # Chuẩn hóa: về chữ thường, loại bỏ dấu, loại bỏ khoảng trắng thừa
            s = s.strip().lower()
            s = unicodedata.normalize('NFD', s)
            s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
            return s
        if partner:
            street = partner.street or ""
            city = partner.city or ""
            state = partner.state_id.name if partner.state_id else ""
            address_parts = []
            normalized = set()
            for part in [street, city, state]:
                norm = normalize_addr(part) if part else ""
                if part and norm not in normalized:
                    address_parts.append(part)
                    normalized.add(norm)
            partner_address = ", ".join(address_parts)
        partner_vat = (partner and partner.vat) or ""
        
        # Lấy thông tin từ Sale Order
        sale_name = so.name if so else (picking.origin or "")
        # Lấy mã nhân viên sale từ trường x_studio_misa_saler_code của sale.order, nếu không có thì lấy từ user Odoo
        sale_user_code = ''
        if so:
            misa_code = getattr(so, 'x_studio_misa_saler_code', None)
            if misa_code:
                sale_user_code = misa_code
            elif so.user_id:
                sale_user_code = so.user_id.login or so.user_id.name or ''
        
        # Diễn giải
        dien_giai = ""
        if so and so.origin:
            dien_giai = f"Xuất kho bán hàng cho {partner_name}"
        elif picking.note:
            dien_giai = picking.note
        else:
            dien_giai = f"Bán hàng {partner_name}"
        
        ly_do_xuat = dien_giai
        
        warehouse_code = self._get_warehouse_code(picking)

        # Xử lý từng move line hoặc move
        if picking.move_line_ids:
            for ml in picking.move_line_ids:
                move = ml.move_id
                prod = ml.product_id
                if not prod:
                    continue

                row = self._build_row_data(
                    picking, so, prod, ml, move,
                    scheduled_date_str, picking_name, partner_code, partner_name,
                    partner_address, partner_vat, sale_name, sale_user_code,
                    dien_giai, ly_do_xuat, warehouse_code
                )
                rows.append(row)
        else:
            for mv in picking.move_ids_without_package:
                prod = mv.product_id
                if not prod:
                    continue

                row = self._build_row_data(
                    picking, so, prod, None, mv,
                    scheduled_date_str, picking_name, partner_code, partner_name,
                    partner_address, partner_vat, sale_name, sale_user_code,
                    dien_giai, ly_do_xuat, warehouse_code
                )
                rows.append(row)

        return rows

    def _build_row_data(self, picking, so, prod, ml, move,
                        scheduled_date_str, picking_name, partner_code, partner_name,
                        partner_address, partner_vat, sale_name, sale_user_code,
                        dien_giai, ly_do_xuat, warehouse_code):
        """Xây dựng dữ liệu cho 1 dòng"""
        
        product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""
        product_name = prod.display_name or prod.name or ""
        
        # UoM
        if ml:
            uom = ml.product_uom_id or prod.uom_id
            qty = ml.qty_done or 0.0
            location_name = (ml.location_id and ml.location_id.complete_name) or ""
        else:
            uom = move.product_uom or prod.uom_id
            qty = move.qty_done if hasattr(move, 'qty_done') else (move.product_uom_qty or 0.0)
            location_name = (move.location_id and move.location_id.complete_name) or ""
        
        uom_name = (uom and uom.name) or ""
        
        # Lấy thông tin từ Sale Order Line
        sol = getattr(move, 'sale_line_id', False) if move else False
        don_gia = 0.0
        thanh_tien = 0.0
        ty_le_ck = 0.0
        tien_chiet_khau = 0.0
        ty_le_thue_gtgt = 0.0
        tien_thue_gtgt = 0.0
        
        if sol:
            don_gia = sol.price_unit or 0.0
            thanh_tien = sol.price_subtotal or 0.0
            ty_le_ck = sol.discount or 0.0
            
            # Tính tiền chiết khấu
            if ty_le_ck > 0:
                tien_chiet_khau = (don_gia * qty * ty_le_ck) / 100
            
            # Thuế GTGT
            if sol.tax_id:
                for tax in sol.tax_id:
                    ty_le_thue_gtgt = tax.amount or 0.0
                    break
            
            tien_thue_gtgt = (thanh_tien * ty_le_thue_gtgt) / 100
        else:
            # Fallback: lấy từ product
            don_gia = prod.list_price or 0.0
            thanh_tien = don_gia * qty
        
        # Đơn giá vốn và tiền vốn
        don_gia_von = prod.standard_price or 0.0
        tien_von = don_gia_von * qty

        return {
            # Hardcoded fields
            'hinh_thuc_ban_hang': 'Bán hàng hóa trong nước',
            'phuong_thuc_thanh_toan': picking.x_studio_pos_payment_method or 'Chưa thu tiền',
            # 3 cột mới từ sale.order (đặt ngay sau phương thức thanh toán)
            'hinh_thuc_giao_hang': getattr(so, 'x_studio_htgh', '') if so else '',
            'hinh_thuc_thanh_toan_so': getattr(so, 'x_studio_httt', '') if so else '',
            'ben_tra_phi_van_chuyen': getattr(so, 'x_studio_misa_delivery', '') if so else '',
            'kiem_phieu_xuat_kho': 'Có',
            'lap_kem_hoa_don': 'Có',
            'da_lap_hoa_don': 'Đã lập',
            
            # Date fields
            'ngay_hach_toan': _to_date_str(datetime.date.today()),
            'ngay_chung_tu': _to_date_str(datetime.date.today()),
            'so_chung_tu': picking_name,
            'so_phieu_xuat': sale_name,
            
            # Invoice fields - hardcoded examples
            'mau_so_hd': '01GTKT0/001',
            'ky_hieu_hd': '1C25TLV',
            'so_hoa_don': '',  # Để trống hoặc lấy từ invoice nếu có
            'ngay_hoa_don': scheduled_date_str,
            
            # Partner info
            'ma_khach_hang': partner_code,
            'ten_khach_hang': partner_name,
            'dia_chi': partner_address,
            'ma_so_thue': partner_vat,
            
            # Other info
            'don_vi_giao_dai_ly': '',
            'nguoi_nop': partner_name,
            'nop_vao_tk': '',
            'ten_ngan_hang': '',
            'dien_giai': dien_giai,
            'ly_do_xuat': ly_do_xuat,
            'ma_nhan_vien': sale_user_code,
            'so_ct_phieu_thu': '',
            'so_ct_phieu_xuat': sale_name,
            'han_thanh_toan': '',
            
            # Product info
            'ma_hang': product_code,
            'thuoc_combo': self._thuoc_combo_code_for_move(move),
            'ten_hang': product_name,
            'la_dong_ghi_chu': 'không',
            'hang_khuyen_mai': 'Không',
            'chiet_khau_thuong_mai': '',
            
            # Account codes - hardcoded examples
            'tk_tien_no': '131',
            'tk_doanh_thu_co': '5111',
            
            # Quantity and price
            'dvt': uom_name,
            'so_luong': qty,
            'don_gia': don_gia,
            'thanh_tien': thanh_tien,
            'ty_le_ck': ty_le_ck,
            'tien_chiet_khau': tien_chiet_khau,
            'tk_chiet_khau': '',
            
            # Tax info
            'gia_tinh_thue_xk': '',
            'ty_le_thue_xk': '',
            'tien_thue_xk': '',
            'tk_thue_xk': '',
            'ty_le_thue_gtgt': ty_le_thue_gtgt,
            'ty_le_thue_khac': '',
            'tien_thue_gtgt': tien_thue_gtgt,
            'tk_thue_gtgt': '33311',
            
            # Other fields
            'bien_kiem_soat': '',
            'hh_khong_th_tren_to_khai': 'Không',
            'ma_khoan_muc_cp': '',
            'ma_don_vi': 'PKD',
            'ma_doi_tuong_thcp': '',
            'ma_cong_trinh': '',
            'so_don_dat_hang': sale_name,
            'so_hop_dong_ban': sale_name,
            'ma_thong_ke': '',
            'so_khe_uoc_cho_vay': '',
            'cp_khong_hop_ly': 'Không',
            
            # Warehouse and cost
            'ma_kho': warehouse_code,
            'tk_gia_von': '632',
            'tk_kho': '156',
            'don_gia_von': don_gia_von,
            'tien_von': tien_von,
            'hang_hoa_giu_ho': '',
            'vi_tri': '',
            'misa_sync': getattr(picking, 'x_studio_misa_sav', False),
        }

    def _create_excel_workbook(self, data_rows):
        """Tạo workbook Excel với header"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Xuất bán hàng hóa"

        columns = self._get_columns_definition()

        # Styles
        header_font = Font(name='Arial', size=10, bold=True)
        header_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
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
                value = row_data.get(col_def['key'], "")

                if value is None:
                    value = ""

                cell.value = value
                cell.border = border

                # Number formatting
                if isinstance(value, (int, float)) and value != "":
                    cell.alignment = number_alignment
                    if col_def['key'] in ['don_gia', 'thanh_tien', 'tien_chiet_khau', 
                                         'tien_thue_gtgt', 'don_gia_von', 'tien_von']:
                        cell.number_format = '#,##0'
                    elif col_def['key'] in ['ty_le_ck', 'ty_le_thue_gtgt', 'ty_le_thue_xk']:
                        cell.number_format = '0.00'
                    elif col_def['key'] == 'so_luong':
                        cell.number_format = '#,##0.00'
                else:
                    cell.alignment = cell_alignment

        ws.row_dimensions[HEADER_ROW].height = 30

        return wb

    def action_export(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho nào trong khoảng ngày đã chọn."))

        # Tạo dữ liệu
        all_rows = []
        for picking in pickings:
            rows = self._get_move_line_rows(picking)
            all_rows.extend(rows)

        if not all_rows:
            raise UserError(_("Không có dữ liệu chi tiết để xuất."))

        # Tạo Excel workbook
        wb = self._create_excel_workbook(all_rows)

        # Xuất file
        out = BytesIO()
        wb.save(out)
        out.seek(0)

        filename = f"Xuat_ban_hang_hoa_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "picking.export.wizard",
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _get_json_data(self, picking):
        """
        Lấy dữ liệu JSON: mã đơn hàng và dict sản phẩm với số lượng
        Trả về dict: {'ma_don_hang': 'SO001', 'san_pham': {'PROD001': 10.0, 'PROD002': 5.0}}
        """
        so = self._find_sale_order(picking.move_ids_without_package[0] if picking.move_ids_without_package else None, picking)
        
        # Mã đơn hàng: ưu tiên sale order name, sau đó là picking origin
        sale_name = so.name if so else (picking.origin or picking.name or "")
        
        # Dict để lưu sản phẩm và số lượng
        san_pham_dict = {}
        
        # Xử lý từng move line hoặc move
        if picking.move_line_ids:
            for ml in picking.move_line_ids:
                prod = ml.product_id
                if not prod:
                    continue
                
                product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""
                qty = ml.qty_done or 0.0
                
                if product_code and qty > 0:
                    # Cộng dồn số lượng nếu sản phẩm đã có
                    if product_code in san_pham_dict:
                        san_pham_dict[product_code] += qty
                    else:
                        san_pham_dict[product_code] = qty
        else:
            for mv in picking.move_ids_without_package:
                prod = mv.product_id
                if not prod:
                    continue
                
                product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""
                qty = mv.qty_done if hasattr(mv, 'qty_done') else (mv.product_uom_qty or 0.0)
                
                if product_code and qty > 0:
                    # Cộng dồn số lượng nếu sản phẩm đã có
                    if product_code in san_pham_dict:
                        san_pham_dict[product_code] += qty
                    else:
                        san_pham_dict[product_code] = qty
        
        # Chỉ trả về nếu có sản phẩm
        if san_pham_dict:
            return {
                'ma_don_hang': sale_name,
                'san_pham': san_pham_dict
            }
        return None

    def action_export_json(self):
        """
        Xuất dữ liệu ra file JSON với format nhóm theo mã đơn hàng:
        - mã đơn hàng
        - san_pham: dict chứa tất cả sản phẩm và số lượng trong đơn hàng đó
        """
        self.ensure_one()
        
        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho nào trong khoảng ngày đã chọn."))
        
        # Dict để nhóm theo mã đơn hàng
        orders_dict = {}
        
        # Thu thập dữ liệu từ tất cả pickings
        for picking in pickings:
            order_data = self._get_json_data(picking)
            if not order_data:
                continue
            
            ma_don_hang = order_data['ma_don_hang']
            san_pham = order_data['san_pham']
            
            # Nếu đơn hàng đã tồn tại, cộng dồn sản phẩm
            if ma_don_hang in orders_dict:
                for product_code, qty in san_pham.items():
                    if product_code in orders_dict[ma_don_hang]['san_pham']:
                        orders_dict[ma_don_hang]['san_pham'][product_code] += qty
                    else:
                        orders_dict[ma_don_hang]['san_pham'][product_code] = qty
            else:
                orders_dict[ma_don_hang] = {
                    'ma_don_hang': ma_don_hang,
                    'san_pham': san_pham.copy()
                }
        
        # Chuyển thành list
        all_rows = list(orders_dict.values())
        
        if not all_rows:
            raise UserError(_("Không có dữ liệu chi tiết để xuất."))
        
        # Chuyển đổi sang JSON
        json_data = json.dumps(all_rows, ensure_ascii=False, indent=2)
        json_bytes = json_data.encode('utf-8')
        
        # Tạo attachment
        filename = f"Xuat_ban_hang_hoa_{self.date_from}_{self.date_to}.json"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/json",
            "datas": base64.b64encode(json_bytes),
            "res_model": "picking.export.wizard",
            "res_id": self.id,
        })
        
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _get_pos_columns_definition(self):
        """Định nghĩa cột cho mẫu POS (52 columns match template)"""
        return [
            {'key': 'hinh_thuc_ban_hang', 'name': 'Hình thức bán hàng', 'width': 25},
            {'key': 'phuong_thuc_thanh_toan', 'name': 'Phương thức thanh toán', 'width': 25},
            {'key': 'kiem_phieu_xuat_kho', 'name': 'Kiêm phiếu xuất kho', 'width': 20},
            {'key': 'lap_kem_hoa_don', 'name': 'Lập kèm hóa đơn', 'width': 18},
            {'key': 'da_lap_hoa_don', 'name': 'Đã lập hóa đơn', 'width': 18},
            {'key': 'ngay_hach_toan', 'name': 'Ngày hạch toán (*)', 'width': 25},
            {'key': 'ngay_chung_tu', 'name': 'Ngày chứng từ (*)', 'width': 25},
            {'key': 'so_chung_tu', 'name': 'Số chứng từ (*)', 'width': 20},
            {'key': 'so_phieu_xuat', 'name': 'Số phiếu xuất', 'width': 20},
            {'key': 'mau_so_hd', 'name': 'Mẫu số HĐ', 'width': 15},
            {'key': 'ky_hieu_hd', 'name': 'Ký hiệu HĐ', 'width': 15},
            {'key': 'so_hoa_don', 'name': 'Số hóa đơn', 'width': 15},
            {'key': 'ngay_hoa_don', 'name': 'Ngày hóa đơn', 'width': 20},
            {'key': 'ma_khach_hang', 'name': 'Mã khách hàng', 'width': 15},
            {'key': 'ten_khach_hang', 'name': 'Tên khách hàng', 'width': 40},
            {'key': 'dia_chi', 'name': 'Địa chỉ', 'width': 50},
            {'key': 'ma_so_thue', 'name': 'Mã số thuế', 'width': 15},
            {'key': 'don_vi_giao_dai_ly', 'name': 'Đơn vị giao đại lý', 'width': 30},
            {'key': 'nguoi_nop', 'name': 'Người nộp', 'width': 25},
            {'key': 'nop_vao_tk', 'name': 'Nộp vào TK', 'width': 15},
            {'key': 'ten_ngan_hang', 'name': 'Tên ngân hàng', 'width': 30},
            {'key': 'dien_giai', 'name': 'Diễn giải/Lý do nộp', 'width': 40},
            {'key': 'ly_do_xuat', 'name': 'Lý do xuất', 'width': 40},
            {'key': 'nhan_vien_ban_hang', 'name': 'Mã nhân viên bán hàng', 'width': 20},
            {'key': 'kem_theo', 'name': 'Kèm theo', 'width': 20},
            {'key': 'han_thanh_toan', 'name': 'Hạn thanh toán', 'width': 20},
            {'key': 'ma_hang', 'name': 'Mã hàng (*)', 'width': 18},
            {'key': 'thuoc_combo', 'name': 'Thuộc combo', 'width': 15},
            {'key': 'ten_hang', 'name': 'Tên hàng', 'width': 40},
            {'key': 'la_dong_ghi_chu', 'name': 'Là dòng ghi chú', 'width': 18},
            {'key': 'hang_khuyen_mai', 'name': 'Hàng khuyến mại', 'width': 18},
            {'key': 'chiet_khau_thuong_mai', 'name': 'Chiết khấu thương mại', 'width': 25},
            {'key': 'tk_tien_no', 'name': 'TK Tiền/Chi phí/Nợ (*)', 'width': 20},
            {'key': 'tk_doanh_thu_co', 'name': 'TK Doanh thu/Có (*)', 'width': 20},
            {'key': 'dvt', 'name': 'ĐVT', 'width': 12},
            {'key': 'so_luong', 'name': 'Số lượng', 'width': 12},
            {'key': 'don_gia', 'name': 'Đơn giá', 'width': 15},
            {'key': 'thanh_tien', 'name': 'Thành tiền', 'width': 15},
            {'key': 'ty_le_ck', 'name': 'Tỷ lệ CK (%)', 'width': 12},
            {'key': 'tien_chiet_khau', 'name': 'Tiền chiết khấu', 'width': 15},
            {'key': 'tk_chiet_khau', 'name': 'TK chiết khấu', 'width': 15},
            {'key': 'gia_tinh_thue_xk', 'name': 'Giá tính thuế XK', 'width': 15},
            {'key': 'ty_le_thue_xk', 'name': '% thuế xuất khẩu', 'width': 15},
            {'key': 'tien_thue_xk', 'name': 'Tiền thuế xuất khẩu', 'width': 15},
            {'key': 'tk_thue_xk', 'name': 'TK thuế xuất khẩu', 'width': 15},
            {'key': 'ty_le_thue_gtgt', 'name': '% thuế GTGT', 'width': 12},
            {'key': 'ty_le_thue_khac', 'name': '% thuế suất KHAC', 'width': 15},
            {'key': 'tien_thue_gtgt', 'name': 'Tiền thuế GTGT', 'width': 15},
            {'key': 'tk_thue_gtgt', 'name': 'TK thuế GTGT', 'width': 15},
            {'key': 'hh_khong_th_tren_to_khai', 'name': 'HH không TH trên tờ khai thuế GTGT', 'width': 25},
            {'key': 'ma_kho', 'name': 'Mã kho', 'width': 15},
            {'key': 'tk_gia_von', 'name': 'TK giá vốn', 'width': 15},
            {'key': 'tk_kho', 'name': 'TK Kho', 'width': 15},
            {'key': 'don_gia_von', 'name': 'Đơn giá vốn', 'width': 15},
            {'key': 'tien_von', 'name': 'Tiền vốn', 'width': 15},
            {'key': 'hang_hoa_giu_ho', 'name': 'Hàng hóa giữ hộ/bán hộ', 'width': 20},
        ]

    def _get_pos_row_data(self, picking):
        """Xây dựng rows cho mẫu POS"""
        rows = []
        so = self._find_sale_order(picking.move_ids_without_package[0] if picking.move_ids_without_package else None, picking)
        
        # --- Common Info ---
        date_done = picking.date_done or picking.scheduled_date or fields.Datetime.now()
        date_str = _to_date_str(date_done)
        
        # Số chứng từ: x_studio_pos_group (VD: POS/050126)
        # Nếu chưa có thì fallback về picking name
        so_chung_tu = picking.x_studio_pos_group or picking.name
        
        # Số phiếu xuất: thêm 'PXK' trước số chứng từ
        # VD: PXKPOS/050126
        # Lưu ý: user nói "có thêm PXK phía trước"
        so_phieu_xuat = ""
        if picking.x_studio_pos_group:
            # Xử lý format nếu cần, ở đây ghép chuỗi đơn giản
            # Giả sử group là POS/050126 -> PXKPOS/050126
            # Hoặc PXK + POS/050126 -> PXKPOS/050126
            so_phieu_xuat = "PXK" + picking.x_studio_pos_group.replace("POS/", "POS") 
            # Hay là "PXK" + full string? User: "số phiếu xuất là số chứng từ có thêm PXK phía trước"
            # Nếu group = POS/010126 -> PXKPOS/010126 ?
            # Hay PXK POS/010126 ?
            # Thường là liền: PXKPOS/010126
            if "POS/" in picking.x_studio_pos_group:
                 so_phieu_xuat = "PXK" + picking.x_studio_pos_group.replace("/", "")
            else:
                 so_phieu_xuat = "PXK" + picking.x_studio_pos_group
        else:
            so_phieu_xuat = "PXK" + picking.name

        partner = picking.partner_id
        partner_code = self._partner_code(partner)
        partner_name = (partner and partner.name) or ""
        partner_address = ""
        # Get address parts same as before...
        # ... (Simplified for brevity, assuming existing logic from _get_move_line_rows works or copying it)
        # Copy logic for address:
        import unicodedata
        def normalize_addr(s):
            s = s.strip().lower()
            s = unicodedata.normalize('NFD', s)
            s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
            return s
        if partner:
            parts = [partner.street, partner.city, partner.state_id.name]
            valid_parts = [p for p in parts if p]
            partner_address = ", ".join(valid_parts)
            
        partner_vat = (partner and partner.vat) or ""

        # Sale info
        sale_name = so.name if so else (picking.origin or "")
        sale_user_code = ''
        if so and so.user_id:
            sale_user_code = so.user_id.login or so.user_id.name or ''
        
        dien_giai = picking.note or f"Xuất bán hàng {partner_name}"
        warehouse_code = self._get_warehouse_code(picking)

        # Loop moves
        moves = picking.move_line_ids if picking.move_line_ids else picking.move_ids_without_package
        
        for line in moves:
            # Determine product, qty, uom
            if line._name == 'stock.move.line':
                prod = line.product_id
                qty = line.qty_done
                uom = line.product_uom_id
                move = line.move_id
            else:
                prod = line.product_id
                qty = line.quantity_done if hasattr(line, 'quantity_done') else line.product_uom_qty
                uom = line.product_uom
                move = line # Itself
            
            if not prod: continue

            # Pricing from SOL
            sol = move.sale_line_id if move and hasattr(move, 'sale_line_id') else False
            price_unit = 0
            price_subtotal = 0
            discount = 0
            tax_amount = 0
            
            if sol:
                price_unit = sol.price_unit
                discount = sol.discount
                price_subtotal = sol.price_subtotal
                # Tax calculation rudimentary
                if sol.tax_id:
                    tax_amount = sol.tax_id[0].amount
            else:
                 # Fallback to product list price if no SOL
                 price_unit = prod.list_price
                 price_subtotal = price_unit * qty

            # Computed fields
            tien_ck = (price_unit * qty * discount / 100) if discount else 0
            thanh_tien = price_subtotal # Excludes tax usually
            # Or manually: (price_unit * qty) - tien_ck
            
            tien_thue = (thanh_tien * tax_amount / 100) if tax_amount else 0
            
            # Start building dict based on NEW columns
            row = {
                'hinh_thuc_ban_hang': 'Bán hàng hóa trong nước',
                'phuong_thuc_thanh_toan': 'Chưa thu tiền',
                'kiem_phieu_xuat_kho': 'Có',
                'lap_kem_hoa_don': 'Không',
                'da_lap_hoa_don': 'Chưa lập',
                'ngay_hach_toan': date_str,
                'ngay_chung_tu': date_str,
                'so_chung_tu': so_chung_tu,
                'so_phieu_xuat': so_phieu_xuat,
                'mau_so_hd': '',
                'ky_hieu_hd': '',
                'so_hoa_don': '', # Customize if needed
                'ngay_hoa_don': '',
                'ma_khach_hang': partner_code,
                'ten_khach_hang': partner_name,
                'dia_chi': partner_address,
                'ma_so_thue': '',
                'don_vi_giao_dai_ly': '',
                'nguoi_nop': '',
                'nop_vao_tk': '',
                'ten_ngan_hang': '',
                'dien_giai': dien_giai,
                'ly_do_xuat': dien_giai,
                'nhan_vien_ban_hang': sale_user_code,
                'kem_theo': '',
                'han_thanh_toan': '',
                
                'ma_hang': prod.default_code or '',
                'thuoc_combo': self._thuoc_combo_code_for_move(move) if move else '',
                'ten_hang': prod.name,
                'la_dong_ghi_chu': 'không',
                'hang_khuyen_mai': 'Không',
                'chiet_khau_thuong_mai': '',
                
                'tk_tien_no': '131',
                'tk_doanh_thu_co': '5111',
                'dvt': uom.name if uom else '',
                'so_luong': qty,
                'don_gia': price_unit,
                'thanh_tien': thanh_tien,
                'ty_le_ck': '',
                'tien_chiet_khau': tien_ck,
                'tk_chiet_khau': '5211', # Assuming standard
                
                'gia_tinh_thue_xk': '',
                'ty_le_thue_xk': '',
                'tien_thue_xk': '',
                'tk_thue_xk': '',
                
                'ty_le_thue_gtgt': tax_amount,
                'ty_le_thue_khac': '',
                'tien_thue_gtgt': tien_thue,
                'tk_thue_gtgt': '33311',
                'hh_khong_th_tren_to_khai': 'Không',
                
                'ma_kho': 'HLV',
                'tk_gia_von': '632',
                'tk_kho': '1561', # From template sample
                'don_gia_von': prod.standard_price,
                'tien_von': prod.standard_price * qty,
                'hang_hoa_giu_ho': '',
            }
            rows.append(row)
        return rows

    def _create_pos_excel_workbook(self, pickings):
        """Tạo workbook Excel mẫu POS với header và hướng dẫn"""
        wb = Workbook()
        ws = wb.active
        ws.title = "DS Hóa Đơn - POS"

        columns = self._get_pos_columns_definition()

        # Styles
        title_font = Font(name='Arial', size=16, bold=True)
        instruction_font = Font(name='Arial', size=10, italic=True, color='FF0000')
        header_font = Font(name='Arial', size=10, bold=True)
        header_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        border_side = Side(style='thin', color='000000')
        border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

        cell_alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
        number_alignment = Alignment(horizontal='right', vertical='center')

        # --- HEADER ROW (Row 1) ---
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

        # --- DATA ROWS ---
        current_row = DATA_START
        for picking in pickings:
            row_data_list = self._get_pos_row_data(picking)
            for row_data in row_data_list:
                for col_idx, col_def in enumerate(columns, start=1):
                    cell = ws.cell(row=current_row, column=col_idx)
                    value = row_data.get(col_def['key'], "")
                    
                    if value is None: value = ""
                    
                    cell.value = value
                    cell.border = border
                    
                    # Number fmt
                    if isinstance(value, (int, float)) and value != "":
                        cell.alignment = number_alignment
                        if 'ty_le' in col_def['key'] or 'so_luong' in col_def['key']:
                             cell.number_format = '#,##0.00'
                        elif 'tien' in col_def['key'] or 'gia' in col_def['key']:
                             cell.number_format = '#,##0'
                    else:
                        cell.alignment = cell_alignment
                
                current_row += 1

        ws.row_dimensions[HEADER_ROW].height = 30
        return wb

    def action_export_pos_template(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        domain = self._domain()
        # Filter: Either has Group OR has POS Session (ungrouped POS orders)
        domain.append('|')
        domain.append(('x_studio_pos_group', '!=', False))
        domain.append(('pos_session_id', '!=', False))
        pickings = self.env["stock.picking"].sudo().search(domain, order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho nào trong khoảng ngày đã chọn."))

        # Create workbook passing pickings directly to iterate there
        wb = self._create_pos_excel_workbook(pickings)
        
        # Save
        out = BytesIO()
        wb.save(out)
        out.seek(0)

        filename = f"Xuat_POS_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "picking.export.wizard",
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }