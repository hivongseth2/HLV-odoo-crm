from odoo import models, fields, api
import pandas as pd
import base64
import tempfile
import logging

_logger = logging.getLogger(__name__)

class ImportStockQuantWizard(models.TransientModel):
    _name = "import.stock.quant.wizard"
    _description = "Import tồn kho theo vị trí"

    file = fields.Binary(string="File Excel", required=True)
    filename = fields.Char(string="Tên tập tin")

    def action_import(self):
        _logger.info("=== Bắt đầu import tồn kho từ file Excel ===")

        if not self.file:
            _logger.warning("Không có file được upload.")
            return

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(base64.b64decode(self.file))
                tmp.seek(0)
                df = pd.read_excel(tmp.name)

            _logger.info("Đọc file thành công: %s dòng dữ liệu", len(df))

            imported_count = 0
            skipped_count = 0

            inventory = self.env['stock.inventory'].create({
                'name': 'Import tồn kho từ Excel',
                'filter': 'partial',
            })

            for idx, row in df.iterrows():
                product_code = row.get("Mã sản phẩm")
                location_name = row.get("Vị trí")
                quantity = row.get("Số lượng", 0)

                if not product_code or not location_name:
                    skipped_count += 1
                    continue

                product = self.env["product.product"].search([
                    "|", "|", "|",
                    ("default_code", "=", str(product_code)),
                    ("barcode", "=", str(product_code)),
                    ("reference_code", "=", str(product_code)),
                    ("name", "=", str(product_code))
                ], limit=1)

                if not product:
                    _logger.warning("Không tìm thấy sản phẩm '%s' ở dòng %s", product_code, idx + 1)
                    skipped_count += 1
                    continue

                location = self.env["stock.location"].search([
                    "|",
                    ("complete_name", "=", str(location_name).strip()),
                    ("barcode", "=", str(location_name).strip())
                ], limit=1)

                if not location:
                    _logger.warning("Không tìm thấy vị trí '%s' ở dòng %s", location_name, idx + 1)
                    skipped_count += 1
                    continue

                self.env['stock.inventory.line'].create({
                    'inventory_id': inventory.id,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'location_id': location.id,
                    'product_qty': quantity,
                })

                imported_count += 1

            inventory.action_start()
            inventory.action_validate()

            _logger.info("🎯 Import hoàn tất: %s dòng thành công, %s dòng bị bỏ qua.", imported_count, skipped_count)

        except Exception as e:
            _logger.exception("🔥 Lỗi khi import tồn kho: %s", str(e))
            raise
