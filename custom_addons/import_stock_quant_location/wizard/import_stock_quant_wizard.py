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

            for idx, row in df.iterrows():
                product_code = row.get("Mã sản phẩm")
                location_name = row.get("Vị trí")
                quantity = row.get("Số lượng", 0)

                _logger.debug("→ Dòng %s: sản phẩm='%s', vị trí='%s', số lượng=%s", idx + 1, product_code, location_name, quantity)

                if not product_code or not location_name:
                    _logger.warning("⛔ Thiếu mã sản phẩm hoặc vị trí ở dòng %s. Bỏ qua.", idx + 1)
                    skipped_count += 1
                    continue

                # Tìm sản phẩm
                product = self.env["product.product"].search([
                    "|", ("default_code", "=", str(product_code)), 
                         ("barcode", "=", str(product_code))
                ], limit=1)

                if not product:
                    _logger.warning("⛔ Không tìm thấy sản phẩm '%s' ở dòng %s.", product_code, idx + 1)
                    skipped_count += 1
                    continue

                # Tìm vị trí
                location = self.env["stock.location"].search([
                    "|", 
                    ("complete_name", "=", str(location_name).strip()),
                    ("barcode", "=", str(location_name).strip())
                ], limit=1)

                if not location:
                    _logger.warning("⛔ Không tìm thấy vị trí '%s' ở dòng %s.", location_name, idx + 1)
                    skipped_count += 1
                    continue

                # Tạo hoặc cập nhật tồn kho
                quant = self.env["stock.quant"].search([
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id)
                ], limit=1)

                if quant:
                    quant.sudo().write({
                        'inventory_quantity': quantity,
                    })
                else:
                    quant = self.env["stock.quant"].sudo().create({
                        "product_id": product.id,
                        "location_id": location.id,
                        "inventory_quantity": quantity,
                    })

                quant.sudo()._apply_inventory()

                _logger.info("✅ Đã cập nhật tồn kho cho '%s' tại '%s' số lượng %.2f", product_code, location_name, quantity)
                imported_count += 1

            _logger.info("🎯 Import hoàn tất: %s dòng thành công, %s dòng bị bỏ qua.", imported_count, skipped_count)

        except Exception as e:
            _logger.exception("🔥 Lỗi khi import tồn kho: %s", str(e))
            raise
