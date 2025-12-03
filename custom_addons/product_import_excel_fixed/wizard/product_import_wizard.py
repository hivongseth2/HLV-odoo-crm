# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64
import tempfile
import pandas as pd
import logging

_logger = logging.getLogger(__name__)


class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard to import product from Excel"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")
    import_type = fields.Selection([
        ('product_name', 'Cập nhật tên sản phẩm'),
        ('combo', 'Import Combo Products'),
    ], string="Loại Import", default='product_name', required=True)

    # -------- Helpers --------
    def _clean_string(self, val):
        """Chuẩn hóa giá trị thành string, xử lý NaN, None, số."""
        if val is None:
            return ''
        try:
            if pd.isna(val):
                return ''
        except Exception:
            pass
        if isinstance(val, (int, float)):
            return str(int(val)) if float(val).is_integer() else str(val).strip()
        s = str(val).strip()
        return '' if s.lower() == 'nan' else s

    def _safe_float(self, value, default=1.0):
        """Chuyển đổi sang float an toàn."""
        try:
            f = float(value)
            if pd.isna(f):
                return default
            return f if f > 0 else default
        except Exception:
            return default

    def _get_excel_engine(self, filename):
        """Xác định engine dựa trên đuôi file."""
        if filename:
            if filename.lower().endswith('.xls'):
                return 'xlrd'
            elif filename.lower().endswith('.xlsx'):
                return 'openpyxl'
        return None

    def _read_excel(self, file_content, dtype=None):
        """Đọc file Excel, tự động xác định engine dựa trên đuôi file."""
        # Xác định suffix và engine từ filename
        suffix = '.xlsx'
        engine = None
        if self.filename:
            if self.filename.lower().endswith('.xls'):
                suffix = '.xls'
                engine = 'xlrd'
            elif self.filename.lower().endswith('.xlsx'):
                suffix = '.xlsx'
                engine = 'openpyxl'

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(base64.b64decode(file_content))
            tmp.seek(0)
            if engine:
                return pd.read_excel(tmp.name, dtype=dtype, engine=engine)
            else:
                return pd.read_excel(tmp.name, dtype=dtype)

    # -------- Main Action --------
    def action_import(self):
        if not self.file:
            return

        if self.import_type == 'product_name':
            return self._import_product_name()
        elif self.import_type == 'combo':
            return self._import_combo()

    # -------- Import Product Name (logic cũ) --------
    def _import_product_name(self):
        """Import cập nhật tên sản phẩm theo Mã."""
        df = self._read_excel(self.file, dtype={'Mã': str, 'Tên': str})

        Product = self.env['product.template'].sudo()

        updated = 0
        skipped_no_code = 0
        skipped_not_found = 0
        skipped_no_name = 0
        same_name = 0

        for _, row in df.iterrows():
            code = self._clean_string(row.get('Mã'))
            new_name = self._clean_string(row.get('Tên'))

            if not code:
                skipped_no_code += 1
                continue
            if not new_name:
                skipped_no_name += 1
                continue

            prod = Product.search([('default_code', '=', code)], limit=1)
            if not prod:
                skipped_not_found += 1
                _logger.info("⏭️ Bỏ qua: không tìm thấy sản phẩm có default_code='%s'", code)
                continue

            if (prod.name or '').strip() != new_name.strip():
                try:
                    prod.write({'name': new_name})
                    updated += 1
                    _logger.info("✅ Cập nhật tên: [%s] '%s' -> '%s'", code, prod.name, new_name)
                except Exception as e:
                    _logger.exception("❌ Lỗi cập nhật tên cho [%s]: %s", code, e)
            else:
                same_name += 1

        msg = (
            "Hoàn tất cập nhật tên sản phẩm theo Mã.\n"
            f"- Đã cập nhật: {updated}\n"
            f"- Bỏ qua (trùng tên): {same_name}\n"
            f"- Bỏ qua (không có 'Mã'): {skipped_no_code}\n"
            f"- Bỏ qua (không có 'Tên'): {skipped_no_name}\n"
            f"- Bỏ qua (không tìm thấy theo 'Mã'): {skipped_not_found}\n"
        )
        _logger.info(msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Sản phẩm',
                'message': msg,
                'type': 'success',
                'sticky': True,
            }
        }

    # -------- Import Combo Products --------
    def _import_combo(self):
        """
        Import combo products từ file Excel.

        Cấu trúc Excel (có merged cells):
        - Cột B (Mã Combo): default_code của combo - CÓ THỂ MERGED nhiều dòng
        - Cột C (Tên Combo): Tên combo - CÓ THỂ MERGED nhiều dòng
        - Cột D (Mã Hàng Con): default_code của child product
        - Cột E (Tên Hàng Con): Tên child product
        - Cột F (ĐVT): Đơn vị tính
        - Cột G (Số Lượng): Số lượng child trong combo

        Logic:
        - Nếu combo chưa tồn tại (theo Mã Combo): tạo mới với is_combo=True
        - Nếu combo đã tồn tại: bỏ qua
        - Child products phải tồn tại trong hệ thống
        """
        df = self._read_excel(self.file, dtype={
            'Mã Combo': str,
            'Tên Combo': str,
            'Mã Hàng Con': str,
            'Tên Hàng Con': str,
            'ĐVT': str,
        })

        # Xử lý merged cells: fill forward các giá trị NaN từ ô merged
        # Khi pandas đọc merged cells, chỉ ô đầu tiên có giá trị, còn lại là NaN
        if 'Mã Combo' in df.columns:
            df['Mã Combo'] = df['Mã Combo'].fillna(method='ffill')
        if 'Tên Combo' in df.columns:
            df['Tên Combo'] = df['Tên Combo'].fillna(method='ffill')

        ProductTemplate = self.env['product.template'].sudo()
        ProductProduct = self.env['product.product'].sudo()
        ComboProduct = self.env['combo.product'].sudo()

        # Thống kê
        combo_created = 0
        combo_skipped = 0
        child_added = 0
        child_not_found = []
        errors = []

        # Nhóm dữ liệu theo Mã Combo
        combo_groups = {}
        for _, row in df.iterrows():
            combo_code = self._clean_string(row.get('Mã Combo'))
            combo_name = self._clean_string(row.get('Tên Combo'))
            child_code = self._clean_string(row.get('Mã Hàng Con'))
            child_name = self._clean_string(row.get('Tên Hàng Con'))
            qty = self._safe_float(row.get('Số Lượng'), default=1.0)

            # Bỏ qua dòng không có mã combo hoặc mã hàng con
            if not combo_code or not child_code:
                continue

            if combo_code not in combo_groups:
                combo_groups[combo_code] = {
                    'name': combo_name,
                    'children': []
                }

            combo_groups[combo_code]['children'].append({
                'code': child_code,
                'name': child_name,
                'qty': qty,
            })

        # Xử lý từng combo
        for combo_code, combo_data in combo_groups.items():
            combo_name = combo_data['name']
            children = combo_data['children']

            # Kiểm tra combo đã tồn tại chưa
            existing_combo = ProductTemplate.search([
                ('default_code', '=', combo_code)
            ], limit=1)

            if existing_combo:
                combo_skipped += 1
                _logger.info("⏭️ Combo đã tồn tại, bỏ qua: [%s] %s", combo_code, combo_name)
                continue

            # Kiểm tra tất cả child products có tồn tại không
            valid_children = []
            for child in children:
                child_product = ProductProduct.search([
                    ('default_code', '=', child['code'])
                ], limit=1)

                if not child_product:
                    child_not_found.append(f"{child['code']} ({child['name']})")
                    _logger.warning("⚠️ Không tìm thấy child product: [%s] %s",
                                    child['code'], child['name'])
                else:
                    # Kiểm tra child không phải là combo
                    if child_product.is_combo:
                        _logger.warning("⚠️ Child product [%s] là combo, bỏ qua", child['code'])
                        continue
                    valid_children.append({
                        'product': child_product,
                        'qty': child['qty'],
                    })

            if not valid_children:
                errors.append(f"Combo [{combo_code}]: Không có child product hợp lệ")
                _logger.error("❌ Combo [%s] không có child product hợp lệ", combo_code)
                continue

            # Tạo combo product mới
            try:
                # Lấy UoM mặc định (Cái)
                default_uom = self.env['uom.uom'].sudo().search([
                    ('name', 'ilike', 'Cái')
                ], limit=1)
                if not default_uom:
                    default_uom = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)

                combo_vals = {
                    'name': combo_name or combo_code,
                    'default_code': combo_code,
                    'is_combo': True,
                    'type': 'service',
                }
                if default_uom:
                    combo_vals['uom_id'] = default_uom.id
                    combo_vals['uom_po_id'] = default_uom.id

                new_combo = ProductTemplate.create(combo_vals)
                combo_created += 1
                _logger.info("✅ Tạo combo mới: [%s] %s", combo_code, combo_name)

                # Tạo combo lines (children)
                for child_data in valid_children:
                    ComboProduct.create({
                        'product_template_id': new_combo.id,
                        'product_id': child_data['product'].id,
                        'product_quantity': child_data['qty'],
                        'name': child_data['product'].name,
                    })
                    child_added += 1
                    _logger.info("   ➕ Thêm child: [%s] x %s",
                                 child_data['product'].default_code, child_data['qty'])

            except Exception as e:
                errors.append(f"Combo [{combo_code}]: {str(e)}")
                _logger.exception("❌ Lỗi tạo combo [%s]: %s", combo_code, e)

        # Tạo thông báo kết quả
        msg_lines = [
            "Hoàn tất import Combo Products.",
            f"- Combo tạo mới: {combo_created}",
            f"- Combo bỏ qua (đã tồn tại): {combo_skipped}",
            f"- Child products đã thêm: {child_added}",
        ]

        if child_not_found:
            unique_not_found = list(set(child_not_found))[:10]
            msg_lines.append(f"- Child không tìm thấy: {len(set(child_not_found))}")
            for item in unique_not_found:
                msg_lines.append(f"  • {item}")
            if len(set(child_not_found)) > 10:
                msg_lines.append(f"  ... và {len(set(child_not_found)) - 10} items khác")

        if errors:
            msg_lines.append(f"- Lỗi: {len(errors)}")
            for err in errors[:5]:
                msg_lines.append(f"  • {err}")

        msg = "\n".join(msg_lines)
        _logger.info(msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Combo Products',
                'message': msg,
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            }
        }
