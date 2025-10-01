# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64
import tempfile
import pandas as pd
import math
import logging

_logger = logging.getLogger(__name__)


class ProductOrigin(models.Model):
    _name = "product.origin"
    _description = "Nguồn gốc sản phẩm"
    name = fields.Char(required=True)


class ProductGroup(models.Model):
    _name = "product.group"
    _description = "Nhóm VTHH"
    name = fields.Char(required=True)


class ProductProperty(models.Model):
    _name = "product.property"
    _description = "Tính chất sản phẩm"
    name = fields.Char(required=True)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_origin = fields.Many2one("product.origin", string="Nguồn gốc")
    x_group = fields.Many2one("product.group", string="Nhóm VTHH")
    x_property = fields.Many2one("product.property", string="Tính chất")

    _sql_constraints = [
        ('default_code_unique', 'unique(default_code)', 'ID EXTERNAL (Mã) phải là duy nhất!'),
        ('barcode_unique', 'unique(barcode)', 'Mã vạch phải là duy nhất!'),
    ]


class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard to import product from Excel"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

        # ===================== Helpers cho 3 loại giá =====================
    def _first_non_empty(self, row, candidates, default=None):
        """Trả về giá trị đầu tiên khác rỗng theo danh sách tên cột."""
        for name in candidates:
            if name in row:
                val = row.get(name)
                # dùng _clean_string để đồng nhất
                s = self._clean_string(val)
                if s != '':
                    return val
        return default

    def _extract_prices(self, row):
        """
        Đọc 3 loại giá từ các cột:
        - Chi phí            -> standard_price
        - Giá bán           -> list_price
        - Giá thương mại    -> x_studio_gi_bn_thng_mi

        Fallback về tên cột cũ nếu có (để không phá dữ liệu cũ):
        - 'Đơn giá mua gần nhất' cho chi phí
        - 'Đơn giá bán 1' cho giá bán
        """
        # Chi phí
        cost_raw = self._first_non_empty(
            row,
            ['Chi phí', 'Đơn giá mua gần nhất'],
            default=0.0
        )
        # Giá bán
        price_raw = self._first_non_empty(
            row,
            ['Giá bán', 'Đơn giá bán 1'],
            default=0.0
        )
        # Giá thương mại
        trade_raw = self._first_non_empty(
            row,
            ['Giá thương mại'],
            default=0.0
        )

        return {
            'standard_price': self._safe_float(cost_raw),
            'list_price': self._safe_float(price_raw),
            'x_studio_gi_bn_thng_mi': self._safe_float(trade_raw),
        }

    # ===================== Helpers: UoM =====================
    def _get_unit_category(self):
        """Tìm category 'Unit' (tiếng Anh mặc định). Nếu tên đã dịch, vẫn ưu tiên chuỗi chứa 'Unit'."""
        Cat = self.env['uom.category'].sudo()
        cat = Cat.search([('name', 'ilike', 'Unit')], limit=1)
        if cat:
            return cat
        # Fallback: tìm category có UoM 'Cái' để suy ra
        Uom = self.env['uom.uom'].sudo()
        cai_uom = Uom.search([('name', 'ilike', 'cái')], limit=1)
        return cai_uom.category_id if cai_uom else Cat.search([], limit=1)  # last resort

    def _find_uom_in_unit_category(self, dvt_text):
        """
        Tìm UoM theo tên (case-insensitive) trong category 'Unit'.
        Không thấy thì fallback 'Cái' (trong Unit). Cuối cùng: reference UoM của Unit.
        """
        Uom = self.env['uom.uom'].sudo()
        unit_cat = self._get_unit_category()
        if not unit_cat:
            _logger.warning("⚠ Không tìm thấy uom.category 'Unit', dùng bất kỳ UoM sẵn có.")
            # Dù sao cũng thử 'Cái' chung
            any_uom = Uom.search([('name', 'ilike', 'cái')], limit=1)
            return any_uom or Uom.search([], limit=1)

        # Chuẩn hóa chuỗi tìm
        name = self._clean_string(dvt_text).strip()
        if name:
            # Tìm EXACT (không phân biệt hoa thường) trong Unit
            # '=ilike' là so sánh bằng không phân biệt hoa thường (nếu version hỗ trợ),
            # nếu không, dùng ilike và lọc tên đúng.
            uoms = Uom.search([('category_id', '=', unit_cat.id), ('name', 'ilike', name)], limit=10)
            exact = next((u for u in uoms if (u.name or '').strip().lower() == name.lower()), False)
            if exact:
                return exact

        # Fallback: 'Cái' trong Unit
        cai = Uom.search([('category_id', '=', unit_cat.id), ('name', 'ilike', 'cái')], limit=1)
        if cai:
            return cai

        # Fallback cuối: reference UoM trong Unit (chuẩn hệ số)
        ref = Uom.search([('category_id', '=', unit_cat.id), ('uom_type', '=', 'reference')], limit=1)
        if ref:
            return ref

        # Bất đắc dĩ: bất kỳ UoM trong Unit
        any_unit = Uom.search([('category_id', '=', unit_cat.id)], limit=1)
        if any_unit:
            return any_unit

        # Cực chẳng đã: UoM bất kỳ
        return Uom.search([], limit=1)

    # ===================== Import =====================
    def action_import(self):
        if not self.file:
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(
                tmp.name,
                dtype={
                    'Mã vạch': str,
                    'ID EXTERNAL': str,
                    'Mã': str,
                    'DVT': str,  # <-- thêm đọc cột DVT
                }
            )

        Product = self.env["product.template"].sudo()

        for _, row in df.iterrows():
            name = self._clean_string(row.get('Tên'))
            if not name:
                continue

            default_code = self._clean_string(row.get('ID EXTERNAL')) or self._clean_string(row.get('Mã'))
            barcode = self._clean_string(row.get('Mã vạch'))
            x_origin_name = self._clean_string(row.get('Nguồn gốc'))
            x_group_name = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))
            vat = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)
            vat_float = self._safe_float(vat)

            # ===== Helpers lấy 3 loại giá từ Excel =====
            price_dict = self._extract_prices(row)
            cost_price = price_dict['standard_price']
            price1 = price_dict['list_price']
            trade_price = price_dict['x_studio_gi_bn_thng_mi']

            # ===== UOM từ cột DVT =====
            dvt_text = row.get('DVT')
            uom = self._find_uom_in_unit_category(dvt_text)  # đảm bảo thuộc Unit; fallback 'Cái'
            if not uom:
                _logger.warning("⚠ Không xác định được UoM; bỏ qua gán UoM cho dòng: %s", name)

            # --- build values ---
            values = {
                "name": name,
                "type": "consu",          # bạn giữ nguyên theo nhu cầu
                "tracking": "none",
                "standard_price": self._safe_float(cost_price),
                "list_price": self._safe_float(price1),
                "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
                "is_storable": True,
            }
            values["x_studio_gi_bn_thng_mi"] = self._safe_float(trade_price)

            if uom:
                # set cả uom_id & uom_po_id
                values["uom_id"] = uom.id
                values["uom_po_id"] = uom.id

            if default_code:
                values["default_code"] = default_code
            if barcode:
                values["barcode"] = barcode
            if x_origin_name:
                values["x_origin"] = self._get_or_create_m2o("product.origin", x_origin_name)
            if x_group_name:
                values["x_group"] = self._get_or_create_m2o("product.group", x_group_name)
            if x_property_name:
                values["x_property"] = self._get_or_create_m2o("product.property", x_property_name)

            # --- TÌM SẢN PHẨM TỒN TẠI ---
            product = False
            if default_code:
                product = Product.search([('default_code', '=', default_code)], limit=1)
            if not product and barcode:
                product = Product.search([('barcode', '=', barcode)], limit=1)

            # --- XỬ LÝ TẠO/UPDATE ---
            if not product:
                if barcode:
                    dup = Product.search([('barcode', '=', barcode)], limit=1)
                    if dup:
                        _logger.warning("⚠ Bỏ qua tạo mới vì barcode %s đã tồn tại ở sản phẩm %s", barcode, dup.display_name)
                        values.pop('barcode', None)
                try:
                    Product.create(values)
                except Exception as e:
                    _logger.exception("❌ Lỗi tạo sản phẩm (default_code=%s, barcode=%s): %s", default_code, barcode, e)
                continue

            # Đã có product: build write_vals incremental
            write_vals = {}

            if barcode and barcode != (product.barcode or ''):
                conflict = Product.search([('id', '!=', product.id), ('barcode', '=', barcode)], limit=1)
                if conflict:
                    _logger.warning("⚠ Không thể cập nhật barcode %s cho %s vì đã thuộc %s",
                                    barcode, product.display_name, conflict.display_name)
                else:
                    write_vals['barcode'] = barcode

            if name and name != product.name:
                write_vals['name'] = name

            if default_code and default_code != (product.default_code or ''):
                dc_conflict = Product.search([('id', '!=', product.id), ('default_code', '=', default_code)], limit=1)
                if dc_conflict:
                    _logger.warning("⚠ ID EXTERNAL %s đã thuộc %s, bỏ qua update default_code cho %s",
                                    default_code, dc_conflict.display_name, product.display_name)
                else:
                    write_vals['default_code'] = default_code

            if 'standard_price' in values:
                write_vals['standard_price'] = values['standard_price']
            if 'list_price' in values:
                write_vals['list_price'] = values['list_price']
            if values.get('taxes_id'):
                write_vals['taxes_id'] = values['taxes_id']
            if 'x_studio_gi_bn_thng_mi' in values:
                write_vals['x_studio_gi_bn_thng_mi'] = values['x_studio_gi_bn_thng_mi']
            if values.get('x_origin'):
                write_vals['x_origin'] = values['x_origin']
            if values.get('x_group'):
                write_vals['x_group'] = values['x_group']
            if values.get('x_property'):
                write_vals['x_property'] = values['x_property']

            # Cập nhật UoM nếu xác định được và khác hiện tại
            if uom and (product.uom_id.id != uom.id or product.uom_po_id.id != uom.id):
                write_vals['uom_id'] = uom.id
                write_vals['uom_po_id'] = uom.id

            if write_vals:
                try:
                    product.write(write_vals)
                except Exception as e:
                    _logger.exception("❌ Lỗi cập nhật sản phẩm %s: %s", product.display_name, e)

    # ===== Helpers khác =====
    def _get_tax_ids(self, vat_float):
        if not isinstance(vat_float, (int, float)) or math.isnan(vat_float):
            return []
        tax = self.env['account.tax'].search([
            ('amount', '=', vat_float),
            ('type_tax_use', '=', 'sale')
        ], limit=1)
        return [tax.id] if tax else []

    def _safe_float(self, value):
        try:
            f = float(value)
            return 0.0 if math.isnan(f) else f
        except Exception:
            return 0.0

    def _clean_string(self, val):
        if val is None:
            return ''
        try:
            if pd.isna(val):
                return ''
        except Exception:
            pass
        if isinstance(val, (int, float)):
            if float(val).is_integer():
                return str(int(val)).strip()
            else:
                return str(val).strip()
        s = str(val).strip()
        return '' if s.lower() == 'nan' else s

    def _get_or_create_m2o(self, model, name):
        record = self.env[model].sudo().search([('name', '=', name)], limit=1)
        if not record:
            record = self.env[model].sudo().create({'name': name})
        return record.id
