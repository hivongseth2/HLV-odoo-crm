# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import datetime
from io import BytesIO

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

class PickingExportShopeeWizard(models.TransientModel):
    _name = "picking.export.shopee.wizard"
    _inherit = "picking.export.wizard"
    _description = "Xuất Excel lệnh xuất kho Shopee"

    def _domain(self):
        """
        Override _domain to filter for Shopee orders only
        """
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

        # Filter: Only customers with 'shopee' in name (case-insensitive)
        domain.append(('partner_id.name', 'ilike', 'shopee'))

        return domain

    def _thuoc_combo_code_for_move(self, move):
        """
        Overridden to use BoM Kit logic.
        If the product on the Sale Order Line is a Kit (has a phantom BoM),
        return its default_code.
        """
        sol = getattr(move, 'sale_line_id', False)
        if not sol:
            return ''
        
        sol_product = sol.product_id
        if not sol_product:
            return ''

        # If move product is same as SOL product, it hasn't successfully exploded into components 
        # (or it's not a kit).
        if sol_product.id == move.product_id.id:
            return ''

        # Check if sol_product is a BoM Kit (phantom)
        # We search for any active phantom BoM for this product template.
        is_kit = self.env['mrp.bom'].search_count([
            ('product_tmpl_id', '=', sol_product.product_tmpl_id.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])
        
        if is_kit:
            return sol_product.default_code
            
        return ''

    def _normalize_text(self, text):
        if not text:
            return ''
        return ' '.join(str(text).strip().lower().split())

    def _extract_bom_description(self, move=None, ml=None):
        description = ''
        if move:
            description = getattr(move, 'description_bom_line', False) or ''
        if not description and ml:
            description = getattr(ml, 'description_bom_line', False) or ''
        return description.strip() if isinstance(description, str) else ''

    def _find_sale_line_by_bom_description(self, so, bom_description):
        """
        Try to map description_bom_line from OUT moves back to SO line (kit parent).
        """
        if not so or not bom_description:
            return False

        desc_norm = self._normalize_text(bom_description)
        if not desc_norm:
            return False

        # Pass 1: exact / contains against SOL name and product labels
        for sol in so.order_line:
            prod = sol.product_id
            if not prod:
                continue

            probe_values = [
                sol.name,
                prod.display_name,
                prod.name,
                prod.default_code,
            ]
            normalized_values = [self._normalize_text(v) for v in probe_values if v]
            if not normalized_values:
                continue

            if desc_norm in normalized_values:
                return sol
            if any(desc_norm in nv or nv in desc_norm for nv in normalized_values):
                return sol

        # Pass 2: fallback by product default_code token inside description
        for sol in so.order_line:
            prod = sol.product_id
            code = prod.default_code if prod else False
            if code and self._normalize_text(code) in desc_norm:
                return sol

        return False

    def _get_move_line_rows(self, picking):
        """
        Ensure BoM kit exports include both parent kit line and component lines.
        Parent line is detected from:
        1) sale_line_id mismatch (standard Odoo kit explosion), or
        2) description_bom_line on OUT move/move line (fallback as user explained).
        """
        rows = super()._get_move_line_rows(picking)
        if not rows:
            return rows

        move_lines = picking.move_line_ids
        source_moves = move_lines.mapped('move_id') if move_lines else picking.move_ids_without_package
        if not source_moves:
            return rows

        so = self._find_sale_order(source_moves[0], picking)

        # Keep first move line per move for context
        first_ml_by_move_id = {}
        if move_lines:
            for ml in move_lines:
                mv = ml.move_id
                if mv and mv.id not in first_ml_by_move_id:
                    first_ml_by_move_id[mv.id] = ml

        # Group component moves by parent SOL (kit header)
        combo_source_by_key = {}
        for move in source_moves:
            if not move.product_id:
                continue
            ml = first_ml_by_move_id.get(move.id)
            bom_description = self._extract_bom_description(move=move, ml=ml)

            parent_sol = False
            move_sol = getattr(move, 'sale_line_id', False)

            # Standard Odoo kit behavior: component move linked to parent SOL
            if move_sol and move_sol.product_id and move_sol.product_id.id != move.product_id.id:
                parent_sol = move_sol
            # Fallback: OUT line contains description_bom_line only
            elif bom_description:
                candidate_sol = self._find_sale_line_by_bom_description(so, bom_description)
                if candidate_sol and candidate_sol.product_id and candidate_sol.product_id.id != move.product_id.id:
                    parent_sol = candidate_sol

            if not parent_sol or not parent_sol.product_id:
                continue

            group_key = "sol:%s" % parent_sol.id
            if group_key not in combo_source_by_key:
                combo_source_by_key[group_key] = {
                    'sol': parent_sol,
                    'parent_product': parent_sol.product_id,
                    'move': move,
                    'ml': ml,
                    'bom_description': bom_description,
                    'component_product_ids': set(),
                }
            combo_source_by_key[group_key]['component_product_ids'].add(move.product_id.id)
            if bom_description and not combo_source_by_key[group_key]['bom_description']:
                combo_source_by_key[group_key]['bom_description'] = bom_description

        if not combo_source_by_key:
            return rows

        # Existing parent rows (if already present, do not add duplicates)
        existing_parent_keys = {
            "sol:%s" % row.get('_sale_line_id')
            for row in rows
            if row.get('_sale_line_id') and row.get('_product_id') == row.get('_parent_product_id')
        }

        default_ref_row = rows[0]
        pending_inserts = []

        for group_key, payload in combo_source_by_key.items():
            if group_key in existing_parent_keys:
                continue

            sol = payload['sol']
            parent_product = payload['parent_product']
            move = payload['move']
            ml = payload['ml']
            bom_description = payload['bom_description']
            component_product_ids = payload['component_product_ids']

            # Insert before the first component row of this kit group
            insert_idx = len(rows)
            for idx, row in enumerate(rows):
                same_sol = row.get('_sale_line_id') == sol.id
                same_desc = bool(
                    bom_description and
                    row.get('_description_bom_line') and
                    self._normalize_text(row.get('_description_bom_line')) == self._normalize_text(bom_description)
                )
                is_component = row.get('_product_id') in component_product_ids
                if (same_sol or same_desc) and is_component:
                    insert_idx = idx
                    break

            ref_row = rows[insert_idx] if insert_idx < len(rows) else default_ref_row

            parent_row = self._build_row_data(
                picking, so, parent_product, ml, move,
                ref_row.get('ngay_hoa_don', ''),
                ref_row.get('so_chung_tu', picking.name or ''),
                ref_row.get('ma_khach_hang', ''),
                ref_row.get('ten_khach_hang', ''),
                ref_row.get('dia_chi', ''),
                ref_row.get('ma_so_thue', ''),
                ref_row.get('so_phieu_xuat', (so.name if so else (picking.origin or ''))),
                ref_row.get('ma_nhan_vien', ''),
                ref_row.get('dien_giai', ''),
                ref_row.get('ly_do_xuat', ''),
                ref_row.get('ma_kho', ''),
                sale_line=sol,
            )
            parent_row['_description_bom_line'] = bom_description or parent_row.get('_description_bom_line') or ''
            parent_row['_is_parent_combo'] = True

            pending_inserts.append((insert_idx, parent_row))

        # Insert from back to front so indices remain stable
        for insert_idx, row_data in sorted(pending_inserts, key=lambda item: item[0], reverse=True):
            rows.insert(insert_idx, row_data)

        return rows

    def _build_row_data(self, picking, so, prod, ml, move,
                        scheduled_date_str, picking_name, partner_code, partner_name,
                        partner_address, partner_vat, sale_name, sale_user_code,
                        dien_giai, ly_do_xuat, warehouse_code, pos_line=None, sale_line=None, forced_qty=None):
        """
        Override to fix fields showing FALSE and hardcode warehouse code, 
        plus apply SHOPEE OVERRIDE LOGIC from stock_export_wizard.
        """
        row = super()._build_row_data(
            picking, so, prod, ml, move,
            scheduled_date_str, picking_name, partner_code, partner_name,
            partner_address, partner_vat, sale_name, sale_user_code,
            dien_giai, ly_do_xuat, warehouse_code, pos_line=pos_line, sale_line=sale_line, forced_qty=forced_qty
        )
        
        # --- SHOPEE OVERRIDE LOGIC (Ported from stock_export_wizard.py) ---
        if so and hasattr(so, 'shopee_shop_id') and so.shopee_shop_id:
            shop = so.shopee_shop_id
            # Check Account Name contains 2014645
            account = getattr(shop, 'account_id', False)
            if account and '2014645' in getattr(account, 'name', ''):
                shop_id = getattr(shop, 'shop_identifier', 0)
                target_pid = False
                
                if shop_id == 796817584:
                    target_pid = 9715 # MILWAUKEE
                elif shop_id == 1357810112:
                    target_pid = 9720 # DEWALT
                elif shop_id == 326259406:
                    target_pid = 9701 # HLV
                
                if target_pid:
                    target_partner = self.env['res.partner'].browse(target_pid)
                    if target_partner.exists():
                        # Recalculate partner code
                        s_ref = False
                        if target_partner.commercial_partner_id and target_partner.commercial_partner_id.ref:
                            s_ref = target_partner.commercial_partner_id.ref
                        elif target_partner.parent_id and target_partner.parent_id.ref:
                            s_ref = target_partner.parent_id.ref
                        elif target_partner.ref:
                            s_ref = target_partner.ref
                        
                        new_partner_code = s_ref or ''
                        new_partner_name = target_partner.name
                        
                        # Override Row Data
                        row['ten_khach_hang'] = new_partner_name
                        row['ma_khach_hang'] = new_partner_code
                        row['nguoi_nop'] = new_partner_name
                        
                        # Fix ly_do_xuat / dien_giai
                        new_reason = "Xuất kho bán hàng cho " + new_partner_name
                        row['ly_do_xuat'] = new_reason
                        row['dien_giai'] = new_reason
                        
                        # Update address if needed? Stock wizard doesn't explicitly do it but it's good practice
                        # For now sticking to what stock wizard did (mostly name/code/reason)

        # 1. Fix FALSE issue for 3 fields
        if not row.get('hinh_thuc_giao_hang'):
             row['hinh_thuc_giao_hang'] = ''
        if not row.get('hinh_thuc_thanh_toan_so'):
             row['hinh_thuc_thanh_toan_so'] = ''
        if not row.get('ben_tra_phi_van_chuyen'):
             row['ben_tra_phi_van_chuyen'] = ''

        # 2. Hardcode Ma kho
        row['ma_kho'] = 'HLV'
        row['tk_kho'] = '1561'
        row['la_dong_ghi_chu'] = row.get('la_dong_ghi_chu') or 'không'
        row['hang_khuyen_mai'] = row.get('hang_khuyen_mai') or 'Không'
        row['hh_khong_th_tren_to_khai'] = row.get('hh_khong_th_tren_to_khai') or 'Không'

        # 3. Chuẩn hóa ngày theo dd/mm/YYYY
        posting_date = picking.date_done or picking.scheduled_date or fields.Datetime.now()
        posting_date_str = self._to_template_date(posting_date)
        row['ngay_hach_toan'] = posting_date_str
        row['ngay_chung_tu'] = posting_date_str
        row['ngay_hoa_don'] = posting_date_str
        if not row.get('so_phieu_xuat'):
            row['so_phieu_xuat'] = picking_name or sale_name or ''

        # Internal metadata for row post-processing (not exported as columns)
        sol = sale_line or (getattr(move, 'sale_line_id', False) if move else False)
        row['_sale_line_id'] = sol.id if sol else False
        row['_product_id'] = prod.id if prod else False
        row['_parent_product_id'] = sol.product_id.id if sol and sol.product_id else False
        row['_is_component_of_kit'] = bool(
            sol and sol.product_id and prod and sol.product_id.id != prod.id
        )
        row['_description_bom_line'] = self._extract_bom_description(move=move, ml=ml)
        row['_is_parent_combo'] = bool(
            sol and sol.product_id and prod and sol.product_id.id == prod.id and row['_description_bom_line']
        )
        
        return row

    def _to_template_date(self, value):
        if not value:
            return ''

        date_value = False
        if isinstance(value, datetime.datetime):
            date_value = value.date()
        elif isinstance(value, datetime.date):
            date_value = value
        elif isinstance(value, str):
            try:
                dt_value = fields.Datetime.from_string(value)
                if dt_value:
                    date_value = dt_value.date() if hasattr(dt_value, 'date') else dt_value
            except Exception:
                date_value = False
            if not date_value:
                try:
                    date_value = fields.Date.from_string(value)
                except Exception:
                    date_value = False

        if not date_value:
            return ''
        return date_value.strftime("%d/%m/%Y")

    def _get_columns_definition(self):
        """
        Giữ đúng 52 cột cho file Shopee (không phụ thuộc template gốc).
        Width để số nguyên cho dễ đọc/duy trì.
        """
        return [
            {'key': 'hinh_thuc_ban_hang', 'name': 'Hình thức bán hàng', 'width': 20},
            {'key': 'phuong_thuc_thanh_toan', 'name': 'Phương thức thanh toán', 'width': 22},
            {'key': 'kiem_phieu_xuat_kho', 'name': 'Kiêm phiếu xuất kho', 'width': 21},
            {'key': 'lap_kem_hoa_don', 'name': 'Lập kèm hóa đơn', 'width': 18},
            {'key': 'da_lap_hoa_don', 'name': 'Đã lập hóa đơn', 'width': 16},
            {'key': 'ngay_hach_toan', 'name': 'Ngày hạch toán (*)', 'width': 19},
            {'key': 'ngay_chung_tu', 'name': 'Ngày chứng từ (*)', 'width': 19},
            {'key': 'so_chung_tu', 'name': 'Số chứng từ (*)', 'width': 17},
            {'key': 'so_phieu_xuat', 'name': 'Số phiếu xuất', 'width': 17},
            {'key': 'mau_so_hd', 'name': 'Mẫu số HĐ', 'width': 13},
            {'key': 'ky_hieu_hd', 'name': 'Ký hiệu HĐ', 'width': 16},
            {'key': 'so_hoa_don', 'name': 'Số hóa đơn', 'width': 17},
            {'key': 'ngay_hoa_don', 'name': 'Ngày hóa đơn', 'width': 16},
            {'key': 'ma_khach_hang', 'name': 'Mã khách hàng', 'width': 18},
            {'key': 'ten_khach_hang', 'name': 'Tên khách hàng', 'width': 24},
            {'key': 'dia_chi', 'name': 'Địa chỉ', 'width': 25},
            {'key': 'ma_so_thue', 'name': 'Mã số thuế', 'width': 16},
            {'key': 'don_vi_giao_dai_ly', 'name': 'Đơn vị giao đại lý', 'width': 17},
            {'key': 'nguoi_nop', 'name': 'Người nộp', 'width': 17},
            {'key': 'nop_vao_tk', 'name': 'Nộp vào TK', 'width': 13},
            {'key': 'ten_ngan_hang', 'name': 'Tên ngân hàng', 'width': 13},
            {'key': 'dien_giai', 'name': 'Diễn giải/Lý do nộp', 'width': 20},
            {'key': 'ly_do_xuat', 'name': 'Lý do xuất', 'width': 22},
            {'key': 'ma_hang', 'name': 'Mã hàng (*)', 'width': 17},
            {'key': 'ten_hang', 'name': 'Tên hàng', 'width': 18},
            {'key': 'la_dong_ghi_chu', 'name': 'Là dòng ghi chú', 'width': 17},
            {'key': 'hang_khuyen_mai', 'name': 'Hàng khuyến mại', 'width': 14},
            {'key': 'chiet_khau_thuong_mai', 'name': 'Chiết khấu thương mại', 'width': 13},
            {'key': 'tk_tien_no', 'name': 'TK Tiền/Chi phí/Nợ (*)', 'width': 16},
            {'key': 'tk_doanh_thu_co', 'name': 'TK Doanh thu/Có (*)', 'width': 16},
            {'key': 'dvt', 'name': 'ĐVT', 'width': 12},
            {'key': 'so_luong', 'name': 'Số lượng', 'width': 13},
            {'key': 'don_gia', 'name': 'Đơn giá', 'width': 14},
            {'key': 'thanh_tien', 'name': 'Thành tiền', 'width': 13},
            {'key': 'ty_le_ck', 'name': 'Tỷ lệ CK (%)', 'width': 13},
            {'key': 'tien_chiet_khau', 'name': 'Tiền chiết khấu', 'width': 16},
            {'key': 'tk_chiet_khau', 'name': 'TK chiết khấu', 'width': 15},
            {'key': 'gia_tinh_thue_xk', 'name': 'Giá tính thuế XK', 'width': 17},
            {'key': 'ty_le_thue_xk', 'name': '% thuế xuất khẩu', 'width': 18},
            {'key': 'tien_thue_xk', 'name': 'Tiền thuế xuất khẩu', 'width': 21},
            {'key': 'tk_thue_xk', 'name': 'TK thuế xuất khẩu', 'width': 19},
            {'key': 'ty_le_thue_gtgt', 'name': '% thuế GTGT', 'width': 16},
            {'key': 'ty_le_thue_khac', 'name': '% thuế suất KHAC', 'width': 13},
            {'key': 'tien_thue_gtgt', 'name': 'Tiền thuế GTGT', 'width': 13},
            {'key': 'tk_thue_gtgt', 'name': 'TK thuế GTGT', 'width': 16},
            {'key': 'hh_khong_th_tren_to_khai', 'name': 'HH không TH trên tờ khai thuế GTGT', 'width': 19},
            {'key': 'ma_kho', 'name': 'Mã kho', 'width': 11},
            {'key': 'tk_gia_von', 'name': 'TK giá vốn', 'width': 12},
            {'key': 'tk_kho', 'name': 'TK Kho', 'width': 12},
            {'key': 'don_gia_von', 'name': 'Đơn giá vốn', 'width': 12},
            {'key': 'tien_von', 'name': 'Tiền vốn', 'width': 12},
            {'key': 'hang_hoa_giu_ho', 'name': 'Hàng hóa giữ hộ/bán hộ', 'width': 13},
        ]

    def action_export(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho Shopee nào trong khoảng ngày đã chọn."))

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

        filename = f"Xuat_ban_hang_Shopee_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": self._name,  # Correct model name
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
