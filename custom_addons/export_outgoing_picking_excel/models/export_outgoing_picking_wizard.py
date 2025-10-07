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
                return d.date().strftime("%d/%m/%Y")
        except Exception:
            try:
                d2 = fields.Date.from_string(val)
                if d2:
                    return d2.strftime("%d/%m/%Y")
            except Exception:
                return val
        return val
    if isinstance(val, datetime.datetime):
        return val.date().strftime("%d/%m/%Y")
    if isinstance(val, datetime.date):
        return val.strftime("%d/%m/%Y")
    return str(val)


class PickingExportWizard(models.TransientModel):
    _name = "picking.export.wizard"
    _description = "Xuất Excel lệnh xuất kho theo khoảng ngày"

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

    # ====== Định nghĩa cấu trúc cột ĐÚNG THỨ TỰ ======
    def _get_columns_definition(self):
        """
        Định nghĩa các cột xuất Excel theo đúng thứ tự yêu cầu.
        group: 'picking' hoặc 'product' để phân màu
        """
        return [
            # === NHÓM 1: Thông tin phiếu (8 cột) ===
            {'key': 'picking_type', 'name': 'Loại lệnh (*)', 'width': 20, 'group': 'picking'},
            {'key': 'picking_name', 'name': 'Số lệnh xuất kho (*)', 'width': 18, 'group': 'picking'},
            {'key': 'scheduled_date', 'name': 'Ngày lập lệnh (*)', 'width': 15, 'group': 'picking'},
            {'key': 'date_deadline', 'name': 'Hạn xuất kho', 'width': 15, 'group': 'picking'},
            {'key': 'warehouse', 'name': 'Kho xuất (*)', 'width': 20, 'group': 'picking'},
            {'key': 'partner_code', 'name': 'Mã đối tượng', 'width': 15, 'group': 'picking'},
            {'key': 'partner_name', 'name': 'Tên đối tượng nhận hàng', 'width': 30, 'group': 'picking'},
            {'key': 'note', 'name': 'Diễn giải', 'width': 30, 'group': 'picking'},

            # === NHÓM 2: Thông tin hàng hóa (29 cột) ===
            {'key': 'product_code', 'name': 'Mã hàng (*)', 'width': 18, 'group': 'product'},
            {'key': 'product_name', 'name': 'Tên hàng', 'width': 35, 'group': 'product'},
            {'key': 'product_description', 'name': 'Mô tả sản phẩm', 'width': 30, 'group': 'product'},
            {'key': 'product_spec', 'name': 'Mã quy cách', 'width': 15, 'group': 'product'},
            {'key': 'uom', 'name': 'Đơn vị tính', 'width': 12, 'group': 'product'},
            {'key': 'uom_ratio', 'name': 'Tỷ lệ chuyển đổi', 'width': 15, 'group': 'product'},
            {'key': 'location', 'name': 'Vị trí', 'width': 25, 'group': 'product'},
            {'key': 'length', 'name': 'Chiều dài', 'width': 12, 'group': 'product'},
            {'key': 'width', 'name': 'Chiều rộng', 'width': 12, 'group': 'product'},
            {'key': 'height', 'name': 'Chiều cao', 'width': 12, 'group': 'product'},
            {'key': 'radius', 'name': 'Bán kính', 'width': 12, 'group': 'product'},
            {'key': 'quantity', 'name': 'Lượng', 'width': 12, 'group': 'product'},
            {'key': 'qty_requested', 'name': 'SL yêu cầu', 'width': 12, 'group': 'product'},
            {'key': 'qty_requested_main', 'name': 'SL yêu cầu theo ĐVT chính', 'width': 20, 'group': 'product'},
            {'key': 'qty_done', 'name': 'SL thực xuất', 'width': 12, 'group': 'product'},
            {'key': 'qty_done_main', 'name': 'SL thực xuất theo ĐVT chính', 'width': 20, 'group': 'product'},
            {'key': 'lot_name', 'name': 'Số lô', 'width': 15, 'group': 'product'},
            {'key': 'lot_expiry', 'name': 'Hạn sử dụng', 'width': 15, 'group': 'product'},
            {'key': 'origin', 'name': 'Đơn đặt hàng', 'width': 18, 'group': 'product'},
            {'key': 'custom_1', 'name': 'Trường mở rộng chi tiết 1', 'width': 15, 'group': 'product'},
            {'key': 'custom_2', 'name': 'Trường mở rộng chi tiết 2', 'width': 15, 'group': 'product'},
            {'key': 'custom_3', 'name': 'Trường mở rộng chi tiết 3', 'width': 15, 'group': 'product'},
            {'key': 'custom_4', 'name': 'Trường mở rộng chi tiết 4', 'width': 15, 'group': 'product'},
            {'key': 'custom_5', 'name': 'Trường mở rộng chi tiết 5', 'width': 15, 'group': 'product'},
            {'key': 'custom_6', 'name': 'Trường mở rộng chi tiết 6', 'width': 15, 'group': 'product'},
            {'key': 'custom_7', 'name': 'Trường mở rộng chi tiết 7', 'width': 15, 'group': 'product'},
            {'key': 'custom_8', 'name': 'Trường mở rộng chi tiết 8', 'width': 15, 'group': 'product'},
            {'key': 'custom_9', 'name': 'Trường mở rộng chi tiết 9', 'width': 15, 'group': 'product'},
            {'key': 'custom_10', 'name': 'Trường mở rộng chi tiết 10', 'width': 15, 'group': 'product'},
        ]

    # ====== Helpers ======
    def _domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("scheduled_date", ">=", fields.Date.to_date(self.date_from)),
            ("scheduled_date", "<=", fields.Date.to_date(self.date_to)),
            ("picking_type_id.code", "=", "outgoing"),
        ]

        if self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))

        if self.state_filter and self.state_filter != "all":
            domain.append(("state", "=", self.state_filter))

        return domain

    def _partner_code(self, partner):
        if not partner:
            return ""
        return partner.ref or (partner.barcode if hasattr(partner, "barcode") else None) or partner.vat or str(partner.id) or ""

    def _uom_ratio(self, from_uom, to_uom):
        if not from_uom or not to_uom:
            return None
        if from_uom.id == to_uom.id:
            return 1.0
        try:
            return from_uom._compute_quantity(1.0, to_uom)
        except Exception:
            return 1.0

    def _get_move_qty_done(self, move):
        if hasattr(move, 'qty_done'):
            return move.qty_done or 0.0
        return sum(ml.qty_done for ml in move.move_line_ids) or 0.0

    def _get_warehouse_name(self, picking):
        pt = picking.picking_type_id
        if pt and pt.warehouse_id:
            return pt.warehouse_id.name
        if hasattr(picking.location_id, 'warehouse_id') and picking.location_id.warehouse_id:
            return picking.location_id.warehouse_id.name
        return ""

    def _extract_sale_refs(self, move):
        """
        Trả về (sale_line, sale_order_name) nếu tồn tại, ngược lại (None, picking.origin or '').
        """
        sol = getattr(move, 'sale_line_id', False) or False
        so_name = ""
        if sol and sol.order_id:
            so_name = sol.order_id.name or ""
        else:
            so_name = move.picking_id.origin or ""
        return sol, so_name

    def _convert_qty_pair(self, qty_in_src_uom, src_uom, uom_line, uom_main):
        """
        Trả về (qty_for_column_qty_requested, qty_requested_main)
        - qty_for_column_qty_requested theo uom_line
        - qty_requested_main theo uom_main
        """
        qty_line = qty_in_src_uom
        if src_uom and uom_line and src_uom.id != uom_line.id:
            qty_line = src_uom._compute_quantity(qty_in_src_uom, uom_line)
        qty_main = qty_line
        if uom_line and uom_main and uom_line.id != uom_main.id:
            qty_main = uom_line._compute_quantity(qty_line, uom_main)
        return qty_line, qty_main

    def _get_move_line_rows(self, picking):
        rows = []
        pt = picking.picking_type_id
        warehouse_name = self._get_warehouse_name(picking)

        if picking.move_line_ids:
            for ml in picking.move_line_ids:
                move = ml.move_id
                prod = ml.product_id
                if not prod:
                    continue

                product_name = prod.display_name or prod.name or ""
                product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""

                # UoM chọn theo line trước, rồi về UoM chính
                uom_line = ml.product_uom_id or move.product_uom or prod.uom_id
                uom_name = (uom_line and uom_line.name) or ""
                uom_main = prod.uom_id
                ratio = self._uom_ratio(uom_line, uom_main)

                # Lấy tham chiếu Sale
                sol, so_name = self._extract_sale_refs(move)

                # ====== SL yêu cầu từ Sale Order Line (nếu có) ======
                if sol:
                    qty_req_src = sol.product_uom_qty or 0.0
                    src_uom = sol.product_uom or prod.uom_id
                    qty_req, qty_req_main = self._convert_qty_pair(qty_req_src, src_uom, uom_line, uom_main)
                else:
                    # fallback theo move
                    qty_req = move.product_uom_qty or 0.0
                    qty_req_main = uom_line._compute_quantity(qty_req, uom_main) if (uom_line and uom_main) else qty_req

                # ====== SL thực xuất từ qty_delivered (nếu có) ======
                if sol:
                    qty_done_src = sol.qty_delivered or 0.0
                    src_uom = sol.product_uom or prod.uom_id
                    qty_done, qty_done_main = self._convert_qty_pair(qty_done_src, src_uom, uom_line, uom_main)
                else:
                    qty_done = ml.qty_done or 0.0
                    qty_done_main = uom_line._compute_quantity(qty_done, uom_main) if (uom_line and uom_main) else qty_done

                lot_name = ""
                lot_expiry = ""
                if ml.lot_id:
                    lot_name = ml.lot_id.name or ""
                    life_date = getattr(ml.lot_id, "life_date", None) or \
                                getattr(ml.lot_id, "expiration_date", None) or \
                                getattr(ml.lot_id, "use_date", None)
                    lot_expiry = _to_date_str(life_date)

                location_name = (ml.location_id and ml.location_id.complete_name) or \
                                (ml.location_id and ml.location_id.display_name) or ""

                rows.append({
                    'picking_type': pt.name or "",
                    'picking_name': picking.display_name or picking.name or "",
                    'scheduled_date': _to_date_str(picking.scheduled_date),
                    'date_deadline': _to_date_str(picking.date_deadline),
                    'warehouse': warehouse_name,
                    'partner_code': self._partner_code(picking.partner_id),
                    'partner_name': (picking.partner_id and picking.partner_id.name) or "",
                    'note': picking.note or "",
                    'product_code': product_code,
                    'product_name': product_name,
                    'product_description': (prod.description_sale or prod.description_picking or prod.description) or "",
                    'product_spec': getattr(prod, "default_code", "") or "",
                    'uom': uom_name,
                    'uom_ratio': ratio,
                    'location': location_name,
                    'length': "",
                    'width': "",
                    'height': "",
                    'radius': "",
                    'quantity': "",
                    'qty_requested': qty_req,
                    'qty_requested_main': qty_req_main,
                    'qty_done': qty_done,
                    'qty_done_main': qty_done_main,
                    'lot_name': lot_name,
                    'lot_expiry': lot_expiry,
                    'origin': so_name or "",
                    'custom_1': "",
                    'custom_2': "",
                    'custom_3': "",
                    'custom_4': "",
                    'custom_5': "",
                    'custom_6': "",
                    'custom_7': "",
                    'custom_8': "",
                    'custom_9': "",
                    'custom_10': "",
                })
        else:
            for mv in picking.move_ids_without_package:
                prod = mv.product_id
                if not prod:
                    continue

                product_name = prod.display_name or prod.name or ""
                product_code = prod.default_code or (prod.barcode if hasattr(prod, 'barcode') else "") or ""

                uom_line = mv.product_uom or prod.uom_id
                uom_name = (uom_line and uom_line.name) or ""
                uom_main = prod.uom_id
                ratio = self._uom_ratio(uom_line, uom_main)

                # Lấy tham chiếu Sale
                sol, so_name = self._extract_sale_refs(mv)

                # ====== SL yêu cầu từ Sale Order Line (nếu có) ======
                if sol:
                    qty_req_src = sol.product_uom_qty or 0.0
                    src_uom = sol.product_uom or prod.uom_id
                    qty_req, qty_req_main = self._convert_qty_pair(qty_req_src, src_uom, uom_line, uom_main)
                else:
                    qty_req = mv.product_uom_qty or 0.0
                    qty_req_main = uom_line._compute_quantity(qty_req, uom_main) if (uom_line and uom_main) else qty_req

                # ====== SL thực xuất từ qty_delivered (nếu có) ======
                if sol:
                    qty_done_src = sol.qty_delivered or 0.0
                    src_uom = sol.product_uom or prod.uom_id
                    qty_done, qty_done_main = self._convert_qty_pair(qty_done_src, src_uom, uom_line, uom_main)
                else:
                    qty_done = self._get_move_qty_done(mv)
                    qty_done_main = uom_line._compute_quantity(qty_done, uom_main) if (uom_line and uom_main) else qty_done

                rows.append({
                    'picking_type': pt.name or "",
                    'picking_name': picking.display_name or picking.name or "",
                    'scheduled_date': _to_date_str(picking.scheduled_date),
                    'date_deadline': _to_date_str(picking.date_deadline),
                    'warehouse': warehouse_name,
                    'partner_code': self._partner_code(picking.partner_id),
                    'partner_name': (picking.partner_id and picking.partner_id.name) or "",
                    'note': picking.note or "",
                    'product_code': product_code,
                    'product_name': product_name,
                    'product_description': (prod.description_sale or prod.description_picking or prod.description) or "",
                    'product_spec': getattr(prod, "default_code", "") or "",
                    'uom': uom_name,
                    'uom_ratio': ratio,
                    'location': (mv.location_id and mv.location_id.complete_name) or "",
                    'length': "",
                    'width': "",
                    'height': "",
                    'radius': "",
                    'quantity': "",
                    'qty_requested': qty_req,
                    'qty_requested_main': qty_req_main,
                    'qty_done': qty_done,
                    'qty_done_main': qty_done_main,
                    'lot_name': "",
                    'lot_expiry': "",
                    'origin': so_name or "",
                    'custom_1': "",
                    'custom_2': "",
                    'custom_3': "",
                    'custom_4': "",
                    'custom_5': "",
                    'custom_6': "",
                    'custom_7': "",
                    'custom_8': "",
                    'custom_9': "",
                    'custom_10': "",
                })
        return rows

    def _create_excel_workbook(self, data_rows):
        """Tạo workbook Excel với 2 header rows.
        9 dòng đầu tiên bỏ qua, header ở dòng 8-9, data bắt đầu từ dòng 10."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Lệnh xuất kho"

        columns = self._get_columns_definition()

        # Định nghĩa styles
        header1_font = Font(name='Arial', size=12, bold=True, color='FFFFFF')
        header1_fill_picking = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')  # Xanh dương
        header1_fill_product = PatternFill(start_color='70AD47', end_color='70AD47', fill_type='solid')  # Xanh lá
        header1_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        header2_font = Font(name='Arial', size=10, bold=True, color='000000')
        header2_fill_picking = PatternFill(start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')  # Xanh nhạt
        header2_fill_product = PatternFill(start_color='E2EFD9', end_color='E2EFD9', fill_type='solid')  # Xanh lá nhạt
        header2_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        border_side = Side(style='thin', color='000000')
        border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

        cell_alignment = Alignment(horizontal='left', vertical='center', wrap_text=False)
        number_alignment = Alignment(horizontal='right', vertical='center')

        # Các chỉ số hàng
        HEADER1_ROW = 8
        HEADER2_ROW = 9
        DATA_START = 10

        # === HEADER ROW 1: Group headers ===
        picking_start = 1
        picking_end = sum(1 for c in columns if c['group'] == 'picking')
        product_start = picking_end + 1
        product_end = len(columns)

        ws.merge_cells(start_row=HEADER1_ROW, start_column=picking_start, end_row=HEADER1_ROW, end_column=picking_end)
        cell = ws.cell(row=HEADER1_ROW, column=picking_start)
        cell.value = "THÔNG TIN PHIẾU"
        cell.font = header1_font
        cell.fill = header1_fill_picking
        cell.alignment = header1_alignment
        cell.border = border

        ws.merge_cells(start_row=HEADER1_ROW, start_column=product_start, end_row=HEADER1_ROW, end_column=product_end)
        cell = ws.cell(row=HEADER1_ROW, column=product_start)
        cell.value = "THÔNG TIN HÀNG HÓA"
        cell.font = header1_font
        cell.fill = header1_fill_product
        cell.alignment = header1_alignment
        cell.border = border

        # === HEADER ROW 2: Column names ===
        for col_idx, col_def in enumerate(columns, start=1):
            cell = ws.cell(row=HEADER2_ROW, column=col_idx)
            cell.value = col_def['name']
            cell.font = header2_font

            if col_def['group'] == 'picking':
                cell.fill = header2_fill_picking
            else:
                cell.fill = header2_fill_product

            cell.alignment = header2_alignment
            cell.border = border
            ws.column_dimensions[get_column_letter(col_idx)].width = col_def.get('width', 15)

        # Freeze panes: cố định 9 dòng đầu và cột A
        ws.freeze_panes = 'B{}'.format(DATA_START)

        # === DATA ROWS ===
        for row_idx, row_data in enumerate(data_rows, start=DATA_START):
            for col_idx, col_def in enumerate(columns, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                value = row_data.get(col_def['key'], "")

                if value is None:
                    value = ""

                cell.value = value
                cell.border = border

                if isinstance(value, (int, float)) and value != "":
                    cell.alignment = number_alignment
                    if col_def['key'] in ['uom_ratio', 'qty_requested', 'qty_requested_main', 'qty_done', 'qty_done_main']:
                        if value != "":
                            cell.number_format = '#,##0.00'
                else:
                    cell.alignment = cell_alignment

        # Set row heights cho header
        ws.row_dimensions[HEADER1_ROW].height = 25
        ws.row_dimensions[HEADER2_ROW].height = 35

        return wb

    # ====== Action ======
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

        filename = f"Lenh_xuat_kho_{self.date_from}_{self.date_to}.xlsx"
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
