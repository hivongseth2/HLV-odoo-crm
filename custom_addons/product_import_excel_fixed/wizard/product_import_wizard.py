# # -*- coding: utf-8 -*-
# from odoo import models, fields, api
# import base64
# import tempfile
# import pandas as pd
# import math
# import logging

# _logger = logging.getLogger(__name__)


# class ProductOrigin(models.Model):
#     _name = "product.origin"
#     _description = "Nguồn gốc sản phẩm"
#     name = fields.Char(required=True)


# class ProductGroup(models.Model):
#     _name = "product.group"
#     _description = "Nhóm VTHH"
#     name = fields.Char(required=True)


# class ProductProperty(models.Model):
#     _name = "product.property"
#     _description = "Tính chất sản phẩm"
#     name = fields.Char(required=True)


# class ProductTemplate(models.Model):
#     _inherit = "product.template"

#     x_origin = fields.Many2one("product.origin", string="Nguồn gốc")
#     x_group = fields.Many2one("product.group", string="Nhóm VTHH")
#     x_property = fields.Many2one("product.property", string="Tính chất")

#     _sql_constraints = [
#         ('default_code_unique', 'unique(default_code)', 'ID EXTERNAL (Mã) phải là duy nhất!'),
#         ('barcode_unique', 'unique(barcode)', 'Mã vạch phải là duy nhất!'),
#     ]


# class ProductImportWizard(models.TransientModel):
#     _name = "product.import.wizard"
#     _description = "Wizard to import product from Excel"

#     file = fields.Binary(string="Excel File", required=True)
#     filename = fields.Char(string="File Name")

#         # ===================== Helpers cho 3 loại giá =====================
#     def _first_non_empty(self, row, candidates, default=None):
#         """Trả về giá trị đầu tiên khác rỗng theo danh sách tên cột."""
#         for name in candidates:
#             if name in row:
#                 val = row.get(name)
#                 # dùng _clean_string để đồng nhất
#                 s = self._clean_string(val)
#                 if s != '':
#                     return val
#         return default

#     def _extract_prices(self, row):
#         """
#         Đọc 3 loại giá từ các cột:
#         - Chi phí            -> standard_price
#         - Giá bán           -> list_price
#         - Giá thương mại    -> x_studio_gi_bn_thng_mi

#         Fallback về tên cột cũ nếu có (để không phá dữ liệu cũ):
#         - 'Đơn giá mua gần nhất' cho chi phí
#         - 'Đơn giá bán 1' cho giá bán
#         """
#         # Chi phí
#         cost_raw = self._first_non_empty(
#             row,
#             ['Chi phí', 'Đơn giá mua gần nhất'],
#             default=0.0
#         )
#         # Giá bán
#         price_raw = self._first_non_empty(
#             row,
#             ['Giá bán', 'Đơn giá bán 1'],
#             default=0.0
#         )
#         # Giá thương mại
#         trade_raw = self._first_non_empty(
#             row,
#             ['Giá thương mại'],
#             default=0.0
#         )

#         return {
#             'standard_price': self._safe_float(cost_raw),
#             'list_price': self._safe_float(price_raw),
#             'x_studio_gi_bn_thng_mi': self._safe_float(trade_raw),
#         }


#     # ===================== Helpers: UoM =====================
#     def _get_unit_category(self):
#         """Tìm category 'Unit' (tiếng Anh mặc định). Nếu tên đã dịch, vẫn ưu tiên chuỗi chứa 'Unit'."""
#         Cat = self.env['uom.category'].sudo()
#         cat = Cat.search([('name', 'ilike', 'Unit')], limit=1)
#         if cat:
#             return cat
#         # Fallback: tìm category có UoM 'Cái' để suy ra
#         Uom = self.env['uom.uom'].sudo()
#         cai_uom = Uom.search([('name', 'ilike', 'cái')], limit=1)
#         return cai_uom.category_id if cai_uom else Cat.search([], limit=1)  # last resort

