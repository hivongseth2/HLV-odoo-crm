from odoo import models, fields
import base64
import tempfile
import pandas as pd
import math

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
            df = pd.read_excel(tmp.name)

        for _, row in df.iterrows():
            name = row.get('Tên')
            if not name or pd.isna(name):
                continue  # Bỏ qua nếu không có tên

            default_code = row.get('Mã')
            barcode = row.get('Mã vạch')

            # Bỏ qua nếu không có barcode (nan, None, rỗng, chuỗi trắng)
            if not barcode or (isinstance(barcode, float) and math.isnan(barcode)) or str(barcode).strip() == '':
                continue

            x_origin_name = self._clean_string(row.get('Nguồn gốc'))
            x_group_name = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))
            uom_name = self._clean_string(row.get('Đơn vị tính'))

            vat = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)

            vat_float = self._safe_float(vat)

            # Tìm đơn vị tính, nếu chưa có thì tạo mới
            uom_id = False
            if uom_name:
                uom = self.env['uom.uom'].sudo().search([('name', '=', uom_name)], limit=1)
                if not uom:
                    uom = self.env['uom.uom'].sudo().create({'name': uom_name, 'category_id': self._get_default_uom_category()})
                uom_id = uom.id

            # Tìm sản phẩm theo default_code để update, nếu không thì tạo mới
            product = self.env['product.template'].sudo().search([('default_code', '=', default_code)], limit=1) if default_code else None

            values = {
                "name": str(name).strip(),
                "default_code": default_code,
                "barcode": barcode,
                "standard_price": self._safe_float(cost_price),
                "list_price": self._safe_float(price1),
                "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
                "track_inventory": True,  # Mặc định theo dõi tồn kho nha
            }

            if uom_id:
                values['uom_id'] = uom_id
                values['uom_po_id'] = uom_id  # Đơn vị mua cũng set cho đồng bộ

            if x_origin_name:
                values["x_origin"] = self._get_or_create_m2o("product.origin", x_origin_name)
            if x_group_name:
                values["x_group"] = self._get_or_create_m2o("product.group", x_group_name)
            if x_property_name:
                values["x_property"] = self._get_or_create_m2o("product.property", x_property_name)

            if product:
                product.write(values)  # update sản phẩm có rồi
            else:
                self.env["product.template"].sudo().create(values)

    def _get_tax_ids(self, vat_float):
        if not isinstance(vat_float, (int, float)) or math.isnan(vat_float):
            return []
        tax = self.env['account.tax'].sudo().search([
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
        if pd.isna(val) or val is None or str(val).strip().lower() == 'nan':
            return ''
        return str(val).strip()

    def _get_or_create_m2o(self, model, name):
        record = self.env[model].sudo().search([('name', '=', name)], limit=1)
        if not record:
            record = self.env[model].sudo().create({'name': name})
        return record.id

    def _get_default_uom_category(self):
        # Lấy category mặc định cho đơn vị tính, lấy category của đơn vị tính "Unit(s)" nếu có
        category = self.env['uom.category'].sudo().search([], limit=1)
        return category.id if category else False
