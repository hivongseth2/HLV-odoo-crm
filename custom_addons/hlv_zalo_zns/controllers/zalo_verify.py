# controllers/zalo_verify.py
from odoo import http

# TH 1: route cố định đúng tên file Zalo yêu cầu (đơn giản nhất)
class ZaloVerifyFixed(http.Controller):
    @http.route(
        ['/zalo_verifierKlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt.html'],
        type='http', auth='public', csrf=False, website=True
    )
    def zalo_verify_fixed(self, **kwargs):
        # Theo tài liệu, nội dung thường chỉ cần là 1 HTML hợp lệ (có thể rỗng body)
        return """
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>ok</body></html>
""".strip()
