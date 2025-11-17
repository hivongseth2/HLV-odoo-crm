# controllers/zalo_verify.py
from odoo import http

class ZaloVerifyController(http.Controller):
    @http.route('/zalo_verifierKlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt.html', type='http', auth='public', csrf=False)
    def zalo_verify(self, **kw):
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta property="zalo-platform-site-verification" content="KlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt" />
    <meta name="zalo-platform-site-verification" content="CuIw8EUG4oeaWgOA_Aey27sgfoUHt75wDpOv" />
</head>
<body>
There Is No Limit To What You Can Accomplish Using Zalo!
</body>
</html>
"""
        return html