#     def _find_uom_in_unit_category(self, dvt_text):
#         """
#         Tìm UoM theo tên (case-insensitive) trong category 'Unit'.
#         Không thấy thì fallback 'Cái' (trong Unit). Cuối cùng: reference UoM của Unit.
#         """
#         Uom = self.env['uom.uom'].sudo()
#         unit_cat = self._get_unit_category()
#         if not unit_cat:
#             _logger.warning("⚠ Không tìm thấy uom.category 'Unit', dùng bất kỳ UoM sẵn có.")
#             # Dù sao cũng thử 'Cái' chung
#             any_uom = Uom.search([('name', 'ilike', 'cái')], limit=1)
#             return any_uom or Uom.search([], limit=1)

#         # Chuẩn hóa chuỗi tìm
#         name = self._clean_string(dvt_text).strip()
#         if name:
#             # Tìm EXACT (không phân biệt hoa thường) trong Unit
#             # '=ilike' là so sánh bằng không phân biệt hoa thường (nếu version hỗ trợ),
#             # nếu không, dùng ilike và lọc tên đúng.
#             uoms = Uom.search([('category_id', '=', unit_cat.id), ('name', 'ilike', name)], limit=10)
#             exact = next((u for u in uoms if (u.name or '').strip().lower() == name.lower()), False)
#             if exact:
#                 return exact

#         # Fallback: 'Cái' trong Unit
#         cai = Uom.search([('category_id', '=', unit_cat.id), ('name', 'ilike', 'cái')], limit=1)
#         if cai:
#             return cai

#         # Fallback cuối: reference UoM trong Unit (chuẩn hệ số)
#         ref = Uom.search([('category_id', '=', unit_cat.id), ('uom_type', '=', 'reference')], limit=1)
#         if ref:
#             return ref

#         # Bất đắc dĩ: bất kỳ UoM trong Unit
#         any_unit = Uom.search([('category_id', '=', unit_cat.id)], limit=1)
#         if any_unit:
#             return any_unit

#         # Cực chẳng đã: UoM bất kỳ
#         return Uom.search([], limit=1)

#     # ===================== Import =====================
#     def action_import(self):
#         if not self.file:
#             return

#         with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
#             tmp.write(base64.b64decode(self.file))
#             tmp.seek(0)
#             df = pd.read_excel(
#                 tmp.name,
#                 dtype={
#                     'Mã vạch': str,
#                     'ID EXTERNAL': str,
#                     'Mã': str,
#                     'DVT': str,  # <-- thêm đọc cột DVT
#                 }
#             )

#         Product = self.env["product.template"].sudo()

#         for _, row in df.iterrows():
#             name = self._clean_string(row.get('Tên'))
#             if not name:
#                 continue

#             default_code = self._clean_string(row.get('ID EXTERNAL')) or self._clean_string(row.get('Mã'))
#             barcode = self._clean_string(row.get('Mã vạch'))
#             x_origin_name = self._clean_string(row.get('Nguồn gốc'))
#             x_group_name = self._clean_string(row.get('Nhóm VTHH'))
#             x_property_name = self._clean_string(row.get('Tính chất'))
#             vat = row.get('Thuế suất GTGT', 0)
#             cost_price = row.get('Đơn giá mua gần nhất', 0.0)
#             price1 = row.get('Đơn giá bán 1', 0.0)
#             vat_float = self._safe_float(vat)

#             # ===== Helpers lấy 3 loại giá từ Excel =====
#             price_dict = self._extract_prices(row)
#             cost_price = price_dict['standard_price']
#             price1 = price_dict['list_price']
#             trade_price = price_dict['x_studio_gi_bn_thng_mi']

#             # ===== UOM từ cột DVT =====
#             dvt_text = row.get('DVT')
#             uom = self._find_uom_in_unit_category(dvt_text)  # đảm bảo thuộc Unit; fallback 'Cái'
#             if not uom:
#                 _logger.warning("⚠ Không xác định được UoM; bỏ qua gán UoM cho dòng: %s", name)

