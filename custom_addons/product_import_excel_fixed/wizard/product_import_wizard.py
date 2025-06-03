from odoo import models, fields
import base64
import tempfile
import pandas as pd
import math


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
            default_code = row.get('Mã')
            barcode = self._clean_string(row.get('Mã vạch'))

            if not name or pd.isna(name):
                continue  # Bỏ qua nếu không có tên sản phẩm

            x_origin_name = self._clean_string(row.get('Nguồn gốc'))
            x_group_name = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))

            vat = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)
            uom_name = self._clean_string(row.get('Đơn vị tính'))

            vat_float = self._safe_float(vat)
            uom = self._get_or_create_uom(uom_name)

            values = {
                "name": str(name).strip(),
                "standard_price": self._safe_float(cost_price),
                "list_price": self._safe_float(price1),
                "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
                "uom_id": uom.id,
                "uom_po_id": uom.id,
                "tracking": 'none',
                "type": 'product',
            }

            if barcode:
                values["barcode"] = barcode
            if default_code:
                values["default_code"] = default_code
            if x_origin_name:
                values["x_origin"] = self._get_or_create_m2o("product.origin", x_origin_name)
            if x_group_name:
                values["x_group"] = self._get_or_create_m2o("product.group", x_group_name)
            if x_property_name:
                values["x_property"] = self._get_or_create_m2o("product.property", x_property_name)

            # Nếu đã tồn tại thì cập nhật, không tạo mới
            existing_product = self.env["product.template"].search([("default_code", "=", default_code)], limit=1)
            if existing_product:
                existing_product.write(values)
            else:
                self.env["product.template"].create(values)

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
        if pd.isna(val) or val is None or str(val).strip().lower() == 'nan':
            return ''
        return str(val).strip()

    def _get_or_create_m2o(self, model, name):
        record = self.env[model].sudo().search([('name', '=', name)], limit=1)
        if not record:
            record = self.env[model].sudo().create({'name': name})
        return record.id

    def _get_or_create_uom(self, uom_name):
        if not uom_name:
            uom_name = 'Units'
        uom = self.env['uom.uom'].sudo().search([('name', '=', uom_name)], limit=1)
        if not uom:
            category = self.env['uom.category'].search([('name', '=', 'Unit')], limit=1)
            if not category:
                category = self.env['uom.category'].create({'name': 'Unit'})
            uom = self.env['uom.uom'].create({
                'name': uom_name,
                'category_id': category.id,
                'uom_type': 'reference',
                'rounding': 1.0,
            })
        return uom
