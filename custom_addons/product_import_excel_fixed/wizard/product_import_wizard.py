# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import base64
import tempfile
import pandas as pd
import math
import logging

_logger = logging.getLogger(__name__)


# =========================
#  Master data phụ trợ
# =========================
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


# =========================
#  Kế thừa product.template
# =========================
class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_origin = fields.Many2one("product.origin", string="Nguồn gốc")
    x_group = fields.Many2one("product.group", string="Nhóm VTHHH")
    x_property = fields.Many2one("product.property", string="Tính chất")

    # Đảm bảo duy nhất cho ID EXTERNAL (default_code) và barcode
    _sql_constraints = [
        ('default_code_unique', 'unique(default_code)', 'ID EXTERNAL (Mã) phải là duy nhất!'),
        ('barcode_unique', 'unique(barcode)', 'Mã vạch phải là duy nhất!'),
    ]


# =========================
#  Wizard import Excel
# =========================
class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard to import product from Excel"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

    # ===== Main =====
    def action_import(self):
        if not self.file:
            return

        # Đọc file Excel
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(tmp.name, dtype={
                'Mã vạch': str,
                'ID EXTERNAL': str,
                'Mã': str
            })

        Product = self.env["product.template"].sudo()
        default_uom = self._get_default_uom_unit()  # Lấy sẵn UoM "Cái"

        created = 0
        updated = 0
        skipped = 0

        for _, row in df.iterrows():
            name = self._clean_string(row.get('Tên'))
            if not name:
                skipped += 1
                continue

            # Ưu tiên ID EXTERNAL từ cột "ID EXTERNAL", nếu rỗng thì dùng "Mã"
            default_code = self._clean_string(row.get('ID EXTERNAL')) or self._clean_string(row.get('Mã'))
            barcode = self._clean_string(row.get('Mã vạch'))

            x_origin_name = self._clean_string(row.get('Nguồn gốc'))
            x_group_name = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))

            vat = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)
            vat_float = self._safe_float(vat)

            # Build values chung
            values = {
                "name": name,
                "type": "consu",         # Giữ theo yêu cầu trước đó
                "tracking": "none",
                "is_storable": True,     # Nếu muốn hàng tồn kho thực sự thì nên để "product"
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

            # ===== Tìm sản phẩm đã tồn tại =====
            product = False
            # 1) Có ID EXTERNAL -> ưu tiên tìm theo default_code
            if default_code:
                product = Product.search([('default_code', '=', default_code)], limit=1)
            # 2) Không có default_code, nhưng có barcode -> tìm theo barcode
            if not product and barcode:
                product = Product.search([('barcode', '=', barcode)], limit=1)

            # ===== Xử lý tạo mới / cập nhật =====
            if not product:
                # Tạo mới -> set UoM mặc định (Cái) ở đây
                if default_uom:
                    values["uom_id"] = default_uom.id
                    values["uom_po_id"] = default_uom.id
                else:
                    _logger.warning("⚠ Không tìm thấy UoM 'Cái' (Unit). Sẽ để Odoo default UoM.")

                # Nếu barcode bị trùng ở sản phẩm khác, bỏ barcode để vẫn tạo được
                if barcode:
                    dup = Product.search([('barcode', '=', barcode)], limit=1)
                    if dup:
                        _logger.warning("⚠ Bỏ barcode khi tạo mới vì %s đã dùng barcode %s", dup.display_name, barcode)
                        values.pop('barcode', None)

                try:
                    Product.create(values)
                    created += 1
                except Exception as e:
                    _logger.exception("❌ Lỗi tạo sản phẩm (default_code=%s, barcode=%s): %s", default_code, barcode, e)
                    skipped += 1
                continue

            # ----- Đã có product -> cập nhật -----
            write_vals = {}

            # Barcode: chỉ cập nhật nếu khác & không bị trùng ở sản phẩm khác
            if barcode and barcode != (product.barcode or ''):
                conflict = Product.search([('id', '!=', product.id), ('barcode', '=', barcode)], limit=1)
                if conflict:
                    _logger.warning("⚠ Không thể cập nhật barcode %s cho %s vì đã thuộc %s",
                                    barcode, product.display_name, conflict.display_name)
                else:
                    write_vals['barcode'] = barcode

            # Name
            if name and name != product.name:
                write_vals['name'] = name

            # default_code: đảm bảo không trùng
            if default_code and default_code != (product.default_code or ''):
                dc_conflict = Product.search([('id', '!=', product.id), ('default_code', '=', default_code)], limit=1)
                if dc_conflict:
                    _logger.warning("⚠ ID EXTERNAL %s đã thuộc %s, bỏ qua update default_code cho %s",
                                    default_code, dc_conflict.display_name, product.display_name)
                else:
                    write_vals['default_code'] = default_code

            # Giá / thuế
            if 'standard_price' in values:
                write_vals['standard_price'] = values['standard_price']
            if 'list_price' in values:
                write_vals['list_price'] = values['list_price']
            if values.get('taxes_id'):
                write_vals['taxes_id'] = values['taxes_id']

            # Thuộc tính phụ
            if values.get('x_origin'):
                write_vals['x_origin'] = values['x_origin']
            if values.get('x_group'):
                write_vals['x_group'] = values['x_group']
            if values.get('x_property'):
                write_vals['x_property'] = values['x_property']

            # KHÔNG ghi đè uom khi update (giữ nguyên)
            # Nếu muốn chỉ set khi product đang rỗng uom (trường hợp cực hiếm),
            # có thể mở logic sau (comment):
            # if not product.uom_id and default_uom:
            #     write_vals['uom_id'] = default_uom.id
            #     write_vals['uom_po_id'] = default_uom.id

            if write_vals:
                try:
                    product.write(write_vals)
                    updated += 1
                except Exception as e:
                    _logger.exception("❌ Lỗi cập nhật sản phẩm %s: %s", product.display_name, e)
                    skipped += 1
            else:
                # Không có gì để cập nhật
                skipped += 1

        _logger.info("✅ Import hoàn tất: tạo mới=%s, cập nhật=%s, bỏ qua=%s", created, updated, skipped)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Import sản phẩm",
                "message": f"Hoàn tất. Tạo mới: {created}, Cập nhật: {updated}, Bỏ qua: {skipped}",
                "sticky": False,
                "type": "success",
            },
        }

    # ===== Helpers =====
    def _get_tax_ids(self, vat_float):
        """Tìm thuế bán theo % amount = vat_float (ví dụ 8, 10...). Không có thì bỏ trống."""
        try:
            if not isinstance(vat_float, (int, float)) or math.isnan(vat_float):
                return []
        except Exception:
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
        """Chuẩn hoá text: None/NaN -> '', số -> chuỗi, trim, loại 'nan'."""
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
            return str(val).strip()
        s = str(val).strip()
        return '' if s.lower() == 'nan' else s

    def _get_or_create_m2o(self, model, name):
        rec = self.env[model].sudo().search([('name', '=', name)], limit=1)
        if not rec:
            rec = self.env[model].sudo().create({'name': name})
        return rec.id

    def _get_default_uom_unit(self):
        """
        Trả về record uom.uom cho UoM tên 'Cái' thuộc category 'Unit' (nếu có).
        Fallback lần 1: tìm uom có name='Cái' bất kể category.
        Fallback lần 2: xmlid chuẩn của Odoo 'uom.product_uom_unit' (Units).
        Không có nữa -> trả False (để Odoo tự default), đồng thời log cảnh báo.
        """
        Uom = self.env['uom.uom'].sudo()
        UomCateg = self.env['uom.category'].sudo()

        # Tìm category "Unit" (tên hiển thị)
        unit_categ = UomCateg.search([('name', '=', 'Unit')], limit=1)

        if unit_categ:
            uom = Uom.search([('name', '=', 'Cái'), ('category_id', '=', unit_categ.id)], limit=1)
            if uom:
                return uom

        # Fallback: chỉ theo tên 'Cái'
        uom = Uom.search([('name', '=', 'Cái')], limit=1)
        if uom:
            return uom

        # Fallback: xmlid chuẩn của Odoo (Units)
        try:
            uom_xmlid = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
            if uom_xmlid:
                return uom_xmlid
        except Exception:
            pass

        _logger.warning("⚠ Không tìm thấy UoM 'Cái'/'Unit' và cũng không lấy được 'uom.product_uom_unit'.")
        return False