#             # --- build values ---
#             values = {
#                 "name": name,
#                 "type": "consu",          # bạn giữ nguyên theo nhu cầu
#                 "tracking": "none",
#                 "standard_price": self._safe_float(cost_price),
#                 "list_price": self._safe_float(price1),
#                 "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
#                 "is_storable": True,
#             }
#             values["x_studio_gi_bn_thng_mi"] = self._safe_float(trade_price)
#             if uom:
#                 # set cả uom_id & uom_po_id
#                 values["uom_id"] = uom.id
#                 values["uom_po_id"] = uom.id

#             if default_code:
#                 values["default_code"] = default_code
#             if barcode:
#                 values["barcode"] = barcode
#             if x_origin_name:
#                 values["x_origin"] = self._get_or_create_m2o("product.origin", x_origin_name)
#             if x_group_name:
#                 values["x_group"] = self._get_or_create_m2o("product.group", x_group_name)
#             if x_property_name:
#                 values["x_property"] = self._get_or_create_m2o("product.property", x_property_name)

#             # --- TÌM SẢN PHẨM TỒN TẠI ---
#             product = False
#             if default_code:
#                 product = Product.search([('default_code', '=', default_code)], limit=1)
#             if not product and barcode:
#                 product = Product.search([('barcode', '=', barcode)], limit=1)

#             # --- XỬ LÝ TẠO/UPDATE ---
#             if not product:
#                 if barcode:
#                     dup = Product.search([('barcode', '=', barcode)], limit=1)
#                     if dup:
#                         _logger.warning("⚠ Bỏ qua tạo mới vì barcode %s đã tồn tại ở sản phẩm %s", barcode, dup.display_name)
#                         values.pop('barcode', None)
#                 try:
#                     Product.create(values)
#                 except Exception as e:
#                     _logger.exception("❌ Lỗi tạo sản phẩm (default_code=%s, barcode=%s): %s", default_code, barcode, e)
#                 continue

#             # Đã có product: build write_vals incremental
#             write_vals = {}

#             if barcode and barcode != (product.barcode or ''):
#                 conflict = Product.search([('id', '!=', product.id), ('barcode', '=', barcode)], limit=1)
#                 if conflict:
#                     _logger.warning("⚠ Không thể cập nhật barcode %s cho %s vì đã thuộc %s",
#                                     barcode, product.display_name, conflict.display_name)
#                 else:
#                     write_vals['barcode'] = barcode

#             if name and name != product.name:
#                 write_vals['name'] = name

#             if default_code and default_code != (product.default_code or ''):
#                 dc_conflict = Product.search([('id', '!=', product.id), ('default_code', '=', default_code)], limit=1)
#                 if dc_conflict:
#                     _logger.warning("⚠ ID EXTERNAL %s đã thuộc %s, bỏ qua update default_code cho %s",
#                                     default_code, dc_conflict.display_name, product.display_name)
#                 else:
#                     write_vals['default_code'] = default_code

#             if 'standard_price' in values:
#                 write_vals['standard_price'] = values['standard_price']
#             if 'list_price' in values:
#                 write_vals['list_price'] = values['list_price']
#             if 'x_studio_gi_bn_thng_mi' in values:
#                 write_vals['x_studio_gi_bn_thng_mi'] = values['x_studio_gi_bn_thng_mi']
#             if values.get('taxes_id'):
#                 write_vals['taxes_id'] = values['taxes_id']

#             if values.get('x_origin'):
#                 write_vals['x_origin'] = values['x_origin']
#             if values.get('x_group'):
#                 write_vals['x_group'] = values['x_group']
#             if values.get('x_property'):
#                 write_vals['x_property'] = values['x_property']

#             # Cập nhật UoM nếu xác định được và khác hiện tại
#             if uom and (product.uom_id.id != uom.id or product.uom_po_id.id != uom.id):
#                 write_vals['uom_id'] = uom.id
#                 write_vals['uom_po_id'] = uom.id

#             if write_vals:
#                 try:
#                     product.write(write_vals)
#                 except Exception as e:
#                     _logger.exception("❌ Lỗi cập nhật sản phẩm %s: %s", product.display_name, e)

#     # ===== Helpers khác =====
#     def _get_tax_ids(self, vat_float):
#         if not isinstance(vat_float, (int, float)) or math.isnan(vat_float):
#             return []
#         tax = self.env['account.tax'].search([
#             ('amount', '=', vat_float),
#             ('type_tax_use', '=', 'sale')
#         ], limit=1)
#         return [tax.id] if tax else []

