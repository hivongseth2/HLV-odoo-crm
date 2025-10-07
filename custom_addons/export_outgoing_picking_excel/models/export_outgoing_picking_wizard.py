# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.modules.module import get_module_resource
import base64

import datetime
from io import BytesIO

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


def _to_date_str(val):
    if not val:
        return ""
    if isinstance(val, str):
        # Trường hợp Odoo trả dạng chuỗi ISO
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
    _description = "Xuất Excel lệnh xuất kho theo khoảng ngày (dùng template, full cột)"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    # PHẠM VI KHO
    warehouse_scope = fields.Selection(
        [
            ("all", "Tất cả kho"),
            ("some", "Chọn kho cụ thể"),
        ],
        string="Phạm vi kho",
        default="all",
        required=True,
        help="Chọn 'Tất cả kho' để xuất gộp toàn bộ kho trong 1 file."
    )
    warehouse_ids = fields.Many2many(
        "stock.warehouse",
        string="Kho xuất",
        help="Chọn 1 hoặc nhiều kho khi phạm vi = 'Chọn kho cụ thể'",
    )

    # (Giữ nếu bạn vẫn muốn lọc sâu theo 1 loại lệnh cụ thể)
    picking_type_id = fields.Many2one(
        "stock.picking.type",
        string="Loại lệnh (mặc định: Lệnh xuất kho)",
        domain=[("code", "=", "outgoing")],
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

    TEMPLATE_NAME = "Lenh_xuat_kho.xlsx"
    TEMPLATE_REL_PATH = ("static", "template",)

    # ====== Helpers ======
    def _get_template_path(self):
        path = get_module_resource(
            "export_outgoing_picking_excel",
            *(self.TEMPLATE_REL_PATH + (self.TEMPLATE_NAME,))
        )
        if not path:
            raise UserError(_("Không tìm thấy file template Excel trong module."))
        return path

    def _domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("scheduled_date", ">=", fields.Date.to_date(self.date_from)),
            ("scheduled_date", "<=", fields.Date.to_date(self.date_to)),
            ("picking_type_id.code", "=", "outgoing"),
        ]

        # Lọc theo kho (nếu chọn kho cụ thể)
        if self.warehouse_scope == "some" and self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))

        # Lọc sâu theo 1 picking type cụ thể (nếu có chọn)
        if self.picking_type_id:
            domain.append(("picking_type_id", "=", self.picking_type_id.id))

        # Lọc trạng thái (nếu khác 'all')
        if self.state_filter and self.state_filter != "all":
            domain.append(("state", "=", self.state_filter))

        return domain


    def _find_header_row(self, ws, scan_rows=100):
        """Tìm hàng header: hàng có nhiều ô text nhất trong 1..scan_rows."""
        best_row, best_count = None, 0
        for r in range(1, min(ws.max_row, scan_rows) + 1):
            values = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
            count = sum(1 for v in values if isinstance(v, str) and v.strip())
            if count > best_count:
                best_row, best_count = r, count
        if not best_row:
            raise UserError(_("Không xác định được dòng tiêu đề trong template."))
        return best_row

    def _partner_code(self, partner):
        return partner.ref or (partner.barcode if hasattr(partner, "barcode") else None) or (partner.vat or None) or (partner.id and str(partner.id)) or ""

    def _uom_ratio(self, from_uom, to_uom):
        """
        Trả về (qty_in_to = 1 from_uom quy đổi sang to_uom), dùng _compute_quantity để an toàn.
        Nếu cùng UoM => 1.0
        """
        if not from_uom or not to_uom:
            return None
        if from_uom.id == to_uom.id:
            return 1.0
        return from_uom._compute_quantity(1.0, to_uom)

    def _get_move_line_rows(self, picking):
        """
        Trả về danh sách dict mỗi dòng xuất (ưu tiên stock.move.line; nếu không có, fallback stock.move).
        Mục tiêu: lấp đầy tối đa các cột chi tiết (ĐVT, SL yêu cầu, SL thực xuất, Lô, HSD, Vị trí...)
        """
        rows = []
        pt = picking.picking_type_id
        warehouse_name = (pt.warehouse_id and pt.warehouse_id.name) or \
                         (getattr(picking.location_id, "get_warehouse", None) and picking.location_id.get_warehouse() and picking.location_id.get_warehouse().name) or ""

        # Duyệt move line để bắt được lô/ hạn dùng & vị trí thực tế
        if picking.move_line_ids:
            for ml in picking.move_line_ids:
                move = ml.move_id
                prod = ml.product_id
                product_name = prod.display_name or prod.name or ""
                product_code = prod.default_code or (prod.barcode or "")
                uom_line = ml.product_uom_id or move.product_uom or prod.uom_id
                uom_name = (uom_line and uom_line.name) or ""
                uom_main = prod.uom_id
                ratio = self._uom_ratio(uom_line, uom_main)

                # SL yêu cầu: ưu tiên từ move (độc lập với qty_done)
                qty_req = move.product_uom_qty or 0.0
                qty_req_main  = uom_line._compute_quantity(qty_req,  uom_main) if (uom_line and uom_main) else qty_req

                # SL thực xuất: từ move line
                qty_done = ml.qty_done or 0.0
                qty_done_main = uom_line._compute_quantity(qty_done, uom_main) if (uom_line and uom_main) else qty_done

                lot_name = ""
                lot_expiry = ""
                if ml.lot_id:
                    lot_name = ml.lot_id.name or ""
                    # life_date / use_date tuỳ cấu hình lô
                    life_date = getattr(ml.lot_id, "life_date", None) or getattr(ml.lot_id, "expiration_date", None)
                    lot_expiry = _to_date_str(life_date)

                location_name = (ml.location_id and ml.location_id.complete_name) or (ml.location_id and ml.location_id.display_name) or ""

                rows.append({
                    # Header-level (phiếu)
                    "Loại lệnh (*)": pt.name or "",
                    "Số lệnh xuất kho (*)": picking.display_name or picking.name or "",
                    "Ngày lập lệnh (*)": _to_date_str(picking.scheduled_date),
                    "Hạn xuất kho": _to_date_str(picking.date_deadline),
                    "Kho xuất (*)": warehouse_name,
                    "Mã đối tượng": self._partner_code(picking.partner_id),
                    "Tên đối tượng nhận hàng": (picking.partner_id and picking.partner_id.name) or "",
                    "Diễn giải": picking.note or "",
                    "Đơn đặt hàng": picking.origin or "",

                    # Sản phẩm/chi tiết
                    "Mã hàng (*)": product_code,
                    "Tên hàng": product_name,
                    "Mô tả sản phẩm": (prod.description_sale or prod.description_picking or prod.description) or "",
                    "Mã quy cách": getattr(prod, "default_code", "") or "",
                    "Đơn vị tính": uom_name,
                    "Tỷ lệ chuyển đổi": ratio,  # 1 ĐVT dòng -> ? ĐVT chính
                    "Vị trí": location_name,
                    "Chiều dài": None,  # nếu có field riêng thì map thêm
                    "Chiều rộng": None,
                    "Chiều cao": None,
                    "Bán kính": None,
                    "Lượng": None,  # tùy doanh nghiệp định nghĩa
                    "SL yêu cầu": qty_req,
                    "SL yêu cầu theo ĐVT chính": qty_req_main,
                    "SL thực xuất": qty_done,
                    "SL thực xuất theo ĐVT chính": qty_done_main,
                    "Số lô": lot_name,
                    "Hạn sử dụng": lot_expiry,

                    # Trường mở rộng chi tiết 1..10 (để trống, hoặc bạn map thêm)
                    "Trường mở rộng chi tiết 1": "",
                    "Trường mở rộng chi tiết 2": "",
                    "Trường mở rộng chi tiết 3": "",
                    "Trường mở rộng chi tiết 4": "",
                    "Trường mở rộng chi tiết 5": "",
                    "Trường mở rộng chi tiết 6": "",
                    "Trường mở rộng chi tiết 7": "",
                    "Trường mở rộng chi tiết 8": "",
                    "Trường mở rộng chi tiết 9": "",
                    "Trường mở rộng chi tiết 10": "",
                })
        else:
            # Fallback: không có move line, dùng move (ít thông tin hơn, không có lô)
            for mv in picking.move_ids_without_package:
                prod = mv.product_id
                product_name = prod.display_name or prod.name or ""
                product_code = prod.default_code or (prod.barcode or "")
                uom_line = mv.product_uom or prod.uom_id
                uom_name = (uom_line and uom_line.name) or ""
                uom_main = prod.uom_id
                ratio = self._uom_ratio(uom_line, uom_main)

                qty_req = mv.product_uom_qty or 0.0
                qty_req_main  = uom_line._compute_quantity(qty_req,  uom_main) if (uom_line and uom_main) else qty_req

                rows.append({
                    "Loại lệnh (*)": pt.name or "",
                    "Số lệnh xuất kho (*)": picking.display_name or picking.name or "",
                    "Ngày lập lệnh (*)": _to_date_str(picking.scheduled_date),
                    "Hạn xuất kho": _to_date_str(picking.date_deadline),
                    "Kho xuất (*)": warehouse_name,
                    "Mã đối tượng": self._partner_code(picking.partner_id),
                    "Tên đối tượng nhận hàng": (picking.partner_id and picking.partner_id.name) or "",
                    "Diễn giải": picking.note or "",
                    "Đơn đặt hàng": picking.origin or "",

                    "Mã hàng (*)": product_code,
                    "Tên hàng": product_name,
                    "Mô tả sản phẩm": (prod.description_sale or prod.description_picking or prod.description) or "",
                    "Mã quy cách": getattr(prod, "default_code", "") or "",
                    "Đơn vị tính": uom_name,
                    "Tỷ lệ chuyển đổi": ratio,
                    "Vị trí": (mv.location_id and mv.location_id.complete_name) or "",
                    "Chiều dài": None,
                    "Chiều rộng": None,
                    "Chiều cao": None,
                    "Bán kính": None,
                    "Lượng": None,
                    "SL yêu cầu": qty_req,
                    "SL yêu cầu theo ĐVT chính": qty_req_main,
                    "SL thực xuất": mv.quantity_done or 0.0,
                    "SL thực xuất theo ĐVT chính": (uom_line._compute_quantity(mv.quantity_done, uom_main) if (uom_line and uom_main) else (mv.quantity_done or 0.0)),
                    "Số lô": "",
                    "Hạn sử dụng": "",

                    "Trường mở rộng chi tiết 1": "",
                    "Trường mở rộng chi tiết 2": "",
                    "Trường mở rộng chi tiết 3": "",
                    "Trường mở rộng chi tiết 4": "",
                    "Trường mở rộng chi tiết 5": "",
                    "Trường mở rộng chi tiết 6": "",
                    "Trường mở rộng chi tiết 7": "",
                    "Trường mở rộng chi tiết 8": "",
                    "Trường mở rộng chi tiết 9": "",
                    "Trường mở rộng chi tiết 10": "",
                })
        return rows

    # ====== Action ======
    def action_export(self):
        self.ensure_one()
        if load_workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho nào trong khoảng ngày đã chọn."))

        # Mở template & xác định header
        template_path = self._get_template_path()
        wb = load_workbook(template_path)
        ws = wb.active
        header_row = self._find_header_row(ws)
        # Map tên cột -> index cột
        header_map = {}
        for c in range(1, ws.max_column + 1):
            name = ws.cell(row=header_row, column=c).value
            if name:
                header_map[str(name).strip()] = c

        # Ghi từ dòng kế tiếp sau header
        row_idx = header_row + 1

        # Duyệt từng picking -> tạo các dòng move line
        for p in pickings:
            rows = self._get_move_line_rows(p)
            for r in rows:
                # Ghi từng cột theo header có trong template (điền được bao nhiêu điền bấy nhiêu)
                for header_name, col in header_map.items():
                    if header_name in r:
                        val = r[header_name]
                        # Định dạng ngày cho các cột ngày
                        if header_name in ("Ngày lập lệnh (*)", "Hạn xuất kho", "Hạn sử dụng"):
                            ws.cell(row=row_idx, column=col, value=_to_date_str(val))
                        else:
                            ws.cell(row=row_idx, column=col, value=val)
                row_idx += 1

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

