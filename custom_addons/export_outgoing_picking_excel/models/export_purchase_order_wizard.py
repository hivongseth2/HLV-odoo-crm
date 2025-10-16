# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import datetime
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


class PurchaseExportWizard(models.TransientModel):
    _name = "purchase.export.wizard"
    _description = "Xuất Excel lệnh mua hàng theo template kế toán"

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

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    def _get_columns_definition(self):
        """Định nghĩa các cột theo template kế toán mua hàng"""
        return [
            {'key': 'hinh_thuc_mua_hang', 'name': 'Hình thức mua hàng', 'width': 25},
            {'key': 'phuong_thuc_thanh_toan', 'name': 'Phương thức thanh toán', 'width': 25},
            {'key': 'nhan_kem_hoa_don', 'name': 'Nhận kèm hóa đơn', 'width': 20},
            {'key': 'ngay_hach_toan', 'name': 'Ngày hạch toán (*)', 'width': 25},
            {'key': 'ngay_chung_tu', 'name': 'Ngày chứng từ (*)', 'width': 25},
            {'key': 'so_phieu_nhap', 'name': 'Số phiếu nhập (*)', 'width': 20},
            {'key': 'so_ct_ghi_no', 'name': 'Số chứng từ ghi nợ/Số chứng từ thanh toán', 'width': 35},
            {'key': 'mau_so_hd', 'name': 'Mẫu số HĐ', 'width': 15},
            {'key': 'ky_hieu_hd', 'name': 'Ký hiệu HĐ', 'width': 15},
            {'key': 'so_hoa_don', 'name': 'Số hóa đơn', 'width': 15},
            {'key': 'ngay_hoa_don', 'name': 'Ngày hóa đơn', 'width': 25},
            {'key': 'so_tk_chi', 'name': 'Số tài khoản chi', 'width': 18},
            {'key': 'ten_ngan_hang_chi', 'name': 'Tên ngân hàng chi', 'width': 30},
            {'key': 'ma_nha_cung_cap', 'name': 'Mã nhà cung cấp', 'width': 18},
            {'key': 'ten_nha_cung_cap', 'name': 'Tên nhà cung cấp', 'width': 40},
            {'key': 'dia_chi', 'name': 'Địa chỉ', 'width': 50},
            {'key': 'ma_so_thue', 'name': 'Mã số thuế', 'width': 15},
            {'key': 'nguoi_giao_hang', 'name': 'Người giao hàng', 'width': 25},
            {'key': 'dien_giai', 'name': 'Diễn giải', 'width': 40},
            {'key': 'so_tk_nhan', 'name': 'Số tài khoản nhận', 'width': 18},
            {'key': 'ten_ngan_hang_nhan', 'name': 'Tên ngân hàng nhận', 'width': 30},
            {'key': 'ly_do_chi', 'name': 'Lý do chi/nội dung thanh toán', 'width': 40},
            {'key': 'ma_nhan_vien', 'name': 'Mã nhân viên mua hàng', 'width': 20},
            {'key': 'so_luong_ct_kem_theo', 'name': 'Số lượng chứng từ kèm theo', 'width': 25},
            {'key': 'han_thanh_toan', 'name': 'Hạn thanh toán', 'width': 20},
            {'key': 'ma_hang', 'name': 'Mã hàng (*)', 'width': 18},
            {'key': 'ten_hang', 'name': 'Tên hàng', 'width': 40},
            {'key': 'la_dong_ghi_chu', 'name': 'Là dòng ghi chú', 'width': 18},
            {'key': 'ma_kho', 'name': 'Mã kho', 'width': 15},
            {'key': 'hang_hoa_giu_ho', 'name': 'Hàng hóa giữ hộ/bán hộ', 'width': 25},
            {'key': 'tk_kho', 'name': 'TK kho/TK chi phí (*)', 'width': 22},
            {'key': 'tk_cong_no', 'name': 'TK công nợ/TK tiền (*)', 'width': 22},
            {'key': 'dvt', 'name': 'ĐVT', 'width': 12},
            {'key': 'so_luong', 'name': 'Số lượng', 'width': 12},
            {'key': 'don_gia', 'name': 'Đơn giá', 'width': 15},
            {'key': 'thanh_tien', 'name': 'Thành tiền', 'width': 15},
            {'key': 'ty_le_ck', 'name': 'Tỷ lệ CK (%)', 'width': 12},
            {'key': 'tien_chiet_khau', 'name': 'Tiền chiết khấu', 'width': 15},
            {'key': 'ty_le_thue_gtgt', 'name': '% thuế GTGT', 'width': 12},
            {'key': 'ty_le_thue_khac', 'name': '% thuế suất KHAC', 'width': 18},
            {'key': 'tien_thue_gtgt', 'name': 'Tiền thuế GTGT', 'width': 15},
            {'key': 'tk_thue_gtgt', 'name': 'TK thuế GTGT', 'width': 15},
            {'key': 'phi_hang_ve_kho', 'name': 'Phí hàng về kho/Chi phí mua hàng', 'width': 30},
            {'key': 'nhom_hhdv_mua_vao', 'name': 'Nhóm HHDV mua vào', 'width': 20},
            {'key': 'so_lenh_san_xuat', 'name': 'Số Lệnh sản xuất', 'width': 20},
            {'key': 'ma_khoan_muc_cp', 'name': 'Mã khoản mục chi phí', 'width': 22},
            {'key': 'ma_don_vi', 'name': 'Mã đơn vị', 'width': 15},
            {'key': 'ma_doi_tuong_thcp', 'name': 'Mã đối tượng THCP', 'width': 20},
            {'key': 'ma_cong_trinh', 'name': 'Mã công trình', 'width': 18},
            {'key': 'so_don_dat_hang', 'name': 'Số đơn đặt hàng', 'width': 20},
            {'key': 'so_don_mua_hang', 'name': 'Số đơn mua hàng', 'width': 20},
            {'key': 'so_hop_dong_mua', 'name': 'Số hợp đồng mua', 'width': 20},
            {'key': 'so_hop_dong_ban', 'name': 'Số hợp đồng bán', 'width': 20},
            {'key': 'ma_thong_ke', 'name': 'Mã thống kê', 'width': 15},
            {'key': 'so_khe_uoc_di_vay', 'name': 'Số khế ước đi vay', 'width': 20},
            {'key': 'so_khe_uoc_cho_vay', 'name': 'Số khế ước cho vay', 'width': 20},
            {'key': 'cp_khong_hop_ly', 'name': 'CP không hợp lý', 'width': 18},
        ]

    def _domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("date_order", ">=", fields.Date.to_date(self.date_from)),
            ("date_order", "<=", fields.Date.to_date(self.date_to)),
            ("receipt_status", "!=", "pending"),
        ]

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
    
    def _get_purchase_line_rows(self, purchase):
        rows = []
        
        # Thông tin chung từ Purchase Order
        order_date_str = _to_date_str(purchase.date_order)
        purchase_name = purchase.name or ""
        partner = purchase.partner_id
        partner_code = self._partner_code(partner)
        partner_name = (partner and partner.name) or ""
        
        # Địa chỉ
        partner_address = ""
        import unicodedata
        def normalize_addr(s):
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
        
        # Diễn giải
        # dien_giai = f"Mua hàng từ {partner_name}"
        # if purchase.notes:
        #     dien_giai = purchase.notes
        
        # Xử lý từng order line
        for pol in purchase.order_line:
            prod = pol.product_id
            if not prod:
                continue

            row = self._build_row_data(
                purchase, pol, prod,
                order_date_str, purchase_name, partner_code, partner_name,
                partner_address, partner_vat
            )
            rows.append(row)

        return rows

    def _build_row_data(self, purchase, pol, prod,
                        order_date_str, purchase_name, partner_code, partner_name,
                        partner_address, partner_vat):
        """Xây dựng dữ liệu cho 1 dòng"""
        
        product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""
        product_name = prod.display_name or prod.name or ""
        
        # UoM
        uom = pol.product_uom or prod.uom_id
        uom_name = (uom and uom.name) or ""
        qty = pol.product_qty or 0.0
        
        # Giá và thuế
        don_gia = pol.price_unit or 0.0
        thanh_tien = pol.price_subtotal or 0.0
        ty_le_ck = pol.discount or 0.0  # Purchase order thường không có discount trong standard Odoo
        tien_chiet_khau = 0.0
        
        # Thuế GTGT
        ty_le_thue_gtgt = 0.0
        tien_thue_gtgt = 0.0
        if pol.taxes_id:
            for tax in pol.taxes_id:
                ty_le_thue_gtgt = tax.amount or 0.0
                break
            tien_thue_gtgt = (thanh_tien * ty_le_thue_gtgt) / 100

        return {
            # Hardcoded fields
            'hinh_thuc_mua_hang': 'Mua hàng hóa trong nước',
            'phuong_thuc_thanh_toan': 'Chưa thanh toán',
            'nhan_kem_hoa_don': 'Nhận kèm hóa đơn',
            
            # Date fields - ngày hiện tại
            'ngay_hach_toan': _to_date_str(datetime.date.today()),
            'ngay_chung_tu': _to_date_str(datetime.date.today()),
            'so_phieu_nhap': purchase_name,
            'so_ct_ghi_no': '',
            
            # Invoice fields - hardcoded
            'mau_so_hd': '01GTKT0/001',
            'ky_hieu_hd': 'AB/20E',
            'so_hoa_don': purchase.origin or "",
            'ngay_hoa_don': order_date_str,
            
            # Account fields - hardcoded
            'so_tk_chi': '04080082835',
            'ten_ngan_hang_chi': 'Ngân hàng quốc tế Việt Nam',
            
            # Partner info
            'ma_nha_cung_cap': partner_code,
            'ten_nha_cung_cap': partner_name,
            'dia_chi': partner_address,
            'ma_so_thue': partner_vat,
            
            # Other info - hardcoded
            'nguoi_giao_hang': 'Vũ Thị Bích Thủy',
            'dien_giai': purchase.origin or "",
            'so_tk_nhan': '0486523679',
            'ten_ngan_hang_nhan': 'Ngân hàng Nông nghiệp và Phát triển Nông thôn Việt Nam',
            'ly_do_chi': '',
            'ma_nhan_vien': 'DINHTRANTHIKIMQUYEN',
            'so_luong_ct_kem_theo': '',
            'han_thanh_toan': '',
            
            # Product info
            'ma_hang': product_code,
            'ten_hang': product_name,
            'la_dong_ghi_chu': '',
            'ma_kho': self._get_warehouse_code(purchase.picking_ids and purchase.picking_ids[0] or None),
            'hang_hoa_giu_ho': '',
            
            # Account codes - hardcoded
            'tk_kho': '156',
            'tk_cong_no': '331',
            
            # Quantity and price
            'dvt': uom_name,
            'so_luong': qty,
            'don_gia': don_gia,
            'thanh_tien': thanh_tien,
            'ty_le_ck': ty_le_ck,
            'tien_chiet_khau': tien_chiet_khau,
            
            # Tax info
            'ty_le_thue_gtgt': ty_le_thue_gtgt,
            'ty_le_thue_khac': '',
            'tien_thue_gtgt': tien_thue_gtgt,
            'tk_thue_gtgt': '1331',
            
            # Other fields
            'phi_hang_ve_kho': '',
            'nhom_hhdv_mua_vao': '',
            'so_lenh_san_xuat': '',
            'ma_khoan_muc_cp': '',
            'ma_don_vi': '',
            'ma_doi_tuong_thcp': '',
            'ma_cong_trinh': '',
            'so_don_dat_hang': '',
            'so_don_mua_hang': '',
            'so_hop_dong_mua': '',
            'so_hop_dong_ban': '',
            'ma_thong_ke': '',
            'so_khe_uoc_di_vay': '',
            'so_khe_uoc_cho_vay': '',
            'cp_khong_hop_ly': 'Không',
        }

    def _create_excel_workbook(self, data_rows):
        """Tạo workbook Excel với header"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Mua hàng hóa"

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
                    if col_def['key'] in ['don_gia', 'thanh_tien', 'tien_chiet_khau', 'tien_thue_gtgt']:
                        cell.number_format = '#,##0'
                    elif col_def['key'] in ['ty_le_ck', 'ty_le_thue_gtgt', 'ty_le_thue_khac']:
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

        purchases = self.env["purchase.order"].sudo().search(self._domain(), order="date_order asc, id asc")
        if not purchases:
            raise UserError(_("Không tìm thấy đơn mua hàng nào trong khoảng ngày đã chọn."))

        # Tạo dữ liệu
        all_rows = []
        for purchase in purchases:
            rows = self._get_purchase_line_rows(purchase)
            all_rows.extend(rows)

        if not all_rows:
            raise UserError(_("Không có dữ liệu chi tiết để xuất."))

        # Tạo Excel workbook
        wb = self._create_excel_workbook(all_rows)

        # Xuất file
        out = BytesIO()
        wb.save(out)
        out.seek(0)

        filename = f"Phieu_mua_hang_trong_nuoc_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": "purchase.export.wizard",
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
