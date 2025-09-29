# -*- coding: utf-8 -*-
from odoo import api, models
from io import BytesIO
import base64

# dùng qrcode để tạo QR base64
try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except Exception:
    qrcode = None


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _qr_data_uri(self, value, box_size=3, border=2):
        """
        Trả về data-uri PNG của QR cho 'value'.
        Dùng trực tiếp trong QWeb: <img t-att-src="o._qr_data_uri(text)"/>
        """
        if not value:
            value = ''
        if qrcode is None:
            # fallback cực đoan: trả ảnh trắng 1x1 để không vỡ layout
            empty_png = base64.b64encode(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
                b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
            ).decode()
            return f"data:image/png;base64,{empty_png}"

        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=int(box_size or 3),
            border=int(border or 2),
        )
        qr.add_data(value)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