#     def _safe_float(self, value):
#         try:
#             f = float(value)
#             return 0.0 if math.isnan(f) else f
#         except Exception:
#             return 0.0

#     def _clean_string(self, val):
#         if val is None:
#             return ''
#         try:
#             if pd.isna(val):
#                 return ''
#         except Exception:
#             pass
#         if isinstance(val, (int, float)):
#             if float(val).is_integer():
#                 return str(int(val)).strip()
#             else:
#                 return str(val).strip()
#         s = str(val).strip()
#         return '' if s.lower() == 'nan' else s

#     def _get_or_create_m2o(self, model, name):
#         record = self.env[model].sudo().search([('name', '=', name)], limit=1)
#         if not record:
#             record = self.env[model].sudo().create({'name': name})
#         return record.id



# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64
import tempfile
import pandas as pd
import logging

_logger = logging.getLogger(__name__)


class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard Import sản phẩm từ Excel"

    file = fields.Binary(string="Tệp Excel", required=True)
    filename = fields.Char(string="Tên tệp")
    import_type = fields.Selection([
        ('product', 'Import sản phẩm'),
        ('combo', 'Import sản phẩm Combo'),
    ], string="Loại Import", default='product', required=True)

    update_existing = fields.Boolean(
        string="Cập nhật sản phẩm đã tồn tại", 
        default=False,
        help="Nếu được chọn, các sản phẩm đã tồn tại sẽ được cập nhật thông tin (tên, đơn vị tính)."
    )
    
    batch_size = fields.Integer(
        string="Số lượng mỗi Batch",
        default=500,
        help="Số lượng sản phẩm xử lý trong mỗi batch. Với file lớn (>1000 dòng), "
             "nên để 300-500 để tránh quá tải hệ thống. Mặc định: 500."
    )
    
    max_batches = fields.Integer(
        string="Giới hạn số Batch",
        default=0,
        help="Giới hạn số batch chạy (dùng để test). Để 0 = không giới hạn, chạy hết file."
    )

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
        _logger.info("🆕 Tạo sản phẩm mới: [%s] %s với ĐVT: %s", code, name, uom.name)
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

        if self.import_type == 'product':
            return self._import_product()
        elif self.import_type == 'combo':
            return self._import_combo()

    # -------- Import Sản phẩm --------
    def _import_product(self):
        """
        Import sản phẩm từ Excel với xử lý theo batch.
        
        BATCH PROCESSING:
        - Dữ liệu được chia thành các batch nhỏ (mặc định 500 sản phẩm/batch)
        - Sau mỗi batch, database sẽ commit để lưu dữ liệu
        - Nếu lỗi xảy ra giữa chừng, các batch đã hoàn thành vẫn được giữ lại
        - Log tiến độ sau mỗi batch để theo dõi
        
        - Nếu sản phẩm đã tồn tại (theo Mã/default_code):
            - update_existing = False → bỏ qua
            - update_existing = True → cập nhật tên và đơn vị tính
        - Nếu chưa có → tạo mới với sale_ok, purchase_ok, is_storable = True
        
        Cấu trúc Excel:
        - Cột 'Mã hàng': default_code (mã tham chiếu nội bộ) - BẮT BUỘC
        - Cột 'Tên hàng': Tên sản phẩm
        - Cột 'ĐVT': Đơn vị tính (mặc định 'Cái' nếu không có)
        """
        df = self._read_excel(self.file, dtype={'Mã hàng': str, 'Tên hàng': str, 'ĐVT': str})

        ProductTemplate = self.env['product.template'].sudo()

        # Thống kê
        created = 0
        updated = 0
        skipped_exists = 0
        skipped_no_code = 0
        skipped_same = 0
        errors = []

        # Batch processing
        batch_size = self.batch_size or 500
        total_rows = len(df)
        total_batches = (total_rows + batch_size - 1) // batch_size  # Ceiling division
        
        # Giới hạn số batch nếu được set (dùng để test)
        max_batches = self.max_batches or 0
        if max_batches > 0 and max_batches < total_batches:
            batches_to_run = max_batches
            _logger.info("⚠️ GIỚI HẠN: Chỉ chạy %d/%d batch (test mode)", max_batches, total_batches)
        else:
            batches_to_run = total_batches
        
        _logger.info("="*60)
        _logger.info("🚀 BẮT ĐẦU IMPORT SẢN PHẨM")
        _logger.info("   Tổng số dòng: %d | Batch size: %d | Số batch sẽ chạy: %d/%d", 
                     total_rows, batch_size, batches_to_run, total_batches)
        _logger.info("="*60)

        # Xử lý từng batch
        for batch_num in range(batches_to_run):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, total_rows)
            batch_df = df.iloc[start_idx:end_idx]
            
            batch_created = 0
            batch_updated = 0
            batch_errors = 0
            
            _logger.info("📦 Đang xử lý Batch %d/%d (dòng %d-%d)...", 
                         batch_num + 1, total_batches, start_idx + 1, end_idx)

            for _, row in batch_df.iterrows():
                code = self._clean_string(row.get('Mã hàng'))
                name = self._clean_string(row.get('Tên hàng'))
                uom_name = self._clean_string(row.get('ĐVT'))

                if not code:
                    skipped_no_code += 1
                    continue

                try:
                    # Tìm sản phẩm theo mã
                    existing_product = ProductTemplate.search([('default_code', '=', code)], limit=1)

                    if existing_product:
                        if not self.update_existing:
                            # Không cập nhật → bỏ qua
                            skipped_exists += 1
                            continue
                        else:
                            # Cập nhật sản phẩm đã tồn tại
                            write_vals = {}
                            
                            # Cập nhật tên nếu có và khác
                            if name and name != (existing_product.name or '').strip():
                                write_vals['name'] = name
                            
                            # Cập nhật đơn vị tính nếu có và khác
                            if uom_name:
                                new_uom = self._get_or_create_uom(uom_name)
                                if new_uom.id != existing_product.uom_id.id:
                                    write_vals['uom_id'] = new_uom.id
                                    write_vals['uom_po_id'] = new_uom.id
                            
                            if write_vals:
                                existing_product.write(write_vals)
                                updated += 1
                                batch_updated += 1
                            else:
                                skipped_same += 1
                    else:
                        # Tạo mới sản phẩm
                        uom = self._get_or_create_uom(uom_name or 'Cái')
                        ProductTemplate.create({
                            'name': name or code,
                            'default_code': code,
                            'type': 'consu',
                            'uom_id': uom.id,
                            'uom_po_id': uom.id,
                            'purchase_ok': True,
                            'sale_ok': True,
                            'is_storable': True,
                        })
                        created += 1
                        batch_created += 1

                except Exception as e:
                    errors.append(f"[{code}]: {str(e)}")
                    batch_errors += 1
                    _logger.exception("❌ Lỗi xử lý sản phẩm [%s]: %s", code, e)

            # ⭐ COMMIT DATABASE SAU MỖI BATCH
            # Điều này đảm bảo dữ liệu được lưu ngay cả khi có lỗi ở batch sau
            try:
                self.env.cr.commit()
                _logger.info("✅ Batch %d/%d hoàn thành: Tạo mới=%d, Cập nhật=%d, Lỗi=%d",
                             batch_num + 1, total_batches, batch_created, batch_updated, batch_errors)
            except Exception as e:
                _logger.error("❌ Lỗi commit batch %d: %s", batch_num + 1, e)
                # Rollback và tiếp tục batch tiếp theo
                self.env.cr.rollback()

        # Tạo thông báo kết quả
        _logger.info("="*60)
        _logger.info("🏁 HOÀN TẤT IMPORT SẢN PHẨM")
        _logger.info("="*60)
        
        msg_lines = [
            f"Hoàn tất Import sản phẩm ({batches_to_run}/{total_batches} batch).",
            f"- Tạo mới: {created}",
            f"- Cập nhật: {updated}",
            f"- Bỏ qua (đã tồn tại): {skipped_exists}",
            f"- Bỏ qua (không thay đổi): {skipped_same}",
            f"- Bỏ qua (không có 'Mã hàng'): {skipped_no_code}",
        ]
        
        # Thêm thông báo nếu còn batch chưa chạy
        if batches_to_run < total_batches:
            remaining_rows = total_rows - (batches_to_run * batch_size)
            msg_lines.append(f"⚠️ Còn lại: {remaining_rows} dòng chưa import")

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
                'title': 'Kết quả Import sản phẩm',
                'message': msg,
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            }
        }

    # -------- Import sản phẩm Combo --------
    def _import_combo(self):
        """
        Import sản phẩm combo từ file Excel.

        Cấu trúc Excel (có merged cells):
        - Cột 'Mã Combo': default_code của combo - CÓ THỂ MERGED nhiều dòng
        - Cột 'Tên Combo': Tên combo - CÓ THỂ MERGED nhiều dòng
        - Cột 'Mã Hàng Con': default_code của sản phẩm con
        - Cột 'Tên Hàng Con': Tên sản phẩm con
        - Cột 'ĐVT': Đơn vị tính
        - Cột 'Số Lượng': Số lượng sản phẩm con trong combo

        Logic:
        - Nếu combo chưa tồn tại (theo Mã Combo): tạo mới với is_combo=True
        - Nếu combo đã tồn tại:
            - Nếu update_existing=True: Cập nhật tên, xoá hết thành phần cũ, thêm thành phần mới
            - Nếu update_existing=False: Bỏ qua
        - Sản phẩm con: tự động tạo nếu không tồn tại trong hệ thống
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
        child_created = 0  # Số sản phẩm con được tạo mới
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

            # Lấy hoặc tạo sản phẩm con
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

                # Kiểm tra sản phẩm con không phải là combo
                if child_product.is_combo:
                    _logger.warning("⚠️ Sản phẩm con [%s] là combo, bỏ qua", child['code'])
                    continue

                valid_children.append({
                    'product': child_product,
                    'qty': child['qty'],
                })

            if not valid_children:
                errors.append(f"Combo [{combo_code}]: Không có sản phẩm con hợp lệ")
                _logger.error("❌ Combo [%s] không có sản phẩm con hợp lệ", combo_code)
                continue

            # Tạo combo mới hoặc Cập nhật
            try:
                if is_update:
                    # Cập nhật tên nếu có thay đổi (và khác rỗng)
                    if combo_name and existing_combo.name != combo_name:
                        existing_combo.name = combo_name
                    
                    # Đảm bảo là combo
                    if not existing_combo.is_combo:
                        existing_combo.is_combo = True
                        existing_combo.type = 'service'

                    # Xoá toàn bộ thành phần cũ
                    existing_combo.combo_product_id.unlink()
                    _logger.info("   🗑️ Đã xoá các thành phần cũ của combo [%s]", combo_code)

                    target_combo = existing_combo
                    combo_updated += 1
                else:
                    # Tạo mới hoàn toàn
                    # Lấy ĐVT mặc định (Cái)
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

                # Tạo các thành phần combo
                for child_data in valid_children:
                    ComboProduct.create({
                        'product_template_id': target_combo.id,
                        'product_id': child_data['product'].id,
                        'product_quantity': child_data['qty'],
                        'name': child_data['product'].name,
                    })
                    child_added += 1

            except Exception as e:
                errors.append(f"Combo [{combo_code}]: {str(e)}")
                _logger.exception("❌ Lỗi xử lý combo [%s]: %s", combo_code, e)

        # Tạo thông báo kết quả
        msg_lines = [
            "Hoàn tất Import sản phẩm Combo.",
            f"- Combo tạo mới: {combo_created}",
            f"- Combo cập nhật: {combo_updated}",
            f"- Combo bỏ qua: {combo_skipped}",
            f"- Thành phần đã thêm vào combo: {child_added}",
            f"- Sản phẩm con tạo mới: {child_created}",
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
                'title': 'Kết quả Import sản phẩm Combo',
                'message': msg,
                'type': 'success' if not errors else 'warning',
                'sticky': True,
            }
        }
