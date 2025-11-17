# # controllers/zalo_verify.py
# from odoo import http

# class ZaloVerifyController(http.Controller):
#     @http.route('/zalo_verifierKlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt.html', type='http', auth='public', csrf=False)
#     def zalo_verify(self, **kw):
#         html = """
# <!DOCTYPE html>
# <html lang="en">
# <head>
#     <meta property="zalo-platform-site-verification" content="KlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt" />
    
# </head>
# <body>
# There Is No Limit To What You Can Accomplish Using Zalo!
# </body>
# </html>
# """
#         return html



from odoo import http
from odoo.http import request

class ZaloVerifyController(http.Controller):

    TOKENS = [
        "KlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt",
        "CuIw8EUG4oeaWgOA_Aey27sgfoUHt75wDpOv",
        
    ]

    @http.route([
        '/zalo_verifierKlhW2wRGLp15rFikZ_v-4tVer0kRdWDKCpCt.html',
        '/zalo_verifierCuIw8EUG4oeaWgOA_Aey27sgfoUHt75wDpOv.html',
    ], type='http', auth='public', csrf=False)
    def zalo_verify(self, **kw):
        path = request.httprequest.path
        token = ""
        for code in self.TOKENS:
            if code in path:
                token = code
                break

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta property="zalo-platform-site-verification"
          content="{token}" />
</head>
<body>
There Is No Limit To What You Can Accomplish Using Zalo!
</body>
</html>
"""
        return html
