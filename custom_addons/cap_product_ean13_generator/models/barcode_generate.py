
import base64
import logging
import os
import random

from barcode.ean import EAN13

from datetime import datetime

from io import BytesIO

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

from barcode.writer import ImageWriter



class CapProductGenerateBarcodeManually(models.TransientModel):
    _name = "cap.product.generate.barcode.manually"

    type_generate = fields.Selection(
        [
            ("date", "Generate Barcode EAN13 through Current Date"),
            (
                "random",
                "Generate Barcode EAN13 through Random Number",
            ),
        ],
        string="Barcode generate options",
        default="date",
    )

    def generate_barcode_manually(self):
        for record in self.env["product.product"].browse(
            self._context.get("active_id")
        ):
            if self.type_generate == "date":
                barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                    "%s%s" % (record.id, datetime.now().strftime("%d%m%y%H%M"))
                )
            else:
                number_random = int("%0.13d" % random.randint(0, 999999999999))
                barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                    "%s" % (number_random)
                )
            # Create a barcode image
            ean = EAN13(barcode_str, writer=ImageWriter())
            image = ean.render()

            # Convert the image to base64
            image_buffer = BytesIO()

            image.save(image_buffer, format="PNG")
            image_data = base64.b64encode(image_buffer.getvalue()).decode('utf-8')
            record.write({"barcode": barcode_str, "image_product": image_data})
        return True


class cap_generate_product_barcode(models.TransientModel):
    _name = "cap.product.generate.barcode"

    overwrite = fields.Boolean(String="Overwrite Exists Ean13")
    type_generate = fields.Selection(
        [
            ("date", "Generate Barcde EAN13 (through Current date)"),
            (
                "random",
                "Generate Barcde EAN13 (through random number)",
            ),
        ],
        string="Barcode Generate options",
        default="date",
    )

    def generate_barcode(self):
        for record in self.env["product.product"].browse(
            self._context.get("active_ids")
        ):
            if not self.overwrite and record.barcode:
                continue

            if self.type_generate == "date":
                barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                    "%s%s" % (record.id, datetime.now().strftime("%d%m%y%H%M"))
                )
            else:
                number_random = int("%0.13d" % random.randint(0, 999999999999))
                barcode_str = self.env["barcode.nomenclature"].sanitize_ean(
                    "%s" % (number_random)
                )

            # Create a barcode image
            ean = EAN13(barcode_str, writer=ImageWriter())
            image = ean.render()

            # Convert the image to base64
            image_buffer = BytesIO()

            image.save(image_buffer, format="PNG")
            image_data = base64.b64encode(image_buffer.getvalue()).decode('utf-8')
            record.write({"barcode": barcode_str,"image_product": image_data})
        return True

