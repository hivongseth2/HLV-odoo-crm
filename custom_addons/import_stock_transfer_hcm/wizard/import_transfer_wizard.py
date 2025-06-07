from odoo import models, fields, _
import base64
import tempfile
import pandas as pd
import logging

_logger = logging.getLogger(__name__)

class ImportTransferWizard(models.TransientModel):
    _name = "import.transfer.wizard"
    _description = "Import Stock Transfers for HCM"

    file = fields.Binary("Excel File", required=True)
    filename = fields.Char("File Name")

    def action_import(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp_path = tmp.name

        df = pd.read_excel(tmp_path, header=0)
        df.fillna("", inplace=True)

        # Group theo refno_finance
        grouped = df.groupby("refno_finance")

        for refno, group in grouped:
            direction = None
            first_row = group.iloc[0]
            from_code = str(first_row.get("from_stock_code")).strip().upper()
            to_code = str(first_row.get("to_stock_code")).strip().upper()

            if from_code == "HCM":
                direction = "outgoing"
            elif to_code == "HCM":
                direction = "incoming"
            else:
                _logger.warning("Bỏ qua chứng từ %s không liên quan HCM", refno)
                continue

            warehouse = self.env['stock.warehouse'].search([('code', '=', 'KHSG')], limit=1)
            if not warehouse:
                _logger.warning("Không tìm thấy kho KHSG (HCM)")
                continue

            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', direction),
                ('warehouse_id', '=', warehouse.id)
            ], limit=1)

            if not picking_type:
                _logger.warning("Không tìm thấy picking type: %s", direction)
                continue

            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
                'origin': refno
            })
            _logger.info("Tạo phiếu %s: %s", direction, refno)

            for _, row in group.iterrows():
                product_code = str(row.get("inventory_item_code")).strip()
                product_name = str(row.get("description")).strip()
                uom_name = str(row.get("unit_name")).strip()
                qty = float(row.get("quantity", 0))

                if not product_code or not product_name or qty <= 0:
                    _logger.warning("Bỏ qua dòng không hợp lệ: %s", row.to_dict())
                    continue

                # Xử lý đơn vị
                category = self.env['uom.category'].search([('name', 'ilike', 'đơn vị')], limit=1)
                if not category:
                    category = self.env['uom.category'].create({'name': 'Đơn vị'})

                uom = self.env['uom.uom'].search([
                    ('name', 'ilike', uom_name),
                    ('category_id', '=', category.id)
                ], limit=1)

                if not uom:
                    existing_ref = self.env['uom.uom'].search([
                        ('category_id', '=', category.id),
                        ('uom_type', '=', 'reference')
                    ], limit=1)
                    uom = self.env['uom.uom'].create({
                        'name': uom_name,
                        'category_id': category.id,
                        'uom_type': 'smaller' if existing_ref else 'reference',
                        'factor': 1.0,
                        'factor_inv': 1.0,
                        'rounding': 1.0,
                    })

                product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
                if not product:
                    tmpl = self.env['product.template'].create({
                        'name': product_name,
                        'default_code': product_code,
                        'type': 'product',
                        'uom_id': uom.id,
                        'uom_po_id': uom.id,
                        'purchase_ok': False,
                        'sale_ok': False,
                    })
                    product = tmpl.product_variant_id

                self.env['stock.move'].create({
                    'name': product_name,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
                _logger.info("  + Tạo dòng chuyển: %s x%s", product_code, qty)
