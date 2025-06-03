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
            barcode = row.get('Mã vạch', False)

            x_origin_name = self._clean_string(row.get('Nguồn gốc'))
            x_group_name = self._clean_string(row.get('Nhóm VTHH'))
            x_property_name = self._clean_string(row.get('Tính chất'))
            uom_name = self._clean_string(row.get('Đơn vị tính'))  # Giả sử cột đơn vị tính tên là 'Đơn vị tính'

            vat = row.get('Thuế suất GTGT', 0)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)

            vat_float = self._safe_float(vat)

            # Lấy hoặc tạo đơn vị tính theo lowercase
            uom_id = False
            if uom_name:
                uom_id = self._get_or_create_uom(uom_name)

            # Kiểm tra sản phẩm theo default_code
            product_obj = self.env["product.template"]
            existing_product = False
            if default_code:
                existing_product = product_obj.search([('default_code', '=', default_code)], limit=1)

            values = {
                "name": str(name).strip(),
                "default_code": default_code,
                "standard_price": self._safe_float(cost_price),
                "list_price": self._safe_float(price1),
                "taxes_id": [(6, 0, self._get_tax_ids(vat_float))],
                "type": 'consu',
                "tracking": 'none',
                'is_storable': True,
                "uom_id": uom_id,
                "uom_po_id": uom_id,
            }
            if barcode and not pd.isna(barcode) and str(barcode).strip().lower() != 'nan':
                values["barcode"] = barcode

            if x_origin_name:
                values["x_origin"] = self._get_or_create_m2o("product.origin", x_origin_name)
            if x_group_name:
                values["x_group"] = self._get_or_create_m2o("product.group", x_group_name)
            if x_property_name:
                values["x_property"] = self._get_or_create_m2o("product.property", x_property_name)

            if existing_product:
                # Cập nhật sản phẩm có sẵn
                existing_product.write(values)
            else:
                # Tạo mới sản phẩm
                product_obj.create(values)

    def _get_or_create_uom(self, name):
        # So sánh tên đơn vị tính không phân biệt hoa thường
        uom_obj = self.env['uom.uom'].sudo()
        name_lower = name.lower()
        # Tìm đơn vị tính đã có theo lower name
        uoms = uom_obj.search([])
        for u in uoms:
            if u.name and u.name.lower() == name_lower:
                return u.id
        # Nếu chưa có thì tạo mới
        new_uom = uom_obj.create({'name': name, 'category_id': self._get_default_uom_category()})
        return new_uom.id

    def _get_default_uom_category(self):
        # Lấy category mặc định (ví dụ category sản phẩm)
        category = self.env['uom.category'].search([('name', '=', 'Unit')], limit=1)
        if not category:
            category = self.env['uom.category'].search([], limit=1)
        return category.id if category else False

    # Giữ nguyên các hàm hỗ trợ _clean_string, _safe_float, _get_tax_ids, _get_or_create_m2o

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
