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

    # Đảm bảo duy nhất cho ID EXTERNAL (default_code) và barcode
    _sql_constraints = [
        ('default_code_unique', 'unique(default_code)', 'ID EXTERNAL (Mã) phải là duy nhất!'),
        ('barcode_unique', 'unique(barcode)', 'Mã vạch phải là duy nhất!'),
    ]

class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard to import product from Excel"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

    def action_import(self):
        if not self.file:
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(tmp.name, dtype={
                    'Mã vạch': str,
                    'ID EXTERNAL': str,
                    'Mã': str
                })


        Product = self.env["product.template"].sudo()

        for _, row in df.iterrows():
            name = self._clean_string(row.get('Tên'))
            if not name:
                continue

            # Ưu tiên lấy ID EXTERNAL từ cột "ID EXTERNAL", nếu không có thì dùng "Mã"
            default_code = self._clean_string(row.get('ID EXTERNAL')) or self._clean_string(row.get('Mã'))
            barcode = self._clean_string(row.get('Mã vạch'))

            x_origin_name   = self._clean_string(row.get('Nguồn gốc'))
            x_group_name    = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))

            vat        = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1     = row.get('Đơn giá bán 1', 0.0)

            vat_float = self._safe_float(vat)

            # --- build values (chỉ set khi có dữ liệu để tránh ghi đè rỗng) ---
            values = {
                "name": name,
                "type": "consu",
                "tracking": "none",
                "is_storable": True,
                "standard_price": self._safe_float(cost_price),
                "list_price": self._safe_float(price1),
                "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
            }
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
            # 1) Có ID EXTERNAL -> ưu tiên tìm theo default_code
            if default_code:
                product = Product.search([('default_code', '=', default_code)], limit=1)

            # 2) Không có ID EXTERNAL, nhưng có barcode -> tìm theo barcode
            if not product and barcode:
                product = Product.search([('barcode', '=', barcode)], limit=1)

            # --- XỬ LÝ TẠO/UPDATE ---
            if not product:
                # Tạo mới (nếu có barcode thì phải chắc chắn chưa ai dùng)
                if barcode:
                    dup = Product.search([('barcode', '=', barcode)], limit=1)
                    if dup:
                        _logger.warning("⚠ Bỏ qua tạo mới vì barcode %s đã tồn tại ở sản phẩm %s", barcode, dup.display_name)
                        # vẫn có thể tạo mới nếu bỏ barcode
                        values.pop('barcode', None)
                try:
                    Product.create(values)
                except Exception as e:
                    _logger.exception("❌ Lỗi tạo sản phẩm (default_code=%s, barcode=%s): %s", default_code, barcode, e)
                continue

            # Đã có product:
            write_vals = {}

            # nếu có barcode mới khác hiện tại -> update (sau khi check không trùng ai khác)
            if barcode and barcode != (product.barcode or ''):
                conflict = Product.search([('id', '!=', product.id), ('barcode', '=', barcode)], limit=1)
                if conflict:
                    _logger.warning("⚠ Không thể cập nhật barcode %s cho %s vì đã thuộc %s",
                                    barcode, product.display_name, conflict.display_name)
                else:
                    write_vals['barcode'] = barcode

            # Update các field khác nếu có giá trị
            if name and name != product.name:
                write_vals['name'] = name
            if default_code and default_code != (product.default_code or ''):
                # đảm bảo không trùng
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
            if values.get('x_origin'):
                write_vals['x_origin'] = values['x_origin']
            if values.get('x_group'):
                write_vals['x_group'] = values['x_group']
            if values.get('x_property'):
                write_vals['x_property'] = values['x_property']

            if write_vals:
                try:
                    product.write(write_vals)
                except Exception as e:
                    _logger.exception("❌ Lỗi cập nhật sản phẩm %s: %s", product.display_name, e)

    # ===== Helpers =====
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
        
        # Nếu là số (int/float) thì convert thành chuỗi không có .0
        if isinstance(val, (int, float)):
            # Bỏ phần thập phân nếu không có giá trị
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
