from odoo import models, fields, _
import base64
import tempfile
import pandas as pd
import logging

_logger = logging.getLogger(__name__)

class ImportPOWizard(models.TransientModel):
    _name = "import.po.wizard"
    _description = "Import PO into Stock"

    file = fields.Binary("Excel File", required=True)
    filename = fields.Char("File Name")

    def action_import(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp_path = tmp.name

        _logger.info("Reading Excel file from path: %s", tmp_path)
        df = pd.read_excel(tmp_path, header=3)
        df.fillna("", inplace=True)

        grouped_invoices = df.groupby("Đơn mua hàng")

        for invoice_number, group in grouped_invoices:
            if not invoice_number:
                _logger.warning("Skipping invoice with empty number.")
                continue

            first_row = group.iloc[0]
            supplier_name = first_row["Tên nhà cung cấp"]
            warehouse_name = first_row["Tên kho"]

            # Create or get supplier
            partner = self.env["res.partner"].search([("name", "=", supplier_name)], limit=1)
            if not partner:
                partner = self.env["res.partner"].create({
                    "name": supplier_name,
                    "supplier_rank": 1,
                })
                _logger.info("Created new supplier: %s", supplier_name)
            else:
                _logger.info("Using existing supplier: %s", supplier_name)

            # Get warehouse by name
            warehouse = self.env["stock.warehouse"].search([("name", "ilike", warehouse_name)], limit=1)
            if not warehouse:
                _logger.warning("Warehouse not found for name: %s", warehouse_name)
                continue

            picking_type = self.env["stock.picking.type"].search([
                ("code", "=", "incoming"),
                ("warehouse_id", "=", warehouse.id)
            ], limit=1)
            if not picking_type:
                _logger.warning("No picking type found for warehouse %s", warehouse.name)
                continue

            picking = self.env["stock.picking"].create({
                "partner_id": partner.id,
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "origin": f"Hóa đơn {invoice_number}"
            })
            _logger.info("Created picking for invoice %s", invoice_number)

            for _, row in group.iterrows():
                code = str(row.get("Mã hàng")).strip()
                name = str(row.get("Tên hàng")).strip()
                uom_name = str(row.get("ĐVT")).strip()
                qty = float(row.get("Số lượng mua", 0))

                if not code or not name or qty <= 0:
                    _logger.warning("Skipping invalid line: %s", row.to_dict())
                    continue

                # Find or create UOM
                
                uom_category = self.env['uom.category'].search([('name', 'ilike', 'đơn vị')], limit=1)
                if not uom_category:
                    uom_category = self.env['uom.category'].create({'name': 'Đơn vị'})

                uom = self.env['uom.uom'].search([
                    ('name', 'ilike', uom_name),
                    ('category_id', '=', uom_category.id)
                ], limit=1)


                if not uom:
                    existing_ref = self.env['uom.uom'].search([
                        ('category_id', '=', uom_category.id),
                        ('uom_type', '=', 'reference')
                    ], limit=1)
                    
                    if existing_ref:
                        # Tạo UOM loại 'smaller' với factor = 1
                        uom = self.env['uom.uom'].create({
                            'name': uom_name,
                            'category_id': uom_category.id,
                            'uom_type': 'smaller',
                            'factor': 1.0,
                            'factor_inv': 1.0,
                            'rounding': 1.0,
                        })
                        _logger.info("Created new non-reference UOM: %s (category: %s)", uom_name, uom_category.name)
                    else:
                        uom = self.env['uom.uom'].create({
                            'name': uom_name,
                            'category_id': uom_category.id,
                            'uom_type': 'reference',
                            'rounding': 1.0,
                        })
                        _logger.info("Created new reference UOM: %s (category: %s)", uom_name, uom_category.name)

                # Find or create product
                product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
                if not product:
                    tmpl = self.env["product.template"].create({
                        "name": name,
                        "default_code": code,
                        "type": "consu",
                        "uom_id": uom.id,
                        "uom_po_id": uom.id,
                        "purchase_ok": True,
                        "sale_ok": False,
                        'is_storable': True,
                    })
                    product = tmpl.product_variant_id
                    _logger.info("Created product: %s", code)
                else:
                    _logger.info("Using existing product: %s", code)

                self.env["stock.move"].create({
                    "name": name,
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "product_uom": uom.id,
                    "picking_id": picking.id,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                })
                _logger.debug("Created move line for %s x%s", code, qty)
