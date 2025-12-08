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

    update_existing = fields.Boolean(string="Cập nhật nếu đã tồn tại", default=False,
        help="Nếu được chọn, các combo đã tồn tại sẽ được cập nhật tên và danh sách hàng con (xoá cũ thêm mới).")

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

    def _get_or_create_uom(self, name):
        """Tìm hoặc tạo mới đơn vị tính (UoM) dựa trên tên."""
        if not name:
            name = 'Cái'
        name = name.strip().title()
        UoM = self.env['uom.uom'].sudo()
        UoMCat = self.env['uom.category'].sudo()

        uom = UoM.search([('name', '=', name)], limit=1)
        if uom:
            return uom

        cat = UoMCat.search([('name', 'ilike', 'Unit')], limit=1)
        if not cat:
            cat = UoMCat.create({'name': 'Unit'})

        ref_uom = UoM.search([
            ('category_id', '=', cat.id),
            ('uom_type', '=', 'reference')
        ], limit=1)

        uom_type = 'reference' if not ref_uom else 'smaller'

        return UoM.create({
            'name': name,
            'category_id': cat.id,
            'uom_type': uom_type,
            'factor_inv': 1.0,
            'rounding': 1.0,
        })

    def _get_or_create_product(self, code, name, unit_name=None):
        """
        Tìm hoặc tạo mới sản phẩm dựa trên mã.
        Nếu tìm thấy → trả về product.product
        Nếu không → tạo mới với thông tin cơ bản từ Excel
        """
        code = code.strip()
        name = name.strip() if name else code

        ProductProduct = self.env['product.product'].sudo()
        ProductTemplate = self.env['product.template'].sudo()

        product = ProductProduct.search([('default_code', '=', code)], limit=1)

        if product:
            # _logger.info("🔁 Sản phẩm %s đã tồn tại", code)
            return product, False  # False = không tạo mới

        # Tạo mới nếu chưa có
        uom = self._get_or_create_uom(unit_name or 'Cái')
        tmpl = ProductTemplate.create({
            'name': name,
            'default_code': code,
            'type': 'consu',
            'uom_id': uom.id,
            'uom_po_id': uom.id,
            'purchase_ok': True,
            'sale_ok': True,
            'is_storable': True,
        })
        _logger.info("🆕 Tạo sản phẩm mới: [%s] %s với UOM: %s", code, name, uom.name)
        return tmpl.product_variant_id, True  # True = đã tạo mới

    def _get_excel_engine(self, filename):
        """Xác định engine dựa trên đuôi file."""
        if filename:
            if filename.lower().endswith('.xls'):
                return 'xlrd'
            elif filename.lower().endswith('.xlsx'):
                return 'openpyxl'
        return None

    def _read_excel(self, file_content, dtype=None):
        """
        Đọc file Excel, tự động xác định engine.
        Hỗ trợ cả file HTML giả dạng .xls (như MISA xuất ra).
        """
        import os

        file_data = base64.b64decode(file_content)

        # Kiểm tra xem file có phải HTML không (MISA thường xuất HTML với đuôi .xls)
        file_start = file_data[:50].lower()
        is_html = b'<html' in file_start or b'<!doctype' in file_start or b'<ht' in file_start[:10]

        if is_html:
            # File là HTML, dùng pd.read_html
            _logger.info("Phát hiện file HTML giả dạng Excel, đọc bằng read_html")
            with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='wb') as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name

            try:
                # read_html trả về list các DataFrame (mỗi table 1 df)
                dfs = pd.read_html(tmp_path, encoding='utf-8')
                if dfs:
                    df = dfs[0]  # Lấy bảng đầu tiên
                    # Ép kiểu cho các cột nếu có
                    if dtype:
                        for col, col_type in dtype.items():
                            if col in df.columns:
                                df[col] = df[col].astype(str)
                    return df
                else:
                    raise ValueError("Không tìm thấy bảng dữ liệu trong file HTML")
            finally:
                os.unlink(tmp_path)
        else:
            # File Excel thật
            suffix = '.xlsx'
            engine = None
            if self.filename:
                if self.filename.lower().endswith('.xls'):
                    suffix = '.xls'
                    engine = 'xlrd'
                elif self.filename.lower().endswith('.xlsx'):
                    suffix = '.xlsx'
                    engine = 'openpyxl'

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name

            try:
                if engine:
                    return pd.read_excel(tmp_path, dtype=dtype, engine=engine)
                else:
                    return pd.read_excel(tmp_path, dtype=dtype)
            finally:
                os.unlink(tmp_path)

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
        - Nếu combo đã tồn tại:
            - Nếu update_existing=True: Cập nhật tên, Xoá hết child cũ, Tạo child mới.
            - Nếu update_existing=False: Bỏ qua.
        - Child products: tự động tạo nếu không tồn tại trong hệ thống
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
        ComboProduct = self.env['combo.product'].sudo()

        # Thống kê
        combo_created = 0
        combo_updated = 0
        combo_skipped = 0
        child_added = 0
        child_created = 0  # Số child products được tạo mới
        errors = []

        # Nhóm dữ liệu theo Mã Combo
        combo_groups = {}
        for _, row in df.iterrows():
            combo_code = self._clean_string(row.get('Mã Combo'))
            combo_name = self._clean_string(row.get('Tên Combo'))
            child_code = self._clean_string(row.get('Mã Hàng Con'))
            child_name = self._clean_string(row.get('Tên Hàng Con'))
            child_uom = self._clean_string(row.get('ĐVT'))
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
                'uom': child_uom,
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

            is_update = False
            if existing_combo:
                if not self.update_existing:
                    combo_skipped += 1
                    _logger.info("⏭️ Combo đã tồn tại, bỏ qua: [%s] %s", combo_code, combo_name)
                    continue
                else:
                    is_update = True
                    _logger.info("♻️ Combo đã tồn tại, tiến hành cập nhật: [%s]", combo_code)

            # Lấy hoặc tạo child products
            valid_children = []
            for child in children:
                # Sử dụng _get_or_create_product để tự động tạo nếu không có
                child_product, is_new = self._get_or_create_product(
                    code=child['code'],
                    name=child['name'],
                    unit_name=child['uom']
                )

                if is_new:
                    child_created += 1
                    # _logger.info("🆕 Tạo child product mới: [%s] %s", child['code'], child['name'])

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

            # Tạo combo product mới hoặc Cập nhật
            try:
                if is_update:
                    # Cập nhật tên nếu có thay đổi (và khác rỗng)
                    if combo_name and existing_combo.name != combo_name:
                        existing_combo.name = combo_name
                    
                    # Đảm bảo là combo
                    if not existing_combo.is_combo:
                        existing_combo.is_combo = True
                        existing_combo.type = 'service'

                    # Xoá toàn bộ child cũ
                    existing_combo.combo_product_id.unlink()
                    _logger.info("   🗑️ Đã xoá các thành phần cũ của combo [%s]", combo_code)

                    target_combo = existing_combo
                    combo_updated += 1
                else:
                    # Tạo mới hoàn toàn
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

                    target_combo = ProductTemplate.create(combo_vals)
                    combo_created += 1
                    _logger.info("✅ Tạo combo mới: [%s] %s", combo_code, combo_name)

                # Tạo combo lines (children)
                for child_data in valid_children:
                    ComboProduct.create({
                        'product_template_id': target_combo.id,
                        'product_id': child_data['product'].id,
                        'product_quantity': child_data['qty'],
                        'name': child_data['product'].name,
                    })
                    child_added += 1
                    # _logger.info("   ➕ Thêm child: [%s] x %s", child_data['product'].default_code, child_data['qty'])

            except Exception as e:
                errors.append(f"Combo [{combo_code}]: {str(e)}")
                _logger.exception("❌ Lỗi xử lý combo [%s]: %s", combo_code, e)

        # Tạo thông báo kết quả
        msg_lines = [
            "Hoàn tất xử lý Combo Products.",
            f"- Combo tạo mới: {combo_created}",
            f"- Combo cập nhật: {combo_updated}",
            f"- Combo bỏ qua: {combo_skipped}",
            f"- Child products đã thêm vào combo: {child_added}",
            f"- Child products tạo mới (hệ thống): {child_created}",
        ]

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
                'title': 'Kết quả Import Combo',
                'message': msg,
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            }
        }
