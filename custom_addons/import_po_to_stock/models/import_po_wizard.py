from odoo import models, fields, _
import base64
import tempfile
import pandas as pd

class ImportPOWizard(models.TransientModel):
    _name = "import.po.wizard"
    _description = "Import PO into Stock"

    file = fields.Binary("Excel File", required=True)
    filename = fields.Char("File Name")

    def action_import(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp_path = tmp.name

        df = pd.read_excel(tmp_path)
        df.fillna("", inplace=True)

        grouped = {}

        for index, row in df.iterrows():
            product_code = str(row.get("Mã hàng", "")).strip()
            product_name = str(row.get("Tên hàng", "")).strip()
            qty = float(row.get("Số lượng", 0))
            location_code = str(row.get("Mã kho", "")).strip()

            if not product_code or not location_code or qty <= 0:
                continue

            product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
            if not product:
                tmpl = self.env['product.template'].create({
                    'name': product_name or product_code,
                    'default_code': product_code,
                    'type': 'product',
                    'purchase_ok': True,
                    'sale_ok': False,
                })
                product = tmpl.product_variant_id

            warehouse = self.env['stock.warehouse'].search([('code', '=', location_code)], limit=1)
            if not warehouse:
                continue  # skip if warehouse code not found

            if warehouse.id not in grouped:
                grouped[warehouse.id] = []

            grouped[warehouse.id].append((product, qty))

        for warehouse_id, lines in grouped.items():
            picking = self.env['stock.picking'].create({
                'picking_type_id': self.env['stock.picking.type'].search([
                    ('code', '=', 'incoming'),
                    ('warehouse_id', '=', warehouse_id)
                ], limit=1).id,
                'location_id': self.env['stock.picking.type'].search([
                    ('code', '=', 'incoming'),
                    ('warehouse_id', '=', warehouse_id)
                ], limit=1).default_location_src_id.id,
                'location_dest_id': self.env['stock.picking.type'].search([
                    ('code', '=', 'incoming'),
                    ('warehouse_id', '=', warehouse_id)
                ], limit=1).default_location_dest_id.id,
                'origin': self.filename or _("PO Import")
            })

            for product, qty in lines:
                self.env['stock.move'].create({
                    'name': product.name,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': product.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
